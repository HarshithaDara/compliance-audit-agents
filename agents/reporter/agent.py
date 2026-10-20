"""Report agent: reviews the evidence it receives, sends weakly-cited findings back to the
regulation agent for one refinement round, then drafts and stores the audit report."""
from __future__ import annotations

import json
import logging

from common import bus, config
from common.schemas import AuditMessage, Status

from agents.reporter.drafter import GroundingError, TemplateDrafter, make_drafter

AGENT = "reporter"
log = logging.getLogger(AGENT)

MIN_CITATION_SCORE = 0.5
MAX_REFINEMENT_ROUNDS = 1


def weakly_cited(msg: AuditMessage) -> list[str]:
    """Flagged findings whose best citation is missing or below the relevance bar."""
    out = []
    for f in msg.findings:
        if f.status not in (Status.WARN, Status.FAIL):
            continue
        best = max((c.score for c in f.citations), default=0.0)
        if best < MIN_CITATION_SCORE:
            out.append(f.check_id)
    return out


def report_key(job_id: str) -> str:
    return f"audit:job:{job_id}:report"


def make_handler(r, drafter=None):
    drafter = drafter or make_drafter()
    fallback = TemplateDrafter()

    def handle(msg: AuditMessage) -> None:
        weak = weakly_cited(msg)
        if weak and msg.refinement_round < MAX_REFINEMENT_ROUNDS:
            msg.refinement_round += 1
            msg.refine_check_ids = weak
            msg.stamp(AGENT, config.CONSUMER_NAME, f"requested citation refinement for {', '.join(weak)}")
            bus.set_status(r, msg.job_id, "refining_citations", refine=",".join(weak))
            bus.publish(r, config.STREAM_REGULATION, msg)
            log.info("job %s: asked regulation agent to refine %s", msg.job_id, weak)
            return

        used = drafter
        try:
            msg.stamp(AGENT, config.CONSUMER_NAME, f"drafting with {drafter.name}")
            report = drafter.draft(msg)
        except GroundingError as e:
            log.warning("job %s: draft rejected (%s); using template drafter", msg.job_id, e)
            msg.trace[-1].note += f"; rejected: {e}; fell back to template"
            used = fallback
            report = fallback.draft(msg)

        flagged = [f for f in msg.findings if f.status in (Status.WARN, Status.FAIL)]
        summary = {
            "job_id": msg.job_id, "ticker": msg.ticker, "company": msg.company.name,
            "fiscal_year": msg.fiscal_year, "accession": msg.company.accession,
            "checks": len(msg.findings), "flagged": [f.check_id for f in flagged],
            "drafter": used.name, "refinement_rounds": msg.refinement_round,
        }
        pipe = r.pipeline()
        pipe.set(report_key(msg.job_id), report, ex=config.JOB_TTL_SECONDS)
        pipe.set(f"audit:job:{msg.job_id}:result", msg.model_dump_json(), ex=config.JOB_TTL_SECONDS)
        pipe.execute()
        bus.set_status(r, msg.job_id, "completed", summary=json.dumps(summary))
        log.info("job %s completed: %s", msg.job_id, summary)
    return handle


def main() -> None:
    bus.setup_logging()
    r = bus.connect()
    drafter = make_drafter()
    log.info("drafter: %s", drafter.name)
    bus.Worker(r, config.STREAM_REPORT, AGENT, make_handler(r, drafter)).run_forever()


if __name__ == "__main__":
    main()
