import pytest

from agents.crosscheck import checks
from common.schemas import Severity, Status
from tests import factories


def by_id(findings):
    return {f.check_id: f for f in findings}


def run(**kw):
    filing, findings = checks.run_all(factories.build(**kw), None)
    return filing, by_id(findings)


def test_healthy_company_passes_every_check():
    filing, f = run()
    assert filing.accn == factories.ACCN and filing.period_end == "2024-12-31"
    assert len(f) == 11
    bad = {k: v.detail for k, v in f.items() if v.status in (Status.FAIL, Status.WARN)}
    assert bad == {}


def test_balance_sheet_mismatch_fails_high():
    v = factories.healthy_values()
    v["LiabilitiesAndStockholdersEquity"] = ("USD", False, 990e6, 900e6)
    _, f = run(values=v)
    assert f["BS_IDENTITY"].status == Status.FAIL
    assert f["BS_IDENTITY"].severity == Severity.HIGH
    assert f["BS_IDENTITY"].values["difference"] == pytest.approx(10e6)


def test_gross_profit_mismatch():
    v = factories.healthy_values()
    v["GrossProfit"] = ("USD", True, 250e6, 280e6)
    _, f = run(values=v)
    assert f["GROSS_PROFIT"].status == Status.FAIL


def test_eps_inconsistent():
    v = factories.healthy_values()
    v["EarningsPerShareDiluted"] = ("USD/shares", True, 2.40, 1.90)
    _, f = run(values=v)
    assert f["EPS_DILUTED"].status == Status.FAIL
    assert f["EPS_DILUTED"].values["implied_eps"] == pytest.approx(2.0)


def test_eps_rounding_tolerated():
    v = factories.healthy_values()
    v["EarningsPerShareDiluted"] = ("USD/shares", True, 2.01, 1.90)
    _, f = run(values=v)
    assert f["EPS_DILUTED"].status == Status.PASS


def test_cash_flow_gap_fails():
    v = factories.healthy_values()
    v["NetCashProvidedByUsedInOperatingActivities"] = ("USD", True, 180e6, 140e6)
    _, f = run(values=v)
    assert f["CASH_RECON"].status == Status.FAIL
    assert f["CASH_RECON"].values["difference"] == pytest.approx(-30e6)


def test_material_revenue_change_warns():
    v = factories.healthy_values()
    v["Revenues"] = ("USD", True, 800e6, 600e6)
    _, f = run(values=v)
    assert f["YOY_REVENUE"].status == Status.WARN
    assert f["YOY_REVENUE"].values["change_pct"] == pytest.approx(33.33, abs=0.01)
    assert "Item 303" in f["YOY_REVENUE"].reg_query


def test_restatement_detected():
    _, f = run(prior_filing_overrides={"NetIncomeLoss": 110e6})
    r = f["RESTATEMENT"]
    assert r.status == Status.WARN and r.severity == Severity.HIGH
    assert r.values["differences"]["NetIncomeLoss"]["originally_reported"] == 110e6


@pytest.mark.parametrize("original_eps,label", [(1.90 / 8, "1-for-8 reverse split"), (1.90 * 4, "4-for-1 split")])
def test_stock_split_is_not_a_restatement(original_eps, label):
    """Regression: GE's 2021 1-for-8 reverse split recast EPS 0.58 -> 4.63."""
    _, f = run(prior_filing_overrides={"EarningsPerShareDiluted": original_eps})
    r = f["RESTATEMENT"]
    assert r.status == Status.PASS
    assert r.values["split_adjusted"]["EarningsPerShareDiluted"]["split_ratio"] == label


def test_eps_deducts_preferred_dividends():
    """Regression: JPM tags NetIncomeLoss plus preferred dividends rather than income to common."""
    v = factories.healthy_values()
    v["NetIncomeLoss"] = ("USD", True, 105e6, 95e6)
    v["PreferredStockDividendsIncomeStatementImpact"] = ("USD", True, 5e6, 5e6)
    _, f = run(values=v)
    assert f["EPS_DILUTED"].status == Status.PASS
    assert f["EPS_DILUTED"].values["implied_eps"] == pytest.approx(2.0)


@pytest.mark.parametrize("filed,pf,expected", [
    ("2025-02-20", 5e9, Status.PASS),      # day 51, large accelerated (60)
    ("2025-03-10", 5e9, Status.WARN),      # day 69, inside 12b-25 extension
    ("2025-04-30", 5e9, Status.FAIL),      # day 120
    ("2025-03-10", 100e6, Status.PASS),    # day 69, accelerated (75)
    ("2025-03-25", 10e6, Status.PASS),     # day 84, non-accelerated (90)
])
def test_filing_deadline_by_filer_category(filed, pf, expected):
    _, f = run(filed=filed, public_float=pf)
    assert f["FILING_TIMELINESS"].status == expected


def test_going_concern_indicators():
    v = factories.healthy_values()
    v["StockholdersEquity"] = ("USD", False, -50e6, 340e6)
    v["NetCashProvidedByUsedInOperatingActivities"] = ("USD", True, -20e6, 140e6)
    _, f = run(values=v)
    assert f["LIQUIDITY"].status == Status.WARN and f["LIQUIDITY"].severity == Severity.HIGH


def test_missing_concepts_are_not_applicable():
    v = factories.healthy_values()
    for c in ("GrossProfit", "CostOfRevenue"):
        v.pop(c)
    _, f = run(values=v)
    assert f["GROSS_PROFIT"].status == Status.NOT_APPLICABLE


def test_future_dated_instant_fact_does_not_move_period_end():
    facts = factories.build()
    facts["facts"]["us-gaap"]["RestructuringAndRelatedCostExpectedCost1"] = {"units": {"USD": [
        {"end": "2026-09-30", "val": 1e6, "accn": factories.ACCN, "fy": 2024, "fp": "FY", "form": "10-K",
         "filed": "2025-02-15"}]}}
    filing = checks.select_filing(facts, None)
    assert filing.period_end == "2024-12-31"


def test_select_unknown_fiscal_year_raises():
    with pytest.raises(ValueError, match="no 10-K for fiscal year 2015"):
        checks.select_filing(factories.build(), 2015)
