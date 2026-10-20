"""Does the written submission explain each discrepancy the checks raised?

A keyword pass finds submission pages that discuss each flagged topic. When an AI reader is
available it then judges whether the passage actually explains the discrepancy (a passage that
only mentions the topic is "mentioned", not "explained"), and must quote the sentence it relied
on; quotes not found on the page are discarded.
"""
from __future__ import annotations

import re

from common.schemas import Evidence, Finding, Severity, Status

from agents.document import llm
from agents.document.pdftext import Page

# All patterns of a topic must appear on the same page for it to count as discussed there.
TOPICS: dict[str, list[str]] = {
    "TURNOVER_AIS_VS_ITR": [r"\bAIS\b|26AS", r"receipts|turnover"],
    "TURNOVER_GST_VS_ITR": [r"\bGST\b", r"turnover", r"timing|invoice date|month of|reconcil"],
    "GSTR1_VS_GSTR3B": [r"GSTR\s*[–-]\s*1", r"GSTR\s*[–-]\s*3B"],
    "INVOICES_VS_GSTR1": [r"invoice", r"GSTR\s*[–-]\s*1"],
    "OTHER_INCOME_OMITTED": [r"interest", r"other sources|savings|deposit"],
    "TDS_CREDIT": [r"\bTDS\b|tax deduct", r"26AS|\bAIS\b|16A"],
    "TDS_HEAD": [r"\bTDS\b", r"other sources|head of income"],
    "PRESUMPTIVE_44AD": [r"44AD", r"44AD\s*\(6\)|exclu|not appl|eligib|agency"],
    "AUDIT_44AB": [r"44AB"],
    "TAX_COMPUTATION": [r"87A|computation of (?:tax|income)"],
    "LATE_FILING": [r"139\s*\(4\)|belated|delay in filing|after the due date|234F"],
    "CASH_WITHDRAWAL_194N": [r"withdraw", r"194N|certificate|WLATMO"],
    "BANK_STATEMENT_INTEGRITY": [r"bank statement"],
    "BANK_THIRD_PARTY_CREDITS": [r"credit", r"third[- ]part|source of|deposit|transfer|gross (?:bank )?credits"],
    "NOTICE_COMPLIANCE": [r"ledger"],
    "DEDUCTION_EVIDENCE": [r"80C|Chapter VI-?A|deduction"],
    "YEAR_CONSISTENCY": [r"subsequent|previous|earlier", r"assessment year"],
}
# Case-level findings that are themselves about the papers, not discrepancies the submission should explain.
NOT_EXPLAINABLE = {"CASE_CONTEXT", "SUBMISSION_CLAIMS", "EVIDENCE_RELEVANCE", "AO_FIGURE_RECONCILIATION"}
MIN_QUOTE = 60  # shorter matches are table rows or headings, not explanations


def _discussed(text: str, patterns: list[str]) -> bool:
    return all(re.search(p, text, re.IGNORECASE) for p in patterns)


def _sentence_with(text: str, pattern: str) -> str:
    """The first prose sentence matching the pattern; table rows and headings are skipped."""
    flat = " ".join(text.split())
    for m in re.finditer(pattern, flat, re.IGNORECASE):
        start = max(flat.rfind(". ", 0, m.start()) + 2, 0)
        end = flat.find(". ", m.end())
        sentence = flat[start: end + 1 if end != -1 else len(flat)]
        if len(sentence) >= MIN_QUOTE and not re.match(r"^\d{1,2}\s", sentence) and sentence.count(" ") >= 8:
            return sentence[:240]
    return ""


def assess(findings: list[Finding], submission: list[Page], reader: llm.Reader | None = None,
           progress=lambda: None) -> Finding:
    flagged = [f for f in findings if f.status in (Status.WARN, Status.FAIL) and f.check_id not in NOT_EXPLAINABLE]
    q = "Rule 46A additional evidence appellate proceedings explanation submission remand report"
    if not submission:
        return Finding(check_id="NARRATIVE_COVERAGE", title="Written submission addresses each discrepancy",
                       status=Status.NOT_APPLICABLE, severity=Severity.INFO,
                       detail="Not tested: no written submission or explanation pages found in the document.",
                       reg_query=q)
    coverage: dict[str, dict] = {}
    for f in flagged:
        patterns = TOPICS.get(f.check_id, [re.escape(f.title.split()[0])])
        # A page counts only if it discusses the topic in prose (an index row naming the document does not).
        pages = [p for p in submission if _discussed(p.text, patterns) and _sentence_with(p.text, patterns[-1])]
        state, quote, quoted_page = ("mentioned" if pages else "unexplained"), "", None
        if pages:
            quote, quoted_page = _sentence_with(pages[0].text, patterns[-1]), pages[0].number
        if reader is not None and pages:
            state = "mentioned"
            for p in pages[:3]:
                progress()
                ok, q_text = llm.judge_coverage(reader, f.detail, p)
                if ok:
                    state, quote, quoted_page = "explained", q_text, p.number
                    break
        coverage[f.check_id] = {"status": state, "pages": [p.number for p in pages], "quote": quote}
        if quoted_page is not None:
            page = next(p for p in submission if p.number == quoted_page)
            f.evidence.append(Evidence(page=quoted_page, printed_page=page.printed,
                                       label=f"submission ({state})", value=None, quote=quote))
        f.values["submission_coverage"] = state
    unexplained = [c for c, v in coverage.items() if v["status"] == "unexplained"]
    mentioned = [c for c, v in coverage.items() if v["status"] == "mentioned"]
    explained = [c for c, v in coverage.items() if v["status"] == "explained"]
    how = "the AI reader confirmed explanations" if reader is not None else \
        "keyword matching only (enable the AI reader to judge whether passages actually explain the issue)"
    values = {"submission_pages": [p.number for p in submission], "coverage": coverage, "method": how}
    evidence = [Evidence(page=submission[0].number, printed_page=submission[0].printed, label="submission starts",
                         quote=" ".join(submission[0].text.split())[:160])]
    if not flagged:
        return Finding(check_id="NARRATIVE_COVERAGE", title="Written submission addresses each discrepancy",
                       status=Status.PASS, severity=Severity.INFO,
                       detail="No discrepancies were raised, so the submission has nothing to explain.",
                       values=values, reg_query=q, evidence=evidence)
    parts = []
    if unexplained:
        parts.append(f"not addressed anywhere in the {len(submission)} submission pages: {', '.join(unexplained)}")
    if mentioned:
        parts.append(f"topic discussed but the specific discrepancy is not explained: {', '.join(mentioned)}")
    if explained:
        parts.append(f"explained: {', '.join(explained)}")
    status = Status.WARN if unexplained or mentioned else Status.PASS
    severity = Severity.MEDIUM if unexplained else Severity.LOW if mentioned else Severity.INFO
    return Finding(check_id="NARRATIVE_COVERAGE", title="Written submission addresses each discrepancy",
                   status=status, severity=severity,
                   detail=f"Of {len(flagged)} discrepancies, " + "; ".join(parts) + f". Method: {how}.",
                   values=values, reg_query=q, evidence=evidence)
