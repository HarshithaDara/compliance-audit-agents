"""Retrieval quality tests against the real scraped eCFR corpus."""
import os

import pytest

from agents.crosscheck import checks
from agents.regulation.retriever import INDEX_DIR, Retriever, section_scope
from tests import factories

MODES = ["bm25"] + (["hybrid"] if os.getenv("SKIP_DENSE") != "1" else [])


@pytest.fixture(scope="module", params=MODES)
def retriever(request):
    return Retriever(INDEX_DIR, mode=request.param)


@pytest.mark.parametrize("query,expected_section", [
    ("material changes in revenue from period to period Item 303", "229.303"),
    ("balance sheet captions total assets Rule 5-02", "210.5-02"),
    ("income statement costs and expenses applicable to sales Rule 5-03", "210.5-03"),
    ("notification of late filing of annual report Form 10-K Rule 12b-25", "240.12b-25"),
    ("definition of large accelerated filer public float", "240.12b-2"),
    ("non-GAAP financial measures reconciliation to most directly comparable GAAP measure", "244.100"),
    ("management's annual report on internal control over financial reporting", "229.308"),
])
def test_known_queries_hit_the_governing_section(retriever, query, expected_section):
    hits = retriever.search(query, k=3)
    assert expected_section in [h.section for h in hits], [h.citation for h in hits]


def test_every_check_query_returns_citations(retriever):
    _, findings = checks.run_all(factories.build(), None)
    for f in findings:
        hits = retriever.search(f.reg_query, k=3)
        assert len(hits) == 3
        assert len({h.section for h in hits}) == 3, "hits must be distinct sections"
        assert all(0 < h.score <= 1 for h in hits)


def test_general_company_never_gets_industry_or_deal_specific_rules(retriever):
    _, findings = checks.run_all(factories.build(), None)
    for f in findings:
        for h in retriever.search(f.reg_query, k=3, industry="general"):
            assert section_scope(h.section) == "general", (f.check_id, h.citation, h.heading)


def test_bank_balance_sheet_query_reaches_article_9(retriever):
    hits = retriever.search("bank holding company balance sheet loans deposits captions", k=3, industry="bank")
    assert any(h.section.startswith("210.9-") for h in hits), [h.citation for h in hits]


@pytest.mark.parametrize("section,scope", [
    ("210.5-02", "general"), ("210.9-03", "bank"), ("210.7-03", "insurance"), ("210.6-04", "investment_company"),
    ("210.4-10", "oil_gas"), ("229.303", "general"), ("229.1402", "bank"), ("229.905", "transaction"),
    ("229.1203", "oil_gas"), ("229.1604", "transaction"), ("240.12b-2", "general"),
])
def test_section_scope(section, scope):
    assert section_scope(section) == scope


@pytest.mark.parametrize("sic,industry", [("6021", "bank"), ("6331", "insurance"), ("2911", "oil_gas"),
                                          ("1311", "oil_gas"), ("1040", "mining"), ("3571", "general"),
                                          (None, "general")])
def test_industry_for_sic(sic, industry):
    assert checks.industry_for_sic(sic) == industry


def test_search_is_deterministic(retriever):
    q = "statement of cash flows operating investing financing activities"
    assert [h.section for h in retriever.search(q)] == [h.section for h in retriever.search(q)]
