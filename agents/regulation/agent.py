"""Regulation agent: RAG over SEC regulations. Attaches governing CFR citations to each
cross-check finding, then forwards to the report agent. Also serves refinement requests
from the report agent when a finding came back with weak or missing citations."""
from __future__ import annotations

import logging

from common import bus, config
from common.schemas import AuditMessage, Citation, Status

from agents.regulation.retriever import Retriever

AGENT = "regulation"
log = logging.getLogger(AGENT)


def attach_citations(retriever: Retriever, msg: AuditMessage) -> int:
    refining = msg.refinement_round > 0
    industry = msg.company.industry if msg.company else "general"
    n = 0
    for f in msg.findings:
        if refining and f.check_id not in msg.refine_check_ids:
            continue
        if f.status == Status.NOT_APPLICABLE and not refining:
            continue
        if refining:
            # Broaden the query with the finding's own wording and pull more candidates.
            query = f"{f.reg_query} {f.title}. {f.detail}"
            hits = retriever.search(query, k=4, candidates=80, industry=industry)
        else:
            k = 3 if f.status in (Status.WARN, Status.FAIL) else 2
            hits = retriever.search(f.reg_query, k=k, industry=industry)
        f.citations = [Citation(citation=h.citation, heading=h.heading, excerpt=h.excerpt,
                                source_url=h.source_url, score=h.score) for h in hits]
        n += len(hits)
    return n


def make_handler(r, retriever: Retriever):
    def handle(msg: AuditMessage) -> None:
        n = attach_citations(retriever, msg)
        note = f"round {msg.refinement_round}: {n} citations"
        msg.stamp(AGENT, config.CONSUMER_NAME, note)
        bus.set_status(r, msg.job_id, "drafting_report")
        bus.publish(r, config.STREAM_REPORT, msg)
        log.info("job %s %s", msg.job_id, note)
    return handle


def main() -> None:
    bus.setup_logging()
    retriever = Retriever()
    log.info("loaded %d regulation chunks (mode=%s)", len(retriever.chunks), retriever.mode)
    r = bus.connect()
    bus.Worker(r, config.STREAM_REGULATION, AGENT, make_handler(r, retriever)).run_forever()


if __name__ == "__main__":
    main()
