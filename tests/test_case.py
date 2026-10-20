"""Case-aware review: proceeding and notice, the order under dispute and its additions, the officer's
figures, the taxpayer's claims, cross-year consistency, deduction evidence, bank narration classes,
per-account certificate coverage, materiality, citation validation and the evaluation harness.
All on synthetic case papers (tests/doc_factories.py)."""
import json
import re
from pathlib import Path

from agents.document import checks, classify, parsers
from agents.document.agent import analyse
from agents.document.pdftext import Page
from agents.regulation.retriever import IN_INDEX_DIR, Retriever
from common.schemas import AuditMessage, DocumentContext, Status
from tests import doc_factories as F


def review(pages):
    pages = classify.classify(pages)
    facts = parsers.parse_all(pages)
    return pages, facts, {f.check_id: f for f in analyse(pages, facts)}


def test_case_papers_are_classified():
    counts = classify.page_type_counts(classify.classify(F.case_bundle()))
    assert counts["notice"] == 1 and counts["annexure_index"] == 1 and counts["fee_receipt"] == 2
    assert counts["assessment_order"] == 2 and counts["submission"] == 2


def test_submission_pages_quoting_an_agreement_stay_submission():
    """Regression: submission pages that reproduce agreement clauses were classified as agreements."""
    text = "SYNTHETIC TRADER\nA.Y.2023-24\nRemand Proceedings\neStamp Certificate No: IN-KA000\nAgreement clause 5 ..."
    assert classify.classify_page(text) == "submission"


def test_notice_requests_survive_ocr_without_spaces():
    page = Page(1, "Remand Report AY 2023-24. you are requested to submit all the documents listed as additional"
                   " evidences i.e.Sl.No.from1to12forverification.Youarealsorequested to furnish thebriefreasons"
                   " for acceptance.Further,youneedto furnish the ledger account extract of all the persons.", "ocr")
    facts = parsers.Facts()
    from agents.document.case_parsers import parse_notice
    parse_notice(page, facts)
    requests = facts.value("case.notice")["requests"]
    assert len(requests) == 3 and "ledger" in requests[2] and "Sl.No" in requests[0]


def test_remand_without_order_under_dispute_says_so():
    _, _, f = review(F.case_bundle())
    ctx = f["CASE_CONTEXT"]
    assert ctx.status == Status.WARN and "remand" in ctx.detail and "not in the bundle" in ctx.detail
    assert ctx.values["other_year_orders"] == ["2024-25"]


def test_notice_items_not_furnished_fail():
    _, _, f = review(F.case_bundle())
    notice = f["NOTICE_COMPLIANCE"]
    assert notice.status == Status.FAIL and notice.values["missing"] == ["ledger account extracts"]
    _, _, f = review(F.case_bundle(notice=[F.notice_page(asks_ledger=False)]))
    assert f["NOTICE_COMPLIANCE"].status == Status.PASS


def test_order_additions_and_officer_figures():
    _, facts, f = review(F.case_bundle(orders=F.order_pages()))
    order = facts.first("order").value
    assert order["additions"][0]["amount"] == 1500000 and order["additions"][0]["section"] == "69A"
    assert order["assessed_income"] == 1920000
    ctx, figures = f["CASE_CONTEXT"], f["AO_FIGURE_RECONCILIATION"]
    assert ctx.severity.value == "high" and ctx.values["additions_total"] == 1500000
    assert {m["matches"] for m in figures.values["matched"]} == {"credits in Synthetic Bank XX1234",
                                                                "gross receipts in the return"}
    assert "double counts" in figures.detail and figures.values["bearing"] == "supports the taxpayer"


def test_officer_figure_not_in_any_document_is_reported():
    pages = F.order_pages()
    pages[0] = pages[0].replace("total credits of Rs. 4,99,000", "total credits of Rs. 9,32,000")
    _, _, f = review(F.case_bundle(orders=pages))
    assert [u["amount"] for u in f["AO_FIGURE_RECONCILIATION"].values["not_traceable"]] == [932000]


def test_claims_are_supported_asserted_or_contradicted():
    _, _, f = review(F.case_bundle())
    claims = {c["claim"].split(" (")[0]: c for c in f["SUBMISSION_CLAIMS"].values["claims"]}
    medical = next(c for k, c in claims.items() if k.startswith("A medical exigency"))
    assert medical["status"] == "asserted only" and "medical" in medical["quote"]
    assert next(c for k, c in claims.items() if k.startswith("The identical issue"))["status"] == "supported"
    exclusive = next(c for k, c in claims.items() if k.startswith("The bank accounts"))
    assert exclusive["status"] == "asserted only" and "XX3333" in exclusive["why"]
    assert next(c for k, c in claims.items() if k.startswith("The receipts are commission"))["status"] == "contradicted"
    assert next(c for k, c in claims.items() if k.startswith("Income was declared"))["status"] == "supported"


def test_deduction_evidence_by_payment_date():
    _, _, f = review(F.case_bundle())
    d = f["DEDUCTION_EVIDENCE"]
    assert d.values["evidence_in_year"] == 50000 and d.values["unsupported"] == 30000
    assert d.values["receipts_outside_year"][0]["dates"] == ["2024-06-20"]
    receipts = [F.fee_receipt_page(50000, ["15-06-2022"]), F.fee_receipt_page(30000, ["17-06-2022", "14-06-2024"])]
    _, _, f = review(F.case_bundle(receipts=receipts))
    assert f["DEDUCTION_EVIDENCE"].severity.value == "low"
    assert "dates both inside and outside" in f["DEDUCTION_EVIDENCE"].detail


def test_evidence_dated_after_the_year():
    _, _, f = review(F.case_bundle())
    rel = f["EVIDENCE_RELEVANCE"]
    assert rel.status == Status.WARN and rel.values["dated_after_year_end"][0]["date"] == "2023-10-01"


def test_cross_year_contrast_on_other_sources():
    pages = F.order_pages(ay="2024-25", additions=())
    pages[0] += "\nThe assessee has shown income from business u/s 44AD and income from other sources."
    _, _, f = review(F.case_bundle(orders=pages))
    y = f["YEAR_CONSISTENCY"]
    assert y.status == Status.WARN and "other sources" in y.detail and "does not bind" in y.detail


def test_bank_credits_classified_before_s68():
    """Regression: a provisional credit later reversed, failed-IMPS returns and self transfers were
    counted as third-party credits."""
    p1, p2 = F.bank_pages()
    p1 = p1.replace("05/04/22 POS 400000XXXXXX1111 FUEL STATION 0000209502796425 05/04/22 1000 9000",
                    "05/04/22 POS 400000XXXXXX1111 FUEL STATION 0000209502796425 05/04/22 1000 9000\n"
                    "06/04/22 CRM 25640964 PROV CR NB SYNTHETIC TRADER 000000000000000 06/04/22 90000 99000\n"
                    "07/04/22 TEMP CR REVERSAL NB CRM 25640964 000000000000000 07/04/22 90000 9000\n"
                    "08/04/22 IMPS-212007314084-SYNTHETIC KIN-SBIN-XXXX6746-LOAN0000212007314084 08/04/22 60000 69000\n"
                    "09/04/22 IMPS-212007314085-SYNTHETIC TRADER-ICIC-XXXX1111-SELF0000212007314085 09/04/22 70000 139000\n"
                    "10/04/22 NEFT DR-ICIC0000001-SYNTHETIC TRADER-SELF 10/04/22 130000 9000")
    p2 = p2.replace("10000 101059 499000.5 407941.5", "10000 321059 719000.5 407941.5")
    _, _, f = review(F.case_bundle(bank=[p1, p2]))
    bank = f["BANK_THIRD_PARTY_CREDITS"]
    classes = bank.values["by_class"]
    assert classes["reversal / provisional"]["total"] == 90000
    assert classes["self transfer"]["total"] == 70000
    assert classes["related party"]["total"] == 60000
    assert classes["business"]["total"] == 300000
    assert "reversals, provisional credits or self transfers" in bank.detail


def test_certificate_gaps_per_account():
    certs = [F.certificate_page("May", 2022, 2000000, "1111222233334444"), F.certificate_page("Jun", 2022, 3000000, "1111222233334444"),
             F.certificate_page("Jun", 2022, 2000000, "9999888877776666"), F.certificate_page("May", 2022, 1000000, "5555666677778888"),
             F.certificate_page("Jul", 2022, 2500000, "5555666677778888")]
    _, _, f = review(F.bundle(certificates=certs))
    gaps = f["CASH_WITHDRAWAL_194N"].values["account_gaps"]
    assert gaps == {"XX4444": ["2022-07"], "XX6666": ["2022-07"], "XX8888": ["2022-06"]}


def test_materiality_drives_severity_and_bearing():
    _, _, f = review(F.case_bundle())
    cash = f["CASH_WITHDRAWAL_194N"]
    assert cash.values["amount_at_stake"] == 6500000 and cash.values["bearing"] == "weakens the taxpayer's case"
    assert f["TURNOVER_AIS_VS_ITR"].values["bearing"] == "supports the taxpayer"
    assert f["OTHER_INCOME_OMITTED"].severity.value == "low"  # ₹1,500 at stake


def test_report_leads_with_the_case_and_amounts():
    from agents.reporter.drafter import TemplateDrafter
    _, _, f = review(F.case_bundle())
    msg = AuditMessage.new_document(DocumentContext(filename="x.pdf", sha256="0" * 64, size_bytes=1))
    msg.findings = list(f.values())
    report = TemplateDrafter().draft(msg)
    assert report.index("## Case summary") < report.index("## Executive summary")
    assert "Items the notice called for were not furnished" in report
    assert "Significant weaknesses" in report and "Satisfactory" not in report


def test_pinned_citations_quote_their_own_section():
    """Regression: the s.80TTA citation quoted a s.44AE paragraph from the same memorandum page."""
    r = Retriever(IN_INDEX_DIR, mode="bm25")
    queries = ["interest income savings bank deposit section 80TTA", "section 194N cash withdrawal",
               "section 44AD presumptive taxation", "section 234F fee", "section 80C deduction tuition fees"]
    for q in queries:
        for h in r.search(q, k=3):
            if h.pinned:
                number = h.citation.rsplit("s.", 1)[1]
                assert re.search(rf"(?<![\dA-Z]){re.escape(number)}(?![\dA-Z])", h.excerpt), (q, h.citation, h.excerpt[:120])


def test_evaluation_harness_on_the_synthetic_case():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from eval_documents import score
    case = json.loads((Path(__file__).parent / "eval" / "synthetic.json").read_text(encoding="utf-8"))
    result = score(case)
    assert result["recall"] == 1.0, result["missed"]
    assert result["precision"] == 1.0, result["false_flags"]
    assert result["figure_accuracy"] == 1.0, result["wrong_figures"]
