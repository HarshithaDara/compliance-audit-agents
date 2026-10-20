"""Document audits: page extraction and classification, parsers, cross-checks, narrative coverage,
the grounded AI reader, and the upload -> document -> regulation -> reporter pipeline.
All inputs are synthetic (tests/doc_factories.py); a local-only test runs on private PDFs if present."""
import io
import json
from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient

from agents.document import agent as document_agent
from agents.document import checks, classify, llm, narrative, parsers
from agents.document.pdftext import Page, extract_pages, printed_page_number
from agents.gateway import app as gateway
from agents.regulation import agent as regulation_agent
from agents.regulation.retriever import IN_INDEX_DIR, INDEX_DIR, Retriever
from agents.reporter import agent as reporter_agent
from agents.reporter.drafter import TemplateDrafter, validate_grounding, GroundingError
from common import blobs, bus, config
from common.schemas import AuditMessage, DocumentContext, Status
from tests import doc_factories as F


def run(pages=None, submission=F.SUBMISSION):
    pages = classify.classify(pages or F.bundle())
    facts = parsers.parse_all(pages)
    return pages, facts, {f.check_id: f for f in checks.run_all(facts, submission)}


# ------------------------------------------------------------------ extraction and classification

def test_pages_are_classified_by_content():
    pages = classify.classify(F.bundle())
    counts = classify.page_type_counts(pages)
    assert counts == {"invoice": 12, "gstr1": 12, "gstr3b": 12, "itr": 4, "cash_withdrawal_certificate": 2,
                      "bank_statement": 2, "ais": 2, "submission": 1, "itr_ack": 1, "tis": 1}


def test_submission_mentioning_an_assessment_order_is_not_one():
    """Regression: a submission page headed 'ASSESSMENT ORDER FOR THE SUBSEQUENT YEAR' was labelled an order."""
    text = "1. ASSESSMENT ORDER FOR THE SUBSEQUENT ASSESSMENT YEAR\nThe assessee respectfully submits that the " \
           "Assessee's returned income was accepted. " + "x" * 300
    assert classify.classify_page(text) == "submission"


def test_printed_page_number_is_read_from_footer():
    assert printed_page_number("some text\n27\nANNEXURE 1", 30) == "27"
    assert printed_page_number("Total 4,20,000\n420000", 30) is None  # an amount, not a page number


_pdf = F.to_pdf


def test_extract_pages_uses_text_layer_and_ocr_for_scanned_pages():
    pdf = _pdf(["Form GSTR-3B\nYear 2022-23\nPeriod April\nSome text for the page\n2", None, "tiny"])
    calls = []

    def fake_ocr(data, number):
        calls.append(number)
        return "CHANNEL PARTNER AGREEMENT made at Bangalore between the parties" if number == 2 else ""
    pages = extract_pages(pdf, fake_ocr)
    assert [p.method for p in pages] == ["text", "ocr", "empty"]
    assert calls == [2, 3] and "Period April" in pages[0].text and pages[0].printed == "2"


def test_unreadable_pdf_is_reported():
    from agents.document.pdftext import UnreadablePdf
    with pytest.raises(UnreadablePdf):
        extract_pages(b"%PDF-1.4 not really a pdf")


# ------------------------------------------------------------------ parsers

def test_itr_and_ack_facts_with_page_provenance():
    _, facts, _ = run()
    assert facts.value("itr.gross_receipts_44ad") == 2420000
    assert facts.value("itr.presumptive_income_44ad") == 500000
    assert facts.value("itr.total_income") == 420000
    assert facts.value("itr.filed_section") == "139(4)" and facts.value("itr.filing_date") == "2023-12-15"
    assert facts.value("itr.pan_masked") == "XXXXX1234F"  # never the full PAN
    receipts = facts.first("itr.gross_receipts_44ad")
    assert receipts.page == 43 and "61i" in receipts.quote
    assert [r.value["head"] for r in facts.all("itr.tds_row")] == ["OS", "BP"]


def test_ais_rows_continuing_on_a_later_page_join_their_own_section():
    """Regression: 194N rows printed on page 2 (after the 194H/194C sections) were attached to 194C,
    and with equal row counts could attach to 194H."""
    _, facts, _ = run()
    rows = {f.value["code"]: f.value["rows"] for f in facts.all("ais.info")}
    assert len(rows["TDS-194N"]) == 4 and sum(r["amount"] for r in rows["TDS-194N"]) == 14500000
    assert len(rows["TDS-194H"]) == 2 and len(rows["TDS-194C"]) == 1


def test_gst_invoice_and_certificate_parsers():
    _, facts, _ = run()
    g1 = {f.value["period"]: f.value["taxable"] for f in facts.all("gstr1.b2b")}
    g3 = {f.value["period"]: f.value["taxable"] for f in facts.all("gstr3b.outward")}
    assert g1["2023-01"] == 199000 and g3 == g1 and len(g1) == 12
    last = facts.all("invoice")[-1].value
    # MAR billed on 15-Apr-2023 is March 2023's service; DEC billed in January is the previous year's.
    assert last["date"] == "2023-04-15" and last["lines"][0]["service_month"] == "2023-03"
    assert facts.all("invoice")[8].value["lines"][0]["service_month"] == "2022-12"
    certs = [(c.value["month"], c.value["amount"], c.value["account"]) for c in facts.all("cert.194n")]
    assert certs == [("2022-05", 3000000, "XX4444"), ("2022-06", 5000000, "XX4444")]


def test_bank_statement_sides_inferred_from_running_balance():
    """Regression: a value date glued to the reference number, and a balance cut to '359000.' by the
    text layer, left rows unparsed or with an unknown side."""
    _, facts, _ = run()
    rows = facts.first("bank.transactions").value["rows"]
    assert [r["direction"] for r in rows] == ["debit", "credit", "credit", "debit", "credit", "debit"]
    assert facts.first("bank.summary").value["account"] == "XX1234"


# ------------------------------------------------------------------ checks

def test_clean_reconciliations_pass():
    _, _, f = run()
    for cid in ("TURNOVER_AIS_VS_ITR", "GSTR1_VS_GSTR3B", "TDS_CREDIT", "AUDIT_44AB", "TAX_COMPUTATION",
                "BANK_STATEMENT_INTEGRITY"):
        assert f[cid].status == Status.PASS, (cid, f[cid].detail)
        assert f[cid].evidence, cid  # every result points at its pages


def test_gst_gap_explained_as_invoice_timing():
    _, _, f = run()
    gst = f["TURNOVER_GST_VS_ITR"]
    assert gst.status == Status.WARN and gst.severity.value == "low"
    assert gst.values["difference"] == 100000 and gst.values["invoices_by_service_month"] == 2420000
    assert "timing difference" in gst.detail


def test_gst_gap_without_invoices_is_medium():
    _, _, f = run(F.bundle(invoices=[]))
    assert f["TURNOVER_GST_VS_ITR"].severity.value == "medium"
    assert f["INVOICES_VS_GSTR1"].status == Status.NOT_APPLICABLE


def test_ais_receipts_above_return_is_a_fail():
    itr = [F.itr_ack(), F.itr_44ad(receipts=2000000, presumptive=400000), F.itr_part_b_ti(), F.itr_tti(), F.itr_tds2()]
    _, _, f = run(F.bundle(itr=itr))
    assert f["TURNOVER_AIS_VS_ITR"].status == Status.FAIL and f["TURNOVER_AIS_VS_ITR"].values["difference"] == 420000


def test_omitted_interest_with_tax_effect_is_high():
    itr = [F.itr_ack(total_income=490000), F.itr_44ad(), F.itr_part_b_ti(total=490000), F.itr_tti(12000, 12000),
           F.itr_tds2()]
    _, _, f = run(F.bundle(itr=itr, tis=[F.tis_page(sb=12000, td=60000)]))
    other = f["OTHER_INCOME_OMITTED"]
    assert other.status == Status.WARN and other.severity.value == "high"
    assert other.values["deduction_80tta"] == 10000 and other.values["tax_effect"] > 0


def test_presumptive_rate_below_minimum_is_high():
    itr = [F.itr_ack(), F.itr_44ad(presumptive=100000), F.itr_part_b_ti(), F.itr_tti(), F.itr_tds2()]
    _, _, f = run(F.bundle(itr=itr))
    assert f["PRESUMPTIVE_44AD"].severity.value == "high" and "below the statutory minimum" in f["PRESUMPTIVE_44AD"].detail


def test_commission_receipts_raise_44ad6_risk():
    _, _, f = run()
    assert "44AD(6)" in f["PRESUMPTIVE_44AD"].detail and f["PRESUMPTIVE_44AD"].values["commission_receipts_194h"] == 100000


def test_cash_withdrawal_months_without_certificates():
    _, _, f = run()
    cash = f["CASH_WITHDRAWAL_194N"]
    assert cash.status == Status.WARN
    assert cash.values["months_without_certificate"] == ["2022-04", "2022-07"]
    assert cash.values["uncovered_amount"] == 6500000


def test_cash_withdrawals_without_any_certificate_fail():
    _, _, f = run(F.bundle(certificates=[]))
    assert f["CASH_WITHDRAWAL_194N"].status == Status.FAIL


def test_third_party_credits_and_declared_payer_from_ais():
    _, _, f = run()
    bank = f["BANK_THIRD_PARTY_CREDITS"]
    assert bank.values["from_declared_payer"] == 150000.5  # payer name taken from the AIS, not hard-coded
    assert [c["from"] for c in bank.values["large_other_credits"]] == ["ACME ENTERPRISES"]


def test_late_filing_and_234f():
    _, _, f = run()
    assert f["LATE_FILING"].status == Status.WARN and f["LATE_FILING"].values["expected_fee"] == 1000
    itr = [F.itr_ack(filed="139(1)- On or before due date"), F.itr_44ad(), F.itr_part_b_ti(), F.itr_tti(), F.itr_tds2()]
    _, _, f = run(F.bundle(itr=itr))
    assert f["LATE_FILING"].status == Status.PASS


def test_missing_documents_make_checks_not_applicable():
    _, _, f = run([Page(1, F.SUBMISSION, "text")])
    assert all(x.status == Status.NOT_APPLICABLE for x in f.values())


def test_inr_formatting():
    assert checks.inr(1234567890) == "₹1,23,45,67,890" and checks.inr(12345) == "₹12,345"
    assert checks.inr(1234567.5) == "₹12,34,567.50"


# ------------------------------------------------------------------ narrative coverage and AI reader

class FakeReader(llm.Reader):
    name = "fake"

    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def complete_json(self, system, prompt):
        self.prompts.append(prompt)
        return self.answer(prompt) if callable(self.answer) else self.answer


def test_narrative_keyword_coverage():
    pages, _, f = run()
    submission = [p for p in pages if p.doc_type == "submission"]
    result = narrative.assess(list(f.values()), submission)
    cov = result.values["coverage"]
    assert cov["CASH_WITHDRAWAL_194N"]["status"] == "mentioned"
    assert cov["OTHER_INCOME_OMITTED"]["status"] == "unexplained"
    assert result.status == Status.WARN and "keyword matching only" in result.detail


def test_ai_reader_can_confirm_an_explanation_only_with_a_real_quote():
    pages, _, f = run()
    submission = [p for p in pages if p.doc_type == "submission"]
    real = "the WLATMO issues a monthly certificate to the bank confirming the withdrawals."
    result = narrative.assess(list(f.values()), submission, FakeReader({"addresses": True, "quote": real}))
    assert result.values["coverage"]["CASH_WITHDRAWAL_194N"]["status"] == "explained"
    _, _, f = run()
    invented = {"addresses": True, "quote": "The assessee obtained certificates for every month without exception."}
    result = narrative.assess(list(f.values()), submission, FakeReader(invented))
    assert result.values["coverage"]["CASH_WITHDRAWAL_194N"]["status"] == "mentioned"


def test_ai_figures_must_appear_on_their_page():
    page = Page(5, "Returned Income Rs. 6,10,190\nTotal receipts 33,85,602 for the year", "text", "2")
    reader = FakeReader({"figures": [{"label": "returned income", "value": "6,10,190", "quote": "Returned Income Rs. 6,10,190"},
                                     {"label": "made up", "value": "9,99,999", "quote": "nowhere"},
                                     {"label": "receipts", "value": "3385602", "quote": "paraphrased"}]})
    figs = llm.extract_figures(reader, [page])
    assert [(f.label, f.page, f.printed_page) for f in figs] == [("returned income", 5, "2"), ("receipts", 5, "2")]
    assert figs[1].quote == "Total receipts 33,85,602 for the year"  # replaced by the real line


def test_reader_failures_do_not_fail_the_audit():
    def boom(_prompt):
        raise ConnectionError("ollama went away")
    assert llm.extract_figures(FakeReader(boom), [Page(1, "Amount 1,23,456", "text")]) == []


def test_local_reader_unavailable_falls_back_to_rules(monkeypatch):
    monkeypatch.setattr(llm.OllamaReader, "available", lambda self: False)
    reader, used = llm.make_reader("local")
    assert reader is None and "unavailable" in used
    assert llm.make_reader("none") == (None, "rules only (AI reader off)")


def test_rupee_amounts_in_a_cloud_draft_must_match_evidence():
    pages, _, f = run()
    msg = AuditMessage.new_document(DocumentContext(filename="x.pdf", sha256="0" * 64, size_bytes=1))
    msg.findings = list(f.values())
    validate_grounding("Business receipts of ₹24,20,000 agree.", msg)
    with pytest.raises(GroundingError):
        validate_grounding("Receipts of ₹31,00,000 were omitted.", msg)


# ------------------------------------------------------------------ pipeline

@pytest.fixture(scope="module")
def retrievers():
    return Retriever(INDEX_DIR, mode="bm25"), Retriever(IN_INDEX_DIR, mode="bm25")


class ExplodingDrafter:
    name = "cloud drafter that must not be used"

    def draft(self, msg):
        raise AssertionError("a confidential document reached the cloud drafter")


@pytest.fixture
def denv(retrievers, monkeypatch):
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(gateway, "_redis", r)
    monkeypatch.setattr(config, "CLAIM_IDLE_MS", 0)
    pdf = _pdf([p.text for p in F.bundle()])
    workers = [
        bus.Worker(r, config.STREAM_DOCUMENT, "document",
                   document_agent.make_handler(r, ocr=None, reader_factory=lambda mode: (None, "rules only")), "doc-0", 10),
        bus.Worker(r, config.STREAM_REGULATION, "regulation", regulation_agent.make_handler(r, *retrievers), "rg-0", 10),
        bus.Worker(r, config.STREAM_REPORT, "reporter", reporter_agent.make_handler(r, ExplodingDrafter()), "rp-0", 10),
    ]

    def drain():
        for _ in range(20):
            if sum(w.poll_once() for w in workers) == 0:
                return

    class Env:
        pass
    env = Env()
    env.r, env.client, env.drain, env.pdf, env.workers = r, TestClient(gateway.app), drain, pdf, workers
    return env


def upload(env, data=None, name="bundle.pdf", reader="local"):
    return env.client.post("/documents", files={"file": (name, io.BytesIO(data or env.pdf), "application/pdf")},
                           data={"ai_reader": reader})


def test_document_audit_end_to_end(denv):
    res = upload(denv)
    assert res.status_code == 202
    job = res.json()["job_id"]
    denv.drain()
    state = denv.client.get(f"/audits/{job}").json()
    assert state["status"] == "completed", state
    summary = state["summary"]
    assert summary["kind"] == "document" and summary["assessment_year"] == "2023-24"
    assert "PRESUMPTIVE_44AD" in summary["flagged"] and "CASH_WITHDRAWAL_194N" in summary["flagged"]
    assert summary["drafter"] == "template drafter (deterministic)"  # confidential: never the cloud drafter
    report = denv.client.get(f"/audits/{job}/report").text
    assert "Income-tax Act, 1961 s.44AD" in report and "CGST Act, 2017 s.39" in report
    assert "- p.43: ITR gross receipts (44AD) = ₹24,20,000" in report  # page provenance for every figure
    assert "ABCDE1234F" not in report and "XXXXX1234F" in report
    result = denv.client.get(f"/audits/{job}/result").json()
    assert [t["agent"] for t in result["trace"]][:3] == ["gateway", "document", "regulation"]
    assert denv.r.get(blobs.blob_key(job)) is None  # the PDF is gone once processed
    queues = denv.client.get("/queues").json()
    assert config.STREAM_DOCUMENT in queues


def test_document_citations_are_only_the_named_sections(denv):
    job = upload(denv).json()["job_id"]
    denv.drain()
    result = denv.client.get(f"/audits/{job}/result").json()
    for f in result["findings"]:
        for c in f["citations"]:
            sec = c["citation"].rsplit("s.", 1)[1]
            assert f"section {sec}".lower() in f["reg_query"].lower() or f["check_id"] in ("NARRATIVE_COVERAGE",), (f["check_id"], c)


def test_upload_validation(denv, monkeypatch):
    assert upload(denv, b"GIF89a not a pdf").status_code == 415
    assert upload(denv, reader="gpt").status_code == 422
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert upload(denv, reader="claude").status_code == 400
    monkeypatch.setattr(config, "MAX_UPLOAD_MB", 0)
    assert upload(denv).status_code == 413
    assert denv.r.xlen(config.STREAM_DOCUMENT) == 0  # nothing queued or stored for rejected uploads
    assert not denv.r.keys("audit:doc:*")


def test_expired_upload_fails_cleanly(denv):
    job = upload(denv).json()["job_id"]
    denv.r.delete(blobs.blob_key(job))
    denv.workers[0].poll_once()
    state = denv.client.get(f"/audits/{job}").json()
    assert state["status"] == "failed" and "upload it again" in state["error"]
    assert denv.r.xlen(config.STREAM_DLQ) == 0


def test_unreadable_pdf_fails_without_retry(denv):
    job = upload(denv, b"%PDF-1.4 garbage").json()["job_id"]
    denv.workers[0].poll_once()
    state = denv.client.get(f"/audits/{job}").json()
    assert state["status"] == "failed" and "could not read the PDF" in state["error"]
    assert denv.r.get(blobs.blob_key(job)) is None


def test_keepalive_resets_idle_time_of_a_long_job(denv, monkeypatch):
    """A long OCR job must not be reclaimed by another replica while it is still progressing."""
    seen = []

    def slow_handler(msg):
        pending = denv.r.xpending_range(config.STREAM_DOCUMENT, "document", "-", "+", 1)[0]
        bus.keepalive()
        after = denv.r.xpending_range(config.STREAM_DOCUMENT, "document", "-", "+", 1)[0]
        seen.append((pending["times_delivered"], after["consumer"]))
    w = bus.Worker(denv.r, config.STREAM_DOCUMENT, "document", slow_handler, "doc-slow", 10)
    upload(denv)
    w.poll_once()
    assert seen == [(1, "doc-slow")]


def test_cloud_drafter_used_only_when_uploader_chose_claude(denv, monkeypatch, retrievers):
    msg = AuditMessage.new_document(DocumentContext(filename="x.pdf", sha256="0" * 64, size_bytes=1, allow_cloud=True))
    msg.findings = []

    class CloudDrafter(TemplateDrafter):
        name = "cloud"
    handler = reporter_agent.make_handler(denv.r, CloudDrafter())
    handler(msg)
    assert json.loads(denv.r.hget(bus.job_key(msg.job_id), "summary"))["drafter"] == "cloud"


# ------------------------------------------------------------------ local only: real private documents

PRIVATE = Path(__file__).resolve().parents[1] / "data" / "private"


@pytest.mark.skipif(not (PRIVATE / "expected.json").exists(), reason="no private documents on this machine")
def test_private_documents_match_expected_figures():
    """data/private/ is git-ignored: real bundles and their expected figures never leave this machine."""
    expected = json.loads((PRIVATE / "expected.json").read_text(encoding="utf-8"))
    for name, want in expected.items():
        pages = classify.classify(extract_pages((PRIVATE / name).read_bytes()))
        facts = parsers.parse_all(pages)
        for key, value in want.get("facts", {}).items():
            assert facts.value(key) == value, (name, key)
        results = {f.check_id: f.status.value for f in checks.run_all(facts)}
        for cid, status in want.get("checks", {}).items():
            assert results[cid] == status, (name, cid)
