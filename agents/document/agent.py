"""Document agent: reads an uploaded PDF bundle (text layer, OCR for scanned pages), extracts the
figures with page provenance, cross-checks them, tests whether the written submission explains
each discrepancy, and hands the findings to the regulation agent.

Confidentiality: the PDF arrives as a short-lived Redis blob, deleted once the job has been
processed (kept until then so a crashed replica's retry can read it; it expires regardless after
DOC_BLOB_TTL_SECONDS). Page text stays inside this process; only extracted figures, masked identifiers and
short quotes travel on. Logs carry job ids and counts, never file names or text.
"""
from __future__ import annotations

import logging

from common import bus, config
from common.blobs import delete_pdf, load_pdf
from common.schemas import AuditMessage, Status

from agents.document import case, checks, classify, llm, narrative, parsers
from agents.document.pdftext import UnreadablePdf, extract_pages, rapidocr_engine

AGENT = "document"
log = logging.getLogger(AGENT)

AI_PAGE_TYPES = {"other", "assessment_order", "agreement"}


def analyse(pages: list, facts: parsers.Facts, reader: llm.Reader | None = None, progress=lambda: None) -> list:
    """All checks over classified pages and their facts: return-level checks, case-level checks,
    narrative coverage, then materiality and bearing. Pure, so the evaluation harness can run it."""
    submission = [p for p in pages if p.doc_type == "submission"]
    findings = checks.run_all(facts, "\n".join(p.text for p in submission))
    findings += case.run_case_checks(facts, pages, findings)
    findings.append(narrative.assess(findings, submission, reader, progress=progress))
    case.annotate(findings, case_mode=bool(facts.first("case.notice") or facts.first("order")))
    return findings


def make_handler(r, ocr="auto", reader_factory=llm.make_reader):
    engine = {"ocr": None}

    def ocr_fn(pdf: bytes, number: int) -> str:
        bus.keepalive()
        if engine["ocr"] is None:
            engine["ocr"] = (rapidocr_engine() if ocr == "auto" else ocr) or (lambda _pdf, _n: "")
        return engine["ocr"](pdf, number)

    def handle(msg: AuditMessage) -> None:
        doc = msg.document
        bus.set_status(r, msg.job_id, "reading_document")
        pdf = load_pdf(r, msg.job_id)
        if pdf is None:
            bus.set_status(r, msg.job_id, "failed", failed_in=AGENT,
                           error="the uploaded PDF expired or was already processed; please upload it again")
            return
        try:
            pages = extract_pages(pdf, ocr_fn if ocr is not None else None)
        except UnreadablePdf as e:
            delete_pdf(r, msg.job_id)
            bus.set_status(r, msg.job_id, "failed", failed_in=AGENT, error=str(e))
            return
        del pdf
        classify.classify(pages)
        doc.pages = len(pages)
        doc.ocr_pages = sum(p.method == "ocr" for p in pages)
        doc.empty_pages = sum(p.method == "empty" for p in pages)
        doc.page_types = classify.page_type_counts(pages)

        bus.set_status(r, msg.job_id, "checking_document", pages=len(pages))
        facts = parsers.parse_all(pages)
        doc.assessment_year = checks.assessment_year(facts)
        doc.form = facts.value("itr.form")
        doc.pan_masked = facts.value("itr.pan_masked")
        doc.taxpayer = facts.value("itr.name")
        reader, used = reader_factory(doc.ai_reader)
        doc.ai_reader_used = used
        if reader is not None:
            targets = [p for p in pages if p.doc_type in AI_PAGE_TYPES][:config.DOC_LLM_MAX_PAGES]
            doc.ai_figures = llm.extract_figures(reader, targets, progress=bus.keepalive)
        findings = analyse(pages, facts, reader, progress=bus.keepalive)

        msg.findings = findings
        msg.fiscal_year = int(doc.assessment_year[:4]) - 1 if doc.assessment_year else None
        flagged = sum(f.status in (Status.WARN, Status.FAIL) for f in findings)
        msg.stamp(AGENT, config.CONSUMER_NAME,
                  f"{len(pages)} pages ({doc.ocr_pages} OCR, {doc.empty_pages} unreadable), {len(facts.items)} facts, "
                  f"{len(findings)} checks, {flagged} flagged; reader: {used}")
        bus.set_status(r, msg.job_id, "retrieving_regulations")
        bus.publish(r, config.STREAM_REGULATION, msg)
        delete_pdf(r, msg.job_id)
        log.info("job %s: %d pages, %d facts, %d checks, %d flagged", msg.job_id, len(pages), len(facts.items),
                 len(findings), flagged)
    return handle


def main() -> None:
    bus.setup_logging()
    r = bus.connect()
    bus.Worker(r, config.STREAM_DOCUMENT, AGENT, make_handler(r)).run_forever()


if __name__ == "__main__":
    main()
