"""Report sections specific to document audits (uploaded income-tax / GST bundles).

Amounts are rendered in Indian notation, and every figure is accompanied by the PDF page it came
from (and the bundle's own printed page number when it differs), so a reviewer can open the
source page directly.
"""
from __future__ import annotations

import json

from common.schemas import AuditMessage, Evidence, Finding

RECOMMENDATIONS = {
    "TURNOVER_AIS_VS_ITR": "Reconcile the AIS/26AS receipts with the turnover offered, payer by payer, and file AIS feedback for any entry that is wrong.",
    "TURNOVER_GST_VS_ITR": "Add an invoice-level reconciliation of GST turnover (invoice date) to income-tax receipts (service period) to the submission.",
    "GSTR1_VS_GSTR3B": "Reconcile GSTR-1 with GSTR-3B for the mismatched months and amend in a later return if needed.",
    "INVOICES_VS_GSTR1": "Produce the missing invoices, or explain the difference between the invoices and the GSTR-1 values for the months listed.",
    "OTHER_INCOME_OMITTED": "Offer the AIS interest under 'income from other sources' (claiming s.80TTA on savings interest) or explain why it is not the taxpayer's income.",
    "TDS_CREDIT": "Reconcile the TDS claimed with Form 26AS / AIS and Form 16A; withdraw any excess claim.",
    "TDS_HEAD": "Correct the head of income in Schedule TDS2 so the credit is claimed where the receipt was offered.",
    "PRESUMPTIVE_44AD": "Address s.44AD(6) explicitly: show that the receipts are business income from an eligible business and not commission, brokerage or agency income, or compute income on actual books.",
    "AUDIT_44AB": "Obtain a tax audit report under s.44AB.",
    "TAX_COMPUTATION": "Recompute the tax and the s.87A rebate and correct the return.",
    "LATE_FILING": "Record the reason for the delay; confirm the s.234F fee is paid.",
    "CASH_WITHDRAWAL_194N": "Obtain the WLATMO monthly certificates for the uncovered months/accounts, and reconcile certificate totals to the bank's 194N reporting.",
    "BANK_STATEMENT_INTEGRITY": "Obtain the complete bank statement; the parsed pages do not reproduce the bank's summary.",
    "BANK_THIRD_PARTY_CREDITS": "Explain the nature and source of each listed third-party credit and cash deposit with confirmations (s.68).",
    "NARRATIVE_COVERAGE": "Extend the written submission to explain each discrepancy listed as not addressed.",
}

LIMITATIONS = ("## Scope and limitations\n\nThis report was generated automatically from the uploaded PDF. Figures were "
               "extracted by deterministic parsers for the ITR, AIS/TIS, GSTR-1/3B, tax invoices, bank statements and "
               "s.194N certificates; each figure cites the page it came from. Legal references are to the Income-tax "
               "Act, 1961 as explained in the Ministry of Finance's Finance Bill memoranda, and to the CGST Act, 2017. "
               "This is a reviewer's checklist, not legal advice or an assessment; conclusions on eligibility and "
               "explanations require professional judgement and the underlying records.")


def inr(v) -> str:
    if isinstance(v, bool) or v is None:
        return str(v)
    if not isinstance(v, (int, float)):
        return str(v)
    if abs(v) < 1000:
        return f"{v:g}" if isinstance(v, float) else str(v)
    neg, v = v < 0, abs(v)
    whole, frac = divmod(round(v, 2), 1)
    s = str(int(whole))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        s = f"{head},{tail}"
    out = f"₹{s}" + (f".{round(frac * 100):02d}" if frac >= 0.005 else "")
    return f"-{out}" if neg else out


def page_ref(e: Evidence) -> str:
    if e.printed_page and e.printed_page != str(e.page):
        return f"p.{e.page} (printed {e.printed_page})"
    return f"p.{e.page}"


def header(msg: AuditMessage, drafter: str) -> str:
    d = msg.document
    who = d.taxpayer or "Taxpayer"
    bits = [f"AY {d.assessment_year}" if d.assessment_year else None, d.form, f"PAN {d.pan_masked}" if d.pan_masked else None]
    return "\n".join([
        f"# Compliance Review - {who} ({', '.join(b for b in bits if b) or 'uploaded document'})",
        "",
        f"- **Document:** {d.filename} ({d.pages} pages, sha256 `{d.sha256[:16]}…`)",
        f"- **Job ID:** `{msg.job_id}`",
        f"- **AI reader:** {d.ai_reader_used or d.ai_reader}",
        "- **Law sources:** Income-tax Act, 1961 (Finance Bill memoranda, indiabudget.gov.in); CGST Act, 2017 (indiacode.gov.in)",
        f"- **Drafted by:** {drafter}",
        "",
    ])


def coverage_section(msg: AuditMessage) -> str:
    d = msg.document
    types = ", ".join(f"{k} {v}" for k, v in d.page_types.items())
    out = ["## Document coverage", "",
           f"{d.pages} pages read: {d.pages - d.ocr_pages - d.empty_pages} from the text layer, {d.ocr_pages} by OCR, "
           f"{d.empty_pages} unreadable (no text and nothing recognised by OCR).", "",
           f"Pages by type: {types}.", ""]
    if d.ai_figures:
        out += [f"Figures read by the AI reader on pages no parser covers ({len(d.ai_figures)}, each verified to "
                f"appear on its page):", "", "| Page | Figure | Value |", "|---|---|---|"]
        out += [f"| {page_ref(e)} | {e.label} | {e.value} |" for e in d.ai_figures[:40]]
        out.append("")
    return "\n".join(out)


def _value(v) -> str:
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str, ensure_ascii=False)[:600]
    return inr(v)


def evidence_block(f: Finding) -> list[str]:
    out = []
    if f.values:
        out += ["| Item | Value |", "|---|---|"] + [f"| {k} | {_value(v)} |" for k, v in f.values.items()] + [""]
    if f.evidence:
        out.append("Source pages:")
        for e in f.evidence[:16]:
            value = "" if e.value is None else f" = {inr(e.value)}"
            quote = f' - "{e.quote}"' if e.quote else ""
            out.append(f"- {page_ref(e)}: {e.label}{value}{quote}")
        if len(f.evidence) > 16:
            out.append(f"- … and {len(f.evidence) - 16} more pages")
        out.append("")
    return out
