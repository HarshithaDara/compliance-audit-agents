"""Regulation agent: RAG over SEC regulations. Attaches governing CFR citations to each
cross-check finding, then forwards to the report agent. Also serves refinement requests
from the report agent when a finding came back with weak or missing citations."""
from __future__ import annotations

import logging

from common import bus, config
from common.schemas import AuditMessage, Citation, Status

from agents.regulation.retriever import IN_CORPUS, IN_INDEX_DIR, Retriever

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
        if msg.kind == "document":
            # Document checks name the sections they test ("section 44AD ..."); citing anything
            # else from the memoranda corpus would be a loosely related amendment, not the rule.
            hits = [h for h in hits if h.pinned]
        f.citations = [Citation(citation=h.citation, heading=h.heading, excerpt=h.excerpt,
                                source_url=h.source_url, score=h.score) for h in hits]
        n += len(hits)
    return n


def make_handler(r, retriever: Retriever, retriever_in: Retriever | None = None):
    """retriever serves SEC audits; retriever_in (Indian income-tax / GST law) serves document audits."""
    def handle(msg: AuditMessage) -> None:
        if msg.kind == "document" and retriever_in is None:
            raise RuntimeError("no Indian regulation index loaded for document audits")
        n = attach_citations(retriever_in if msg.kind == "document" else retriever, msg)
        note = f"round {msg.refinement_round}: {n} citations"
        msg.stamp(AGENT, config.CONSUMER_NAME, note)
        bus.set_status(r, msg.job_id, "drafting_report")
        bus.publish(r, config.STREAM_REPORT, msg)
        log.info("job %s %s", msg.job_id, note)
    return handle


def main() -> None:
    bus.setup_logging()
    retriever = Retriever()
    retriever_in = Retriever(IN_INDEX_DIR) if IN_CORPUS.exists() or IN_INDEX_DIR.exists() else None
    log.info("loaded %d SEC and %d Indian regulation chunks (mode=%s)", len(retriever.chunks),
             len(retriever_in.chunks) if retriever_in else 0, retriever.mode)
    r = bus.connect()
    bus.Worker(r, config.STREAM_REGULATION, AGENT, make_handler(r, retriever, retriever_in)).run_forever()


if __name__ == "__main__":
    main()
