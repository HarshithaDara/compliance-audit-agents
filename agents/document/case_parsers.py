"""Parsers for the case papers in a bundle: the department's notice or letter, the portal's
acknowledgement, the taxpayer's evidence index, assessment orders (with their additions),
deduction evidence (fee receipts) and Form 16A.

These turn a stack of returns and statements into a case: which proceeding this is, what the
officer asked for, which order (if any) is being contested and what it added to income.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from agents.document.parsers import NUM, Facts, Page, num

PROCEEDINGS = [  # (kind, pattern) - first match wins
    ("remand", r"(?i)remand\s*report|remand\s*proceedings"),
    ("appeal", r"(?i)CIT\s*\(\s*A\s*\)|grounds\s*of\s*appeal|appellate"),
    ("show_cause", r"(?i)show\s*cause"),
    ("reassessment", r"(?i)section\s*148A?\b|u/s\.?\s*148A?\b|reopen"),
    ("scrutiny", r"(?i)u/s\.?\s*142\s*\(1\)|u/s\.?\s*143\s*\(2\)|scrutiny"),
]
# OCR of department letters often loses spaces ("verification.Youarealsorequested"), so requests are
# found by their lead-in phrase and end at the next lead-in or at a full stop followed by a capital.
REQUEST_LEAD = re.compile(r"(?i)you\s*are\s*(?:also\s*|hereby\s*)?requested\s*to|you\s*need\s*to|please\s*(?=submit|furnish|produce)")
SENTENCE_END = re.compile(r"(?<!i\.e)(?<!e\.g)(?<!\bSl)(?<!\bNo)(?<!\bviz)(?<!\bM/s)\.(?=\s*[A-Z][a-z]|\s*$)")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _date(s: str) -> date | None:
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%d-%b-%Y", "%d-%b-%y", "%d-%B-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_notice(page: Page, facts: Facts) -> None:
    flat = _flat(page.text)
    kind = next((k for k, p in PROCEEDINGS if re.search(p, flat)), "other")
    ay = re.search(r"(?:Assessment\s*Year|A\.?\s*Y\.?)\s*:?\s*(\d{4}\s*-\s*\d{2})", flat)
    dated = re.search(r"Dated\s*:?\s*(\d{2}[/.-]\d{2}[/.-]\d{4})", flat) or re.search(r"\b(\d{2}/\d{2}/\d{4})\b", flat)
    requests = []
    leads = list(REQUEST_LEAD.finditer(flat))
    for i, m in enumerate(leads):
        chunk = flat[m.end(): leads[i + 1].start() if i + 1 < len(leads) else len(flat)]
        end = SENTENCE_END.search(chunk)
        item = re.sub(r"\s*(?:Further|Also)\s*,?\s*$", "", chunk[:end.start()] if end else chunk).strip(" ,;:")
        if 10 <= len(item) <= 400:
            requests.append(item)
    facts.add("case.notice", {"proceeding": kind, "assessment_year": ay.group(1).replace(" ", "") if ay else None,
                              "date": dated.group(1) if dated else None, "requests": requests},
              page, (requests[0] if requests else flat[:200]))


def parse_proceeding_ack(page: Page, facts: Facts) -> None:
    flat = _flat(page.text)
    ay = re.search(r"Assessment Year\s*(\d{4}-\d{2})", flat)
    name = re.search(r"Proceeding Name\s*(.+?)\s*Notice", flat)
    facts.add("case.response_ack", {"assessment_year": ay.group(1) if ay else None,
                                    "proceeding_name": name.group(1).strip() if name else None},
              page, flat[:160])


ROW_END = re.compile(r"\s(\d{1,2})\s+(\d{1,3})(?:\s*[–-]\s*(\d{1,3}))?\s*$")
ROW_START = re.compile(r"^(\d{1,2})\s+(\S.*)$")
DATED = re.compile(r"(?i)dated\s*(\d{2}[./-]\d{2}[./-]\d{4})")


def parse_annexure_index(pages: list[Page], facts: Facts) -> None:
    """The taxpayer's list of evidence, from the version of the index that carries page ranges."""
    for page in pages:
        if not re.search(r"(?i)Page\s*no", page.text):
            continue
        rows, current = [], None
        for line in (ln.strip() for ln in page.text.splitlines() if ln.strip()):
            start = ROW_START.match(line)
            if current is None and start and not ROW_END.search(" " + line):
                current = {"no": int(start.group(1)), "text": start.group(2)}
                continue
            if current is None and start:  # whole row on one line
                current = {"no": int(start.group(1)), "text": start.group(2)}
            elif current is not None:
                current["text"] += " " + line
            if current is not None:
                end = ROW_END.search(" " + current["text"])
                if end:
                    desc = current["text"][:end.start()].strip()
                    first, last = int(end.group(2)), int(end.group(3) or end.group(2))
                    when = DATED.search(desc)
                    rows.append({"no": current["no"], "annexure": int(end.group(1)), "description": desc,
                                 "printed_pages": [first, last], "dated": when.group(1) if when else None})
                    current = None
        if rows:
            facts.add("case.evidence_index", rows, page, f"Evidence index: {len(rows)} annexures")
            return


# Receipt layouts print labels and values in separate columns (term-wise fees, then the total), so
# the total paid is taken as the largest amount printed against "Rs"/"₹" or "Total".
FEE_AMOUNTS = re.compile(rf"(?i)(?:Rs\.?|₹|\bTotal(?:\s*Paid)?\s*:?)\s*({NUM})")
FEE_DATE = re.compile(r"\b(\d{2}-[A-Za-z]{3}-\d{2,4}|\d{2}-\d{2}-\d{4}|\d{2}/\d{2}/\d{4})\b")


def parse_fee_receipt(page: Page, facts: Facts) -> None:
    """Tuition fee receipts offered for s.80C. Only the amount and date are kept, not the student."""
    flat = _flat(page.text)
    amounts = [num(m.group(1)) for m in FEE_AMOUNTS.finditer(flat) if re.search(r"\d", m.group(1))]
    amounts = [a for a in amounts if 100 <= a < 10_000_000]
    if not amounts:
        return
    amount = max(amounts)
    # Receipts print several dates (receipt, payment reference, printing) whose labels the text layer
    # separates from the values, so all of them are kept and the check decides what they show.
    dates = sorted({d.isoformat() for d in (_date(m.group(1)) for m in FEE_DATE.finditer(flat)) if d})
    ay = re.search(r"Academic Year\s*:?.*?(\d{4}-\d{4})", flat)
    facts.add("deduction.fee_receipt", {"amount": amount, "dates": dates, "academic_year": ay.group(1) if ay else None},
              page, f"Tuition fee receipt: Rs {amount:,.0f}" + (f", dates on receipt: {', '.join(dates)}" if dates
                                                                 else " (no legible date)"))


def parse_form16a(pages: list[Page], facts: Facts) -> None:
    seen = set()
    for page in pages:
        flat = _flat(page.text)
        cert = re.search(r"Certificate\s*(?:No\.?|Number)\s*:?\s*([A-Z0-9]{5,})", flat)
        amount = re.search(rf"a\s*sum\s*of\s*Rs\.?\s*({NUM})\s*\[", flat)
        if cert and amount and cert.group(1) not in seen:
            seen.add(cert.group(1))
            facts.add("form16a", {"certificate": cert.group(1), "tds": num(amount.group(1))}, page,
                      f"Form 16A {cert.group(1)}: Rs {amount.group(1)} deducted")


ORDER_AY = re.compile(r"Assessment Year\s*(\d{4}-\d{2})")
COMPUTATION_START = re.compile(r"(?i)total\s*income\s*of\s*the\s*assessee\s*is\s*computed\s*as\s*under")
COMP_ROW = re.compile(r"^(\d{1,2})\s+(.+?)\s+(?:Rs\.?\s*)?([\d,]{4,})\s*/?-?\s*$")


def parse_assessment_orders(pages: list[Page], facts: Facts) -> None:
    """One 'order' fact per assessment order (grouped by assessment year): its section, returned
    and assessed income, whether a variation was made, and each addition with its amount and section."""
    groups: dict[str, list[Page]] = {}
    current = None
    for page in pages:
        m = ORDER_AY.search(page.text) or re.search(r"A\.Y\.\s*(\d{4}-\d{2})", page.text)
        if m:
            current = m.group(1)
        groups.setdefault(current or "unknown", []).append(page)
    for ay, group in groups.items():
        text = "\n".join(p.text for p in group)
        flat = _flat(text)
        section = re.search(r"Order passed under section\s+([\d()A-Za-z ]+?)\s+(?:read with|r\.w\.s)", flat)
        returned = re.search(rf"Returned Income\s*Rs\.?\s*({NUM})", flat)
        no_variation = bool(re.search(r"(?i)no\s*variation\s*is\s*required|variation\s*is\s*not\s*proposed", flat))
        receipts = re.search(rf"(?i)gross\s*receipts\s*at\s*Rs\.?\s*({NUM})", flat)
        rate = re.search(r"(?i)u/s\s*44AD\s*@\s*([\d.]+)\s*%", flat)
        additions, assessed, rows_page = [], None, group[0]
        for page in group:
            lines = [ln.strip() for ln in page.text.splitlines() if ln.strip()]
            started = any(COMPUTATION_START.search(_flat(page.text)) for _ in [0])
            if not started:
                continue
            rows_page = page
            for line in lines:
                r = COMP_ROW.match(line)
                if not r:
                    continue
                desc, amount = r.group(2).strip(), num(r.group(3))
                if re.search(r"(?i)as per (?:ITR|return)|returned income|income declared", desc):
                    continue
                if re.search(r"(?i)assessed income|total income|net income", desc):
                    assessed = amount
                    continue
                sec = re.search(r"(?i)(?:u/s\.?|section)\s*(\d{1,3}[A-Z]{0,3}(?:\(\d+\))?)", desc)
                additions.append({"description": desc, "amount": amount, "section": sec.group(1) if sec else None,
                                  "page": page.number})
        facts.add("order", {"assessment_year": ay, "section": section.group(1).strip() if section else None,
                            "returned_income": num(returned.group(1)) if returned else None,
                            "assessed_income": assessed, "no_variation": no_variation and not additions,
                            "additions": additions, "gross_receipts": num(receipts.group(1)) if receipts else None,
                            "rate_44ad": float(rate.group(1)) if rate else None,
                            "offers_other_sources": bool(re.search(r"(?i)income\s*from\s*other\s*sources", flat)),
                            "pages": [p.number for p in group]},
                  rows_page, f"Assessment order for AY {ay}" + (f" u/s {section.group(1).strip()}" if section else ""))


def parse_case(by_type: dict[str, list[Page]], facts: Facts) -> None:
    for p in by_type.get("notice", []):
        parse_notice(p, facts)
    for p in by_type.get("proceeding_ack", []):
        parse_proceeding_ack(p, facts)
    parse_annexure_index(by_type.get("annexure_index", []), facts)
    for p in by_type.get("fee_receipt", []):
        parse_fee_receipt(p, facts)
    parse_form16a(by_type.get("form16a", []), facts)
    parse_assessment_orders(by_type.get("assessment_order", []), facts)
