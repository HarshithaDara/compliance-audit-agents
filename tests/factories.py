"""Builders for synthetic SEC companyfacts payloads (same shape as data.sec.gov)."""
from __future__ import annotations

CUR = ("2024-01-01", "2024-12-31")
PRI = ("2023-01-01", "2023-12-31")
ACCN = "0000000001-25-000010"
PRIOR_ACCN = "0000000001-24-000010"


def healthy_values() -> dict:
    """Internally consistent statements for FY2024 with FY2023 comparatives."""
    return {
        # concept: (unit, duration?, current, prior)
        "Assets": ("USD", False, 1000e6, 900e6),
        "Liabilities": ("USD", False, 600e6, 560e6),
        "StockholdersEquity": ("USD", False, 400e6, 340e6),
        "LiabilitiesAndStockholdersEquity": ("USD", False, 1000e6, 900e6),
        "AssetsCurrent": ("USD", False, 500e6, 450e6),
        "LiabilitiesCurrent": ("USD", False, 250e6, 240e6),
        "Revenues": ("USD", True, 800e6, 760e6),
        "CostOfRevenue": ("USD", True, 500e6, 480e6),
        "GrossProfit": ("USD", True, 300e6, 280e6),
        "NetIncomeLoss": ("USD", True, 100e6, 95e6),
        "WeightedAverageNumberOfDilutedSharesOutstanding": ("shares", True, 50e6, 50e6),
        "EarningsPerShareDiluted": ("USD/shares", True, 2.00, 1.90),
        "NetCashProvidedByUsedInOperatingActivities": ("USD", True, 150e6, 140e6),
        "NetCashProvidedByUsedInInvestingActivities": ("USD", True, -60e6, -50e6),
        "NetCashProvidedByUsedInFinancingActivities": ("USD", True, -40e6, -70e6),
        "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": ("USD", True, -5e6, 2e6),
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect":
            ("USD", True, 45e6, 22e6),
    }


def build(values: dict | None = None, filed: str = "2025-02-15", public_float: float = 5e9,
          prior_filing_overrides: dict | None = None, name: str = "Synthetic Corp") -> dict:
    values = values if values is not None else healthy_values()
    gaap: dict = {}

    def add(concept, unit, row):
        gaap.setdefault(concept, {"units": {}})["units"].setdefault(unit, []).append(row)

    for concept, (unit, duration, cur, pri) in values.items():
        for (start, end), val in ((CUR, cur), (PRI, pri)):
            row = {"end": end, "val": val, "accn": ACCN, "fy": 2024, "fp": "FY", "form": "10-K", "filed": filed}
            if duration:
                row["start"] = start
            add(concept, unit, row)
        # The prior-year 10-K originally reported the FY2023 numbers.
        orig = (prior_filing_overrides or {}).get(concept, pri)
        row = {"end": PRI[1], "val": orig, "accn": PRIOR_ACCN, "fy": 2023, "fp": "FY", "form": "10-K",
               "filed": "2024-02-15"}
        if duration:
            row["start"] = PRI[0]
        add(concept, unit, row)
    dei = {"EntityPublicFloat": {"units": {"USD": [
        {"end": "2024-06-30", "val": public_float, "accn": ACCN, "fy": 2024, "fp": "FY", "form": "10-K",
         "filed": filed}]}}}
    return {"cik": 1, "entityName": name, "facts": {"us-gaap": gaap, "dei": dei}}
