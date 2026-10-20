"""Deterministic parsers for the documents found in Indian income-tax / GST evidence bundles.

Each parser reads the pages of one document type and emits Facts. A Fact always carries the
page it came from and the exact line quoted, so every number in the report can be traced back.
Identifiers (PAN, bank accounts) are masked before they become facts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from agents.document.pdftext import Page

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
NUM = r"-?[\d,]+(?:\.\d+)?"


def num(s: str) -> float:
    return float(s.replace(",", "").replace("₹", "").strip())


def as_int(v: float) -> int | float:
    return int(v) if float(v).is_integer() else round(v, 2)


def mask_pan(pan: str) -> str:
    return "XXXXX" + pan[-5:] if len(pan) == 10 else "XXXXX"


def mask_account(acct: str) -> str:
    return "XX" + acct[-4:]


def month_index(name: str) -> int:
    return MONTHS.index(name[:3].upper()) + 1


def fy_month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def fy_of(assessment_year: str | None) -> tuple[int, int] | None:
    """'2023-24' -> the financial year it assesses, as (start_year, end_year) = (2022, 2023)."""
    if not assessment_year:
        return None
    m = re.match(r"(\d{4})", assessment_year)
    return (int(m.group(1)) - 1, int(m.group(1))) if m else None


def in_fy(key: str, fy: tuple[int, int]) -> bool:
    y, m = int(key[:4]), int(key[5:7])
    return (y == fy[0] and m >= 4) or (y == fy[1] and m <= 3)


@dataclass
class Fact:
    key: str
    value: Any
    page: int
    quote: str
    printed: str | None = None
    extra: dict = field(default_factory=dict)


class Facts:
    def __init__(self) -> None:
        self.items: list[Fact] = []

    def add(self, key: str, value: Any, page: Page, quote: str, **extra) -> Fact:
        f = Fact(key, value, page.number, " ".join(quote.split())[:240], page.printed, extra)
        self.items.append(f)
        return f

    def all(self, key: str) -> list[Fact]:
        return [f for f in self.items if f.key == key]

    def first(self, key: str) -> Fact | None:
        return next((f for f in self.items if f.key == key), None)

    def value(self, key: str, default=None):
        f = self.first(key)
        return f.value if f else default

    def keys(self) -> set[str]:
        return {f.key for f in self.items}


def _lines(page: Page) -> list[str]:
    return [ln.strip() for ln in page.text.splitlines() if ln.strip()]


def _search(pattern: str, page: Page, facts: Facts, key: str, conv=num, flags=0) -> Fact | None:
    m = re.search(pattern, page.text, flags | re.MULTILINE)
    if not m:
        return None
    line = page.text[page.text.rfind("\n", 0, m.start()) + 1: page.text.find("\n", m.end()) if "\n" in page.text[m.end():] else None]
    return facts.add(key, conv(m.group(1)), page, line or m.group(0))


# ---------------------------------------------------------------- ITR acknowledgement / form

def parse_itr_ack(page: Page, facts: Facts) -> None:
    t = page.text
    m = re.search(r"Assessment\s*Year\s*(\d{4}-\d{2})", t)
    if m:
        facts.add("itr.assessment_year", m.group(1), page, m.group(0))
    m = re.search(r"Form Number\s*(ITR-\d)", t)
    if m:
        facts.add("itr.form", m.group(1), page, m.group(0))
    m = re.search(r"Filed u/s\s*(\d+\(\d+\))\s*-?\s*([^\n]*?)(?:e-Filing|\n)", t)
    if m:
        facts.add("itr.filed_section", m.group(1), page, m.group(0), description=m.group(2).strip())
    m = re.search(r"Date of filing\s*:\s*(\d{1,2}-[A-Za-z]{3}-\d{4})", t)
    if m:
        facts.add("itr.filing_date", datetime.strptime(m.group(1), "%d-%b-%Y").date().isoformat(), page, m.group(0))
    m = re.search(r"\bPAN\s+([A-Z]{5}\d{4}[A-Z])\b", t)
    if m:
        facts.add("itr.pan_masked", mask_pan(m.group(1)), page, "PAN " + mask_pan(m.group(1)))
    m = re.search(r"^Name\s+([A-Z][A-Z .]+)$", t, re.MULTILINE)
    if m:
        facts.add("itr.name", m.group(1).strip().title(), page, "Name (ITR acknowledgement)")
    _search(rf"^Total Income\s+2\s+({NUM})", page, facts, "ack.total_income")
    _search(rf"^Interest and Fee Payable\s+6\s+({NUM})", page, facts, "ack.interest_fee_payable")
    _search(rf"^Taxes Paid\s+8\s+({NUM})", page, facts, "ack.taxes_paid")
    m = re.search(rf"Tax Payable /\(-\) Refundable \(7-8\)\s+9\s+\((\+|-)\)\s*({NUM})", t)
    if m:
        v = num(m.group(2))
        facts.add("ack.refund" if m.group(1) == "-" else "ack.tax_payable", v, page, m.group(0))


ITR_PATTERNS = [
    ("itr.gross_receipts_44ad", rf"Gross Turnover or Gross Receipts \(ia\+ib\)\s+61i\s+({NUM})"),
    ("itr.receipts_digital_44ad", rf"^ia\s+({NUM})$"),
    ("itr.receipts_other_44ad", rf"Any other mode\s+ib\s+({NUM})"),
    ("itr.presumptive_income_44ad", rf"Presumptive income under section 44AD \(iia \+ iib\)\s+61ii\s+({NUM})"),
    ("itr.gross_receipts_44ada", rf"^i Gross Receipts\s+62i\s+({NUM})"),
    ("itr.other_sources_income", rf"Total \(5a \+ 5b \+ 5c\)\(enter nil if loss\)\s+5d\s+({NUM})"),
    ("itr.gross_total_income", rf"^10 Gross Total income .*?\s10\s+({NUM})$"),
    ("itr.chapter_via", rf"^c Total \(12a \+12b\).*?12c\s+({NUM})$"),
    ("itr.total_income", rf"^14 Total income \(10 - 12c-13\)\s+14\s+({NUM})"),
    ("itr.tax_normal_rates", rf"Tax at normal rates on 17 of Part B-TI\s+2a\s+({NUM})"),
    ("itr.rebate_87a", rf"Rebate under section 87A\s+2e\s+({NUM})"),
    ("itr.tds_claimed_total", rf"TDS claimed in own hand\(total of column 9\)\s+({NUM})"),
    ("itr.new_regime", r"(?:opting for new tax regime|Opting for new tax regime u/s 115BAC)\s*\??\s*(Yes|No)\b"),
]
TDS_ROW = re.compile(r"^\d+\s+Self\s+([A-Z]{4}\d{5}[A-Z])\s+((?:[\d,]+\s+)+)(OS|BP|CG|HP|EI|SA)\b")


def parse_itr(page: Page, facts: Facts) -> None:
    for key, pattern in ITR_PATTERNS:
        if facts.first(key):
            continue
        conv = (lambda s: s) if key == "itr.new_regime" else num
        _search(pattern, page, facts, key, conv=conv)
    if "SCHEDULE TDS2" in page.text or "TDS claimed in own hand" in page.text:
        for line in _lines(page):
            m = TDS_ROW.match(line)
            if m:
                amounts = [num(x) for x in m.group(2).split()]
                facts.add("itr.tds_row", {"tan": m.group(1), "gross": as_int(amounts[-1]),
                                          "tds": as_int(max(amounts[:-1], default=0)), "head": m.group(3)},
                          page, line)


def parse_computation(page: Page, facts: Facts) -> None:
    # The computation prints the amount before its label: "1,000Fee u/s 234F".
    _search(rf"({NUM})\s*Fee u/s 234F", page, facts, "comp.fee_234f")
    m = re.search(r"Date of Birth\s*\n?.*?(\d{1,2}-[A-Za-z]{3}-\d{4})", page.text, re.DOTALL)
    if m and not facts.first("taxpayer.birth_year"):
        facts.add("taxpayer.birth_year", int(m.group(1)[-4:]), page, "date of birth (year only)")


# ---------------------------------------------------------------- AIS / TIS

AIS_HEADER = re.compile(rf"^(\d+)\s+((?:TDS|SFT|EXC|TCS)-[\w()]+)\s+(.+?)\s+(\d+)\s+({NUM})$")
AIS_ROW = re.compile(rf"^(\d+)\s+Q[1-4]\([A-Za-z]{{3}}-[A-Za-z]{{3}}\)\s+(\d{{2}}/\d{{2}}/\d{{4}})\s+({NUM})\s+({NUM})\s+({NUM})\s+(Active|Inactive)$")
AIS_ROW_PARTIAL = re.compile(r"^(\d+)\s+Q[1-4]\([A-Za-z]{3}-[A-Za-z]{3}\)\s+(\d{2}/\d{2}/\d{4})\s*$")


def parse_ais(pages: list[Page], facts: Facts) -> None:
    """Detail rows follow their information header, but a long section (e.g. hundreds of cash
    withdrawals) continues on later pages after other sections were printed. Rows are numbered
    from 1 within a section, so a row joins the section whose last serial it continues."""
    current: Fact | None = None
    pending: str | None = None
    sections: list[Fact] = []

    def owner(serial: int) -> Fact | None:
        candidates = [f for f in ([current] if current else []) + sections[::-1] if len(f.value["rows"]) == serial - 1]
        # Several sections can have the same number of rows so far; prefer one still expecting rows.
        expecting = [f for f in candidates
                     if sum(r["status"] == "Active" for r in f.value["rows"]) < f.value["count"]]
        return (expecting or candidates or [None])[0]

    for page in pages:
        if not facts.first("taxpayer.birth_year"):
            m = re.search(r"Date of Birth\s*\n\s*\d{2}/\d{2}/(\d{4})", page.text)
            if m:
                facts.add("taxpayer.birth_year", int(m.group(1)), page, "date of birth (year only)")
        m = re.search(r"Assessment Year\s*\n?\s*(\d{4}-\d{2})", page.text)
        if m and not facts.first("ais.assessment_year"):
            facts.add("ais.assessment_year", m.group(1), page, m.group(0))
        for line in _lines(page):
            if pending:  # a detail row split across two lines/pages
                line, pending = pending + " " + line, None
            h = AIS_HEADER.match(line)
            if h:
                current = facts.add("ais.info", {"code": h.group(2), "description": h.group(3),
                                                 "count": int(h.group(4)), "amount": as_int(num(h.group(5))),
                                                 "rows": []}, page, line)
                sections.append(current)
                continue
            r = AIS_ROW.match(line)
            target = owner(int(r.group(1))) if r else None
            if target is not None:
                d = datetime.strptime(r.group(2), "%d/%m/%Y").date()
                target.value["rows"].append({"date": d.isoformat(), "amount": as_int(num(r.group(3))),
                                              "tds": as_int(num(r.group(4))), "status": r.group(6),
                                              "page": page.number})
                continue
            if AIS_ROW_PARTIAL.match(line):
                pending = line


TIS_ROW = re.compile(rf"^(\d)\s+([A-Za-z][A-Za-z ]+?)\s+({NUM})\s+({NUM})$")


def parse_tis(pages: list[Page], facts: Facts) -> None:
    seen = set()
    for page in pages:
        for line in _lines(page):
            m = TIS_ROW.match(line)
            if m and m.group(2) not in seen:
                seen.add(m.group(2))
                facts.add("tis.category", {"category": m.group(2), "processed": as_int(num(m.group(3))),
                                           "accepted": as_int(num(m.group(4)))}, page, line)


# ---------------------------------------------------------------- GST returns and invoices

def _period(year_text: str, month_name: str) -> str:
    """GST 'Financial year 2022-23, Tax period April' -> '2022-04'; Jan-Mar fall in the later year."""
    start = int(year_text[:4])
    m = month_index(month_name)
    return fy_month_key(start if m >= 4 else start + 1, m)


def parse_gstr1(pages: list[Page], facts: Facts) -> None:
    for page in pages:
        m = re.search(r"Financial year\s+(\d{4}-\d{2})\s*\n\s*Tax period\s+([A-Za-z]+)", page.text)
        if not m:
            continue
        period = _period(m.group(1), m.group(2))
        b2b = re.search(rf"4A - Taxable outward supplies.*?\n\s*Total\s+(\d+)\s+Invoice\s+({NUM})\s+({NUM})\s+({NUM})\s+({NUM})",
                        page.text, re.DOTALL)
        if b2b:
            facts.add("gstr1.b2b", {"period": period, "records": int(b2b.group(1)), "taxable": num(b2b.group(2)),
                                    "tax": round(num(b2b.group(3)) + num(b2b.group(4)) + num(b2b.group(5)), 2)},
                      page, f"GSTR-1 {m.group(2)} {m.group(1)}: 4A B2B total {b2b.group(2)}")


def parse_gstr3b(pages: list[Page], facts: Facts) -> None:
    for page in pages:
        m = re.search(r"Year\s+(\d{4}-\d{2})\s*\n\s*Period\s+([A-Za-z]+)", page.text)
        if not m:
            continue
        period = _period(m.group(1), m.group(2))
        v = re.search(rf"exempted\)\s*\n\s*({NUM})\s+({NUM})\s+({NUM})\s+({NUM})", page.text)
        if v:
            facts.add("gstr3b.outward", {"period": period, "taxable": num(v.group(1)),
                                         "tax": round(num(v.group(2)) + num(v.group(3)) + num(v.group(4)), 2)},
                      page, f"GSTR-3B {m.group(2)} {m.group(1)}: 3.1(a) taxable value {v.group(1)}")


INVOICE_LINE = re.compile(rf"^\d+\s+(.+?)\s+({'|'.join(MONTHS)})\s+({NUM})$")


def parse_invoice(page: Page, facts: Facts) -> None:
    t = page.text
    ref = re.search(r"Invoice Ref No\s*:\s*(\S+)", t)
    when = re.search(r"\b(\d{2}-[A-Za-z]{3}-\d{4})\b", t)
    total = re.search(rf"TAXABLE AMOUNT Rs\.?\s*({NUM})", t)
    if not (when and total):
        return
    inv_date = datetime.strptime(when.group(1), "%d-%b-%Y").date()
    lines = []
    for line in _lines(page):
        m = INVOICE_LINE.match(line)
        if m:
            mon = month_index(m.group(2))
            # Services are billed after the month they were rendered in: Dec billed in Jan is last year's Dec.
            year = inv_date.year if mon <= inv_date.month else inv_date.year - 1
            lines.append({"description": m.group(1), "service_month": fy_month_key(year, mon), "taxable": num(m.group(3))})
    net = re.search(rf"NET PAYABLE AMOUNT Rs\.?\s*({NUM})", t)
    facts.add("invoice", {"ref": ref.group(1) if ref else None, "date": inv_date.isoformat(),
                          "taxable": num(total.group(1)), "net_payable": num(net.group(1)) if net else None,
                          "lines": lines}, page, f"Tax invoice {ref.group(1) if ref else ''} dated {when.group(1)}: "
                                                 f"taxable amount Rs {total.group(1)}")


# ---------------------------------------------------------------- bank statements

# The value date is sometimes glued to the reference number, and the text layer can cut the last
# decimals of a balance ("196608."), so the debit/credit side is inferred with a one-rupee tolerance.
BANK_TXN = re.compile(r"^(\d{2}/\d{2}/\d{2})\s+(.*?)\s*(\d{2}/\d{2}/\d{2})\s+(-?[\d,]+\.?\d*)\s+(-?[\d,]+\.?\d*)$")
BALANCE_TOLERANCE = 1.0


def parse_bank_statement(pages: list[Page], facts: Facts) -> None:
    text = "\n".join(p.text for p in pages)
    bank = re.search(r"^([A-Z][A-Z ]+BANK)", text, re.MULTILINE)
    acct = re.search(r"Account No\s*:\s*(\d+)", text)
    summary = re.search(rf"Opening Balance\s+Debits\s+Credits\s+Closing Bal\s*\n\s*({NUM})\s+({NUM})\s+({NUM})\s+({NUM})", text)
    period = re.search(r"Statement From\s*:\s*(\d{2}/\d{2}/\d{4})\s+To\s*:\s*(\d{2}/\d{2}/\d{4})", text)
    label = {"bank": bank.group(1).strip().title() if bank else "Bank", "account": mask_account(acct.group(1)) if acct else "?"}
    opening = num(summary.group(1)) if summary else None
    balance = opening
    txns = []
    for page in pages:
        for line in _lines(page):
            m = BANK_TXN.match(line)
            if not m:
                continue
            amount, closing = num(m.group(4)), num(m.group(5))
            if balance is None:
                direction = "unknown"
            elif abs(balance + amount - closing) < BALANCE_TOLERANCE:
                direction = "credit"
            elif abs(balance - amount - closing) < BALANCE_TOLERANCE:
                direction = "debit"
            else:
                direction = "unknown"
            balance = closing
            txns.append({"date": datetime.strptime(m.group(1), "%d/%m/%y").date().isoformat(), "narration": m.group(2),
                         "amount": amount, "direction": direction, "balance": closing, "page": page.number})
    page0 = pages[0]
    if summary:
        last = next(p for p in reversed(pages) if "STATEMENT SUMMARY" in p.text or "Opening Balance" in p.text)
        facts.add("bank.summary", {**label, "opening": num(summary.group(1)), "debits": num(summary.group(2)),
                                   "credits": num(summary.group(3)), "closing": num(summary.group(4)),
                                   "from": period.group(1) if period else None, "to": period.group(2) if period else None},
                  last, f"Statement summary: opening {summary.group(1)}, debits {summary.group(2)}, "
                        f"credits {summary.group(3)}, closing {summary.group(4)}")
    facts.add("bank.transactions", {**label, "rows": txns}, page0, f"{len(txns)} transactions parsed from {label['bank']} {label['account']}")


# ---------------------------------------------------------------- §194N certificates, assessment orders

CERT = re.compile(r"during the month of\s+([A-Za-z]+)\s+(\d{4}),\s*total sum of Rs\.?\s*([\d,]+(?:\.\d+)?)"
                  r".*?withdrawn from the account number\s+(\d+)", re.DOTALL | re.IGNORECASE)


def parse_cash_certificate(page: Page, facts: Facts) -> None:
    flat = " ".join(page.text.split())
    for m in CERT.finditer(flat):
        mon = month_index(m.group(1))
        dated = re.search(r"Date\s*:\s*(\d{2}-[A-Za-z]+-\d{4})", flat)
        facts.add("cert.194n", {"month": fy_month_key(int(m.group(2)), mon), "amount": as_int(num(m.group(3))),
                                "account": mask_account(m.group(4)),
                                "letter_date": dated.group(1) if dated else None},
                  page, f"Certificate: during the month of {m.group(1)} {m.group(2)}, Rs {m.group(3)} withdrawn "
                        f"from account {mask_account(m.group(4))} for ATM replenishment")
    if re.search(r"Exclusive a/c for White Label ATM", flat):
        fy = re.search(r"For FY[’']?\s*(\d{4}-\d{2})", flat)
        facts.add("cert.194n_annual", {"fy": fy.group(1) if fy else None}, page,
                  f"Annual exclusive-account declaration{(' for FY ' + fy.group(1)) if fy else ''}")


def parse_assessment_order(pages: list[Page], facts: Facts) -> None:
    for page in pages:
        m = re.search(r"Assessment Year\s+(\d{4}-\d{2})", page.text)
        if m and not facts.first("order.assessment_year"):
            facts.add("order.assessment_year", m.group(1), page, m.group(0))
        _search(rf"Returned Income\s+Rs\.?\s*({NUM})", page, facts, "order.returned_income")
        m = re.search(r"Order passed under section\s+([\d()A-Za-z ]+?)\s+(?:read with|r\.w\.s)", page.text)
        if m and not facts.first("order.section"):
            facts.add("order.section", m.group(1).strip(), page, m.group(0))


# ---------------------------------------------------------------- driver

def parse_all(pages: Iterable[Page]) -> Facts:
    pages = list(pages)
    facts = Facts()
    by_type: dict[str, list[Page]] = {}
    for p in pages:
        by_type.setdefault(p.doc_type, []).append(p)
    for p in by_type.get("itr_ack", []):
        parse_itr_ack(p, facts)
    for p in by_type.get("itr", []):
        parse_itr(p, facts)
    for p in by_type.get("computation", []):
        parse_computation(p, facts)
    parse_ais(by_type.get("ais", []), facts)
    parse_tis(by_type.get("tis", []), facts)
    parse_gstr1(by_type.get("gstr1", []), facts)
    parse_gstr3b(by_type.get("gstr3b", []), facts)
    for p in by_type.get("invoice", []):
        parse_invoice(p, facts)
    if by_type.get("bank_statement"):
        parse_bank_statement(by_type["bank_statement"], facts)
    for p in by_type.get("cash_withdrawal_certificate", []):
        parse_cash_certificate(p, facts)
    parse_assessment_order(by_type.get("assessment_order", []), facts)
    from agents.document.case_parsers import parse_case  # case papers build on these facts
    parse_case(by_type, facts)
    return facts
