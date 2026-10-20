"""Cross-check agent: pulls a company's real XBRL financials from SEC EDGAR and runs
accounting cross-checks, then hands the findings to the regulation agent."""
from __future__ import annotations

import logging

from common import bus, config
from common.schemas import AuditMessage

from agents.crosscheck import checks
from agents.crosscheck.sec_client import SecClient, SecNotFound

AGENT = "crosscheck"
log = logging.getLogger(AGENT)


def make_handler(r, sec: SecClient):
    def handle(msg: AuditMessage) -> None:
        bus.set_status(r, msg.job_id, "crosschecking", ticker=msg.ticker)
        try:
            cik, _title = sec.lookup_cik(msg.ticker)
            facts = sec.company_facts(cik)
            filing, findings = checks.run_all(facts, msg.fiscal_year)
        except (ValueError, SecNotFound) as e:
            # Bad input (no such fiscal year, no XBRL 10-K): fail the job without retrying.
            bus.set_status(r, msg.job_id, "failed", failed_in=AGENT, error=str(e))
            return
        sic, sic_desc = sec.sic(cik)
        msg.company = checks.company_context(msg.ticker, cik, facts, filing, sic, sic_desc)
        msg.fiscal_year = filing.fy
        msg.findings = findings
        flagged = sum(f.status.value in ("warn", "fail") for f in findings)
        msg.stamp(AGENT, config.CONSUMER_NAME, f"{len(findings)} checks, {flagged} flagged, accn {filing.accn}")
        bus.set_status(r, msg.job_id, "retrieving_regulations", accession=filing.accn)
        bus.publish(r, config.STREAM_REGULATION, msg)
        log.info("job %s %s FY%s: %d checks, %d flagged", msg.job_id, msg.ticker, filing.fy, len(findings), flagged)
    return handle


def main() -> None:
    bus.setup_logging()
    r = bus.connect()
    bus.Worker(r, config.STREAM_CROSSCHECK, AGENT, make_handler(r, SecClient(r))).run_forever()


if __name__ == "__main__":
    main()
