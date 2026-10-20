"""Audit report drafting.

Two drafters share one contract (findings + citations in, markdown out):
  * ClaudeDrafter   - writes the narrative with Claude, then a grounding validator checks
                      that every CFR citation and every large number in the draft came from
                      the agents' evidence. Ungrounded drafts are rejected.
  * TemplateDrafter - deterministic, no network; used when no API key is configured and as
                      the fallback when a Claude draft fails validation.
"""
from __future__ import annotations

import json
import re

from common import config
from common.schemas import CITATION_RE, AuditMessage, Finding, Severity, Status

SEVERITY_ORDER = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2, Severity.INFO: 3}
STATUS_ICON = {Status.PASS: "PASS", Status.WARN: "WARN", Status.FAIL: "FAIL", Status.NOT_APPLICABLE: "N/A"}


def fmt_num(v) -> str:
    if isinstance(v, bool) or v is None:
        return str(v)
    if isinstance(v, (int, float)):
        if abs(v) >= 1_000_000:
            return f"${v / 1e6:,.1f}M" if abs(v) < 1e9 else f"${v / 1e9:,.2f}B"
        if float(v).is_integer():
            return f"{int(v):,}"
        return f"{v:,.2f}"
    return str(v)


def overall_rating(findings: list[Finding]) -> str:
    if any(f.status == Status.FAIL and f.severity == Severity.HIGH for f in findings):
        return "Exceptions noted - material issues require follow-up"
    if any(f.status in (Status.FAIL, Status.WARN) and f.severity in (Severity.HIGH, Severity.MEDIUM) for f in findings):
        return "Satisfactory with observations"
    return "Satisfactory - no exceptions"


def sorted_findings(findings: list[Finding]) -> list[Finding]:
    rank = {Status.FAIL: 0, Status.WARN: 1, Status.PASS: 2, Status.NOT_APPLICABLE: 3}
    return sorted(findings, key=lambda f: (rank[f.status], SEVERITY_ORDER[f.severity], f.check_id))


def _values_table(values: dict) -> str:
    rows = []
    for k, v in values.items():
        if isinstance(v, dict):
            v = json.dumps(v, default=str)
        rows.append(f"| {k} | {fmt_num(v) if not isinstance(v, str) else v} |")
    return "| Item | Value |\n|---|---|\n" + "\n".join(rows) if rows else ""


def evidence_appendix(msg: AuditMessage) -> str:
    out = ["## Appendix A - Check results and evidence", ""]
    for f in sorted_findings(msg.findings):
        out.append(f"### [{STATUS_ICON[f.status]}] {f.check_id} - {f.title}")
        out.append(f"*Severity: {f.severity.value}*  ")
        out.append(f.detail)
        out.append("")
        if f.values:
            out.append(_values_table(f.values))
            out.append("")
        if f.citations:
            out.append("Governing provisions:")
            for c in f.citations:
                out.append(f"- [{c.citation}]({c.source_url}) - {c.heading} (relevance {c.score:.2f})")
            out.append("")
    return "\n".join(out)


def header(msg: AuditMessage, drafter: str) -> str:
    c = msg.company
    return "\n".join([
        f"# Compliance Audit Report - {c.name} ({c.ticker})",
        "",
        f"- **Filing:** Form {c.form}, fiscal year {c.fiscal_year} (period ended {c.period_end}), filed {c.filed}",
        f"- **Accession:** [{c.accession}]({c.source_url})",
        f"- **Job ID:** `{msg.job_id}`",
        f"- **Data sources:** SEC EDGAR XBRL company facts (live); eCFR Title 17 (Regulations S-X, S-K, G; Exchange Act rules)",
        f"- **Drafted by:** {drafter}",
        "",
    ])


def pipeline_trace(msg: AuditMessage) -> str:
    rows = ["## Appendix B - Agent trace", "", "| Agent | Pod | Note |", "|---|---|---|"]
    rows += [f"| {t.agent} | {t.consumer} | {t.note} |" for t in msg.trace]
    return "\n".join(rows)


class TemplateDrafter:
    name = "template drafter (deterministic)"

    def draft(self, msg: AuditMessage) -> str:
        fs = msg.findings
        flagged = [f for f in sorted_findings(fs) if f.status in (Status.FAIL, Status.WARN)]
        passed = [f for f in fs if f.status == Status.PASS]
        na = [f for f in fs if f.status == Status.NOT_APPLICABLE]
        lines = [header(msg, self.name), "## Executive summary", "",
                 f"**Overall assessment:** {overall_rating(fs)}.", "",
                 f"{len(fs)} automated checks were run against the XBRL financial data: {len(passed)} passed, "
                 f"{len(flagged)} raised observations and {len(na)} were not applicable to this filer's tagging.", ""]
        lines += ["## Observations", ""]
        for i, f in enumerate(flagged, 1):
            cites = ", ".join(c.citation for c in f.citations[:2]) or "no governing provision retrieved"
            lines.append(f"{i}. **{f.title}** ({f.severity.value}, {f.status.value}). {f.detail} "
                         f"Relevant provisions: {cites}.")
        if not flagged:
            lines.append("No exceptions were identified by the automated checks.")
        lines += ["", "## Recommended follow-up", ""]
        for f in flagged:
            lines.append(f"- {RECOMMENDATIONS.get(f.check_id, 'Review the underlying disclosure with management.')}")
        if not flagged:
            lines.append("- None required from the automated checks; retain this report with the filing review file.")
        lines.append("")
        lines += [LIMITATIONS, "", evidence_appendix(msg), "", pipeline_trace(msg)]
        return "\n".join(lines)


RECOMMENDATIONS = {
    "BS_IDENTITY": "Reconcile the balance sheet totals and confirm the XBRL tagging of total assets and total liabilities and equity.",
    "BS_COMPONENTS": "Identify the untagged balance sheet caption (e.g. mezzanine equity, commitments) that explains the gap.",
    "GROSS_PROFIT": "Confirm whether the cost-of-revenue caption excludes items that are deducted in arriving at gross profit.",
    "EPS_DILUTED": "Obtain the EPS computation (ASC 260) and reconcile the numerator and diluted share count to reported EPS.",
    "CASH_RECON": "Reconcile operating, investing and financing totals to the change in cash, including restricted cash and FX effects.",
    "YOY_REVENUE": "Verify that MD&A quantifies and explains the drivers of the revenue change, as Item 303(b)(2) requires.",
    "YOY_NET_INCOME": "Verify that MD&A explains the components driving the change in net income, as Item 303(b)(2) requires.",
    "RESTATEMENT": "Confirm that recast prior-year amounts are labeled and that the nature of the restatement or reclassification is disclosed.",
    "FILING_TIMELINESS": "Confirm the filer category and whether a Form 12b-25 notification was filed.",
    "LIQUIDITY": "Confirm that the liquidity and capital resources discussion addresses the flagged indicators.",
    "XBRL_CONSISTENCY": "Correct duplicate facts with conflicting values in the Inline XBRL exhibit.",
}

LIMITATIONS = ("## Scope and limitations\n\nThis report is generated automatically from the company's XBRL-tagged "
               "financial data and the text of SEC regulations. It tests arithmetic consistency and disclosure "
               "triggers only; it is not an audit opinion under PCAOB standards and does not evaluate internal "
               "control over financial reporting, the narrative content of MD&A, or untagged disclosures.")


SYSTEM_PROMPT = """You are the report-drafting agent in a multi-agent financial compliance review.
Other agents have already (1) run accounting cross-checks on a public company's SEC XBRL data and (2) retrieved the governing SEC regulations for each check.
Write the narrative sections of the audit report for an audit committee reader.

Ground every statement in the evidence JSON:
- Cite regulations only by the exact `citation` strings in the evidence (e.g. "17 CFR 229.303"). Never cite anything else.
- Quote numbers only as they appear in the evidence (you may round and express in $M/$B).
- If a check is not applicable, say so briefly rather than speculating.
- This is an automated review of tagged data, not a PCAOB audit opinion; don't claim otherwise.

Output GitHub-flavored markdown with exactly these sections:
## Executive summary   (overall assessment in one bolded sentence, then 2-4 sentences)
## Observations        (one numbered item per WARN/FAIL check, most severe first: what was found, why it matters, the governing provision)
## Recommended follow-up (bullets, one per observation)
Do not add a title or any other sections."""


class GroundingError(ValueError):
    pass


def validate_grounding(text: str, msg: AuditMessage) -> None:
    allowed_cites = {c.citation for f in msg.findings for c in f.citations}
    for cite in set(CITATION_RE.findall(text)):
        if cite not in allowed_cites:
            raise GroundingError(f"draft cites {cite}, which no agent retrieved")
    evidence_nums: list[float] = []

    def walk(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            evidence_nums.append(float(v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    for f in msg.findings:
        walk(f.values)
    for m in re.finditer(r"\$\s?([0-9][0-9,]*\.?[0-9]*)\s*(billion|million|B|M)\b", text):
        amount = float(m.group(1).replace(",", ""))
        scale = 1e9 if m.group(2) in ("billion", "B") else 1e6
        value = amount * scale
        tol = max(0.06 * scale, abs(value) * 0.01)
        if not any(abs(abs(n) - value) <= tol for n in evidence_nums):
            raise GroundingError(f"draft states {m.group(0)}, which does not match any evidence value")


class ClaudeDrafter:
    name = f"Claude ({config.ANTHROPIC_MODEL}) with grounding validation"

    def __init__(self, client=None):
        import anthropic
        self.client = client or anthropic.Anthropic()

    def _evidence(self, msg: AuditMessage) -> str:
        return json.dumps({
            "company": msg.company.model_dump(),
            "findings": [{"check_id": f.check_id, "title": f.title, "status": f.status.value,
                          "severity": f.severity.value, "detail": f.detail, "values": f.values,
                          "citations": [{"citation": c.citation, "heading": c.heading, "excerpt": c.excerpt[:400]}
                                        for c in f.citations]} for f in msg.findings],
        }, indent=1, default=str)

    def narrative(self, msg: AuditMessage) -> str:
        response = self.client.beta.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=16000,
            output_config={"effort": "high"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"<evidence>\n{self._evidence(msg)}\n</evidence>"}],
        )
        if response.stop_reason == "refusal":
            raise GroundingError("model declined to draft the report")
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not text:
            raise GroundingError("empty draft")
        validate_grounding(text, msg)
        return text

    def draft(self, msg: AuditMessage) -> str:
        body = self.narrative(msg)
        return "\n".join([header(msg, self.name), body, "", LIMITATIONS, "", evidence_appendix(msg), "",
                          pipeline_trace(msg)])


def make_drafter():
    import os
    mode = config.LLM_MODE
    if mode == "template" or (mode == "auto" and not os.getenv("ANTHROPIC_API_KEY")):
        return TemplateDrafter()
    return ClaudeDrafter()
