"""Label each page with the kind of document it belongs to, from its content.

Annexure indexes in submission bundles are often wrong or stale, so classification relies on
signatures printed on the pages themselves. Continuation pages (a GSTR-1 table running onto the
next page, AIS detail rows) carry weaker markers and inherit the type of the page before them.
"""
from __future__ import annotations

import re

from agents.document.pdftext import Page

# (type, strong signatures: any one starts a section)
STRONG = [
    # Case papers: the department's notice / letter, and the portal's acknowledgement of a response.
    ("notice", [r"(?i)you\s*are\s*(?:hereby\s*)?requested\s*to\s*(?:submit|furnish|produce)", r"(?i)show\s*cause\s*notice"]),
    ("proceeding_ack", [r"e-Proceedings Response Acknowledgement"]),
    ("annexure_index", [r"(?i)Documents submitted as an? Additional Evidence", r"(?im)^\s*S\.?\s*No\.?\s+Documents?\b.*Annexure"]),
    ("form16a", [r"(?i)FORM\s*NO\.?\s*16A"]),
    ("fee_receipt", [r"Fees? Receipt\b", r"Tui?tion Fee"]),  # case-sensitive: prose says "fees receipts"
    ("itr_ack", [r"INDIAN INCOME TAX RETURN ACKNOWLEDGEMENT"]),
    ("tis", [r"Taxpayer Information Summary \(TIS\)"]),
    ("ais", [r"Annual Information Statement \(AIS\)"]),
    ("gstr1", [r"FORM GSTR-1\b"]),
    ("gstr3b", [r"Form GSTR-3B\b"]),
    ("invoice", [r"TAX INVOICE"]),
    ("cash_withdrawal_certificate", [r"194N", r"withdrawn from the account number|Exclusive a/c for White Label ATM"]),
    ("bank_statement", [r"Statement of accounts|STATEMENT SUMMARY|Withdrawal Amt\.?\s+Deposit Amt"]),
    ("assessment_order", [r"^\s*ASSESSMENT ORDER\s*$|ITBA/AST/"]),
    ("computation", [r"Statement of Income"]),
    ("itr", [r"FORM\s*\n?\s*ITR-?\d|PART B - TI\b|PART B - TTI|SCHEDULE TDS\d|Acknowledgement Number\s*:\s*\d+\s+Date of Filing"]),
    ("agreement", [r"eStamp Certificate|AGREEMENT\b|Agreement is made"]),
]
# Weak markers: only continue a section that is already open.
CONTINUATION = {
    "ais": [r"Download ID\s*:", r"\bQ[1-4]\((?:Apr|Jul|Oct|Jan)-"],
    "tis": [r"INFORMATION CATEGORY"],
    "gstr1": [r"No\. of records", r"Amendment to taxable outward supplies"],
    "gstr3b": [r"Values of exempt, nil-rated and non-GST inward supplies", r"Payment of tax"],
    "bank_statement": [r"^\d{2}/\d{2}/\d{2}\s"],
    "itr": [r"\bSchedule\b|\bSCHEDULE\b"],
    "assessment_order": [r"Page \d+ of \d+"],
    "agreement": [r"Agreement|agreement|CHANNEL ?PARTNER"],
    "form16a": [r"Certificate\s*Number\s*:|TAN\s*of\s*Deductor"],
}
# The running header of the taxpayer's own written submission; its pages often quote other documents
# (agreement clauses, AIS tables), which must not reclassify them.
SUBMISSION_HEADER = re.compile(r"(?i)remand\s*proceedings|written\s*submissions?\b|grounds\s*of\s*appeal|statement\s*of\s*facts")
SUBMISSION = re.compile(r"\b(?:assessee|Assessee|Respected Sir|respectfully submit|Remand|Annexure)\b")


def _matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.MULTILINE) is not None


def classify_page(text: str, previous: str = "other") -> str:
    head = "\n".join(text.splitlines()[:4])
    if SUBMISSION_HEADER.search(head) and not re.search(r"Documents submitted as an? Additional Evidence", text):
        return "submission"
    for doc_type, patterns in STRONG:
        if all(_matches(p, text) for p in patterns) if doc_type == "cash_withdrawal_certificate" \
                else any(_matches(p, text) for p in patterns):
            return doc_type
    if previous in CONTINUATION and any(_matches(p, text) for p in CONTINUATION[previous]):
        return previous
    if len(SUBMISSION.findall(text)) >= 2 and len(text) > 300:
        return "submission"
    return "other"


def classify(pages: list[Page]) -> list[Page]:
    previous = "other"
    for p in pages:
        p.doc_type = classify_page(p.text, previous) if p.method != "empty" else "empty"
        if p.doc_type != "empty":
            previous = p.doc_type
    return pages


def page_type_counts(pages: list[Page]) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in pages:
        out[p.doc_type] = out.get(p.doc_type, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
