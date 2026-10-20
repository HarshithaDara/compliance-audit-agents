from types import SimpleNamespace

import pytest

from agents.crosscheck import checks
from agents.reporter.drafter import ClaudeDrafter, GroundingError, TemplateDrafter, validate_grounding
from common.schemas import CITATION_RE, AuditMessage, Citation
from tests import factories


def message(values=None) -> AuditMessage:
    facts = factories.build(values=values)
    filing, findings = checks.run_all(facts, None)
    msg = AuditMessage.new("SYN", None)
    msg.company = checks.company_context("SYN", "0000000001", facts, filing)
    msg.findings = findings
    for f in msg.findings:
        f.citations = [Citation(citation="17 CFR 229.303", heading="Item 303 MD&A", excerpt="...",
                                source_url="https://www.ecfr.gov/current/title-17/section-229.303", score=0.9)]
    return msg


def test_template_report_has_required_sections():
    v = factories.healthy_values()
    v["Revenues"] = ("USD", True, 800e6, 600e6)
    report = TemplateDrafter().draft(message(v))
    for section in ("# Compliance Audit Report", "## Executive summary", "## Observations",
                    "## Recommended follow-up", "## Scope and limitations", "## Appendix A", "## Appendix B"):
        assert section in report
    assert "YOY_REVENUE" in report and "17 CFR 229.303" in report


def test_clean_report_still_has_every_section():
    report = TemplateDrafter().draft(message())
    assert "## Observations\n\nNo exceptions" in report
    assert "## Recommended follow-up" in report


def test_grounding_accepts_evidence_numbers_and_citations():
    msg = message()
    validate_grounding("Revenue was $800.0M and assets $1.00 billion under 17 CFR 229.303.", msg)


@pytest.mark.parametrize("text,expected", [
    ("see 17 CFR 229.303.", ["17 CFR 229.303"]),
    ("under 17 CFR 240.10D-1, and", ["17 CFR 240.10D-1"]),
    ("17 CFR 210.5-02; 17 CFR 240.12b-25", ["17 CFR 210.5-02", "17 CFR 240.12b-25"]),
])
def test_citation_regex(text, expected):
    assert CITATION_RE.findall(text) == expected


def test_grounding_accepts_mixed_case_rule_numbers():
    msg = message()
    msg.findings[0].citations[0].citation = "17 CFR 240.10D-1"
    validate_grounding("Restatements are defined in 17 CFR 240.10D-1.", msg)


def test_grounding_rejects_unretrieved_citation():
    with pytest.raises(GroundingError, match="17 CFR 210.4-01"):
        validate_grounding("See 17 CFR 210.4-01.", message())


def test_grounding_rejects_invented_number():
    with pytest.raises(GroundingError, match="\\$123.4M"):
        validate_grounding("Net income was $123.4M.", message())


class FakeClient:
    """Stands in for anthropic.Anthropic so the Claude path is tested without network."""

    def __init__(self, text, stop_reason="end_turn"):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self.text, self.stop_reason = text, stop_reason

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text=self.text)])


def test_claude_drafter_request_shape_and_output():
    client = FakeClient("## Executive summary\n**Satisfactory.** Revenue $800.0M (17 CFR 229.303).\n"
                        "## Observations\nNone.\n## Recommended follow-up\n- None")
    report = ClaudeDrafter(client).draft(message())
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert "<evidence>" in call["messages"][0]["content"]
    assert "Revenue $800.0M" in report and "## Appendix A" in report


def test_claude_drafter_rejects_hallucinated_citation():
    client = FakeClient("## Executive summary\nSee 17 CFR 999.1.")
    with pytest.raises(GroundingError):
        ClaudeDrafter(client).draft(message())


def test_claude_drafter_refusal_raises():
    with pytest.raises(GroundingError, match="declined"):
        ClaudeDrafter(FakeClient("", stop_reason="refusal")).draft(message())
