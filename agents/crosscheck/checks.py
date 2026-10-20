"""Deterministic accounting cross-checks over SEC XBRL company facts.

Every check reads the numbers a company tagged in its 10-K and verifies an accounting
identity or disclosure trigger. Each returns a Finding with the exact numbers used and
a `reg_query` that the regulation agent turns into citations.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from common.schemas import CompanyContext, Finding, Severity, Status

ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT"}

REVENUE = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
           "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"]
COST_OF_REVENUE = ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"]
EQUITY_TOTAL = ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity"]
TEMP_EQUITY = ["TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterests",
               "TemporaryEquityCarryingAmountAttributableToParent",
               "RedeemableNoncontrollingInterestEquityCarryingAmount"]
NET_INCOME = ["NetIncomeLoss", "ProfitLoss"]
NI_TO_COMMON_DILUTED = ["NetIncomeLossAvailableToCommonStockholdersDiluted", "NetIncomeLoss"]
PREFERRED_DIVIDENDS = ["PreferredStockDividendsIncomeStatementImpact", "DividendsPreferredStock",
                       "PreferredStockDividendsAndOtherAdjustments"]
# Forward and reverse split ratios; per-share data is retroactively restated for splits.
SPLIT_FACTORS = [2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50]
CASH_CHANGE_INCL_FX = ["CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
                       "CashAndCashEquivalentsPeriodIncreaseDecrease"]
CASH_CHANGE_EXCL_FX = ["CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect",
                       "CashAndCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect"]
CFO = ["NetCashProvidedByUsedInOperatingActivities"]
CFI = ["NetCashProvidedByUsedInInvestingActivities"]
CFF = ["NetCashProvidedByUsedInFinancingActivities"]
FX = ["EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
      "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
      "EffectOfExchangeRateOnCashAndCashEquivalents"]
DISCONTINUED_CASH = ["CashProvidedByUsedInDiscontinuedOperations",
                     "CashProvidedByUsedInOperatingActivitiesDiscontinuedOperations",
                     "CashProvidedByUsedInInvestingActivitiesDiscontinuedOperations",
                     "CashProvidedByUsedInFinancingActivitiesDiscontinuedOperations"]

MATERIAL_CHANGE_PCT = 20.0


def _d(s: str) -> date:
    return date.fromisoformat(s)


@dataclass(frozen=True)
class Filing:
    accn: str
    form: str
    fy: int
    period_end: str
    filed: str


@dataclass(frozen=True)
class Fact:
    concept: str
    unit: str
    val: float
    start: str | None
    end: str
    accn: str
    form: str
    filed: str


class FactBook:
    """Index of a company's XBRL facts, scoped to one annual filing."""

    def __init__(self, company_facts: dict, filing: Filing):
        self.raw = company_facts
        self.filing = filing
        self.facts: dict[str, list[Fact]] = {}
        for taxonomy in ("us-gaap", "dei"):
            for concept, body in company_facts.get("facts", {}).get(taxonomy, {}).items():
                for unit, rows in body.get("units", {}).items():
                    for row in rows:
                        self.facts.setdefault(concept, []).append(Fact(
                            concept, unit, row["val"], row.get("start"), row["end"],
                            row["accn"], row.get("form", ""), row.get("filed", "")))
        pe = _d(filing.period_end)
        self.current_end = pe
        self.prior_end = pe - timedelta(days=365)

    @staticmethod
    def _near(d: str, target: date, days: int = 10) -> bool:
        return abs((_d(d) - target).days) <= days

    def _pick(self, concepts: list[str], end: date, duration: bool, accn: str | None) -> Fact | None:
        accn = accn or self.filing.accn
        for c in concepts:
            for f in self.facts.get(c, []):
                if f.accn != accn or not self._near(f.end, end):
                    continue
                if duration:
                    if not f.start or not 340 <= (_d(f.end) - _d(f.start)).days <= 380:
                        continue
                elif f.start:
                    continue
                return f
        return None

    def cur(self, concepts: list[str], duration: bool = True) -> Fact | None:
        return self._pick(concepts, self.current_end, duration, None)

    def prior(self, concepts: list[str], duration: bool = True, accn: str | None = None) -> Fact | None:
        return self._pick(concepts, self.prior_end, duration, accn)

    def conflicting(self, concept: str) -> list[tuple[Fact, Fact]]:
        """Same concept, same period, same filing, different values."""
        seen: dict[tuple, Fact] = {}
        out = []
        for f in self.facts.get(concept, []):
            if f.accn != self.filing.accn:
                continue
            key = (f.unit, f.start, f.end)
            if key in seen and seen[key].val != f.val:
                out.append((seen[key], f))
            seen.setdefault(key, f)
        return out


def annual_filings(company_facts: dict) -> list[Filing]:
    by_accn: dict[str, dict] = {}
    for body in company_facts.get("facts", {}).get("us-gaap", {}).values():
        for rows in body.get("units", {}).values():
            for row in rows:
                if row.get("form") not in ANNUAL_FORMS or row.get("fp") != "FY":
                    continue
                cur = by_accn.setdefault(row["accn"], {"form": row["form"], "fy": row.get("fy"),
                                                       "end": "", "filed": row.get("filed", "")})
                # The fiscal period end is the latest end date of an annual-duration fact.
                # (Instant facts can carry future dates, e.g. expected restructuring costs.)
                start = row.get("start")
                if not start or not 340 <= (_d(row["end"]) - _d(start)).days <= 380:
                    continue
                if row["end"] > cur["end"] and row["end"] <= cur["filed"]:
                    cur["end"] = row["end"]
    by_accn = {a: v for a, v in by_accn.items() if v["end"]}
    filings = [Filing(a, v["form"], int(v["fy"] or _d(v["end"]).year), v["end"], v["filed"])
               for a, v in by_accn.items()]
    return sorted(filings, key=lambda f: (f.period_end, f.filed))


def select_filing(company_facts: dict, fiscal_year: int | None) -> Filing:
    filings = [f for f in annual_filings(company_facts) if f.form != "10-K/A"]
    if not filings:
        raise ValueError("no annual (10-K) filings with XBRL data")
    if fiscal_year is None:
        return filings[-1]
    for f in reversed(filings):
        if f.fy == fiscal_year:
            return f
    for f in reversed(filings):
        if _d(f.period_end).year == fiscal_year:
            return f
    years = sorted({f.fy for f in filings})
    raise ValueError(f"no 10-K for fiscal year {fiscal_year}; available: {years[-8:]}")


def _pct(a: float, b: float) -> float:
    return 0.0 if b == 0 else (a - b) / abs(b) * 100.0


def _na(check_id: str, title: str, reason: str, query: str) -> Finding:
    return Finding(check_id=check_id, title=title, status=Status.NOT_APPLICABLE, severity=Severity.INFO,
                   detail=reason, reg_query=query)


# ---------------------------------------------------------------- checks

def check_balance_sheet_identity(fb: FactBook) -> Finding:
    cid, title = "BS_IDENTITY", "Balance sheet totals agree (assets = liabilities + equity)"
    q = "balance sheet total assets equal total liabilities and stockholders equity Rule 5-02 balance sheets"
    a = fb.cur(["Assets"], duration=False)
    lse = fb.cur(["LiabilitiesAndStockholdersEquity"], duration=False)
    if not a or not lse:
        return _na(cid, title, "Assets or LiabilitiesAndStockholdersEquity not tagged for the period.", q)
    diff = a.val - lse.val
    ok = abs(diff) <= max(1.0, abs(a.val) * 0.0001)
    return Finding(check_id=cid, title=title, status=Status.PASS if ok else Status.FAIL,
                   severity=Severity.INFO if ok else Severity.HIGH,
                   detail=("Total assets equal total liabilities and equity." if ok else
                           f"Total assets differ from total liabilities and equity by {diff:,.0f}."),
                   values={"Assets": a.val, "LiabilitiesAndStockholdersEquity": lse.val, "difference": diff},
                   reg_query=q)


def check_balance_sheet_components(fb: FactBook) -> Finding:
    cid, title = "BS_COMPONENTS", "Liabilities and equity components sum to the reported total"
    q = "balance sheet liabilities redeemable preferred stocks temporary equity stockholders equity captions Rule 5-02"
    lse = fb.cur(["LiabilitiesAndStockholdersEquity"], duration=False)
    liab = fb.cur(["Liabilities"], duration=False)
    eq = fb.cur(EQUITY_TOTAL, duration=False)
    if not lse or not liab or not eq:
        return _na(cid, title, "Total liabilities, equity or their sum is not separately tagged.", q)
    temp = fb.cur(TEMP_EQUITY, duration=False)
    temp_val = temp.val if temp else 0.0
    total = liab.val + eq.val + temp_val
    diff = lse.val - total
    tol = max(1.0, abs(lse.val) * 0.001)
    ok = abs(diff) <= tol
    values = {"Liabilities": liab.val, eq.concept: eq.val, "LiabilitiesAndStockholdersEquity": lse.val,
              "difference": diff}
    if temp:
        values[temp.concept] = temp.val
    return Finding(check_id=cid, title=title, status=Status.PASS if ok else Status.WARN,
                   severity=Severity.INFO if ok else Severity.MEDIUM,
                   detail=("Liabilities plus equity (including any temporary equity) equal the reported total." if ok
                           else f"Components leave {diff:,.0f} unexplained (possible untagged mezzanine or "
                                f"commitments line)."),
                   values=values, reg_query=q)


def check_gross_profit(fb: FactBook) -> Finding:
    cid, title = "GROSS_PROFIT", "Gross profit equals revenue minus cost of revenue"
    q = "income statement net sales gross revenues costs and expenses applicable to sales and revenues Rule 5-03"
    rev, cost, gp = fb.cur(REVENUE), fb.cur(COST_OF_REVENUE), fb.cur(["GrossProfit"])
    if not rev or not cost or not gp:
        return _na(cid, title, "Revenue, cost of revenue or gross profit not all tagged (common for banks/insurers).", q)
    diff = (rev.val - cost.val) - gp.val
    ok = abs(diff) <= max(1.0, abs(rev.val) * 0.001)
    return Finding(check_id=cid, title=title, status=Status.PASS if ok else Status.FAIL,
                   severity=Severity.INFO if ok else Severity.HIGH,
                   detail=("Revenue less cost of revenue equals reported gross profit." if ok else
                           f"Revenue less cost of revenue differs from gross profit by {diff:,.0f}."),
                   values={rev.concept: rev.val, cost.concept: cost.val, "GrossProfit": gp.val, "difference": diff},
                   reg_query=q)


def check_eps(fb: FactBook) -> Finding:
    cid, title = "EPS_DILUTED", "Diluted EPS consistent with net income and diluted share count"
    q = "income statement earnings per share net income attributable to common stockholders Rule 5-03 per share data"
    ni = fb.cur(NI_TO_COMMON_DILUTED)
    sh = fb.cur(["WeightedAverageNumberOfDilutedSharesOutstanding"])
    eps = fb.cur(["EarningsPerShareDiluted"])
    if not ni or not sh or not eps or sh.val == 0:
        return _na(cid, title, "Net income, diluted shares or diluted EPS not tagged.", q)
    numerator = ni.val
    values = {ni.concept: ni.val}
    if ni.concept == "NetIncomeLoss":
        # EPS is computed on income available to common holders: deduct preferred dividends.
        pref = fb.cur(PREFERRED_DIVIDENDS)
        if pref:
            numerator -= pref.val
            values[pref.concept] = pref.val
    implied = numerator / sh.val
    gap = abs(implied - eps.val)
    rel = gap / abs(eps.val) * 100 if eps.val else 100.0
    if gap <= 0.015 or rel <= 2.0:
        status, sev, detail = Status.PASS, Severity.INFO, "Implied diluted EPS matches the reported figure within rounding."
    elif rel <= 5.0:
        status, sev = Status.WARN, Severity.MEDIUM
        detail = (f"Implied diluted EPS {implied:.2f} vs reported {eps.val:.2f} ({rel:.1f}% gap); "
                  f"may reflect participating securities or preferred dividends.")
    else:
        status, sev = Status.FAIL, Severity.HIGH
        detail = f"Implied diluted EPS {implied:.2f} vs reported {eps.val:.2f} ({rel:.1f}% gap)."
    values.update({"WeightedAverageNumberOfDilutedSharesOutstanding": sh.val, "EarningsPerShareDiluted": eps.val,
                   "implied_eps": round(implied, 4)})
    return Finding(check_id=cid, title=title, status=status, severity=sev, detail=detail, values=values,
                   reg_query=q)


def check_cash_flow(fb: FactBook) -> Finding:
    cid, title = "CASH_RECON", "Cash flow sections reconcile to the change in cash"
    q = ("statements of cash flows Rule 3-02 operating investing financing activities net change in cash "
         "and cash equivalents")
    cfo, cfi, cff = fb.cur(CFO), fb.cur(CFI), fb.cur(CFF)
    incl, excl = fb.cur(CASH_CHANGE_INCL_FX), fb.cur(CASH_CHANGE_EXCL_FX)
    if not cfo or not cfi or not cff or not (incl or excl):
        return _na(cid, title, "Cash flow section totals or the net change in cash are not tagged.", q)
    fx = fb.cur(FX)
    computed = cfo.val + cfi.val + cff.val
    values = {"CFO": cfo.val, "CFI": cfi.val, "CFF": cff.val}
    if incl:
        computed += fx.val if fx else 0.0
        reported = incl
        if fx:
            values["FX_effect"] = fx.val
    else:
        reported = excl
    disc = [f for f in (fb.cur([c]) for c in DISCONTINUED_CASH) if f]
    diff = reported.val - computed
    values.update({reported.concept: reported.val, "computed": computed, "difference": diff})
    tol = max(1_000_000.0, max(abs(cfo.val), abs(cfi.val), abs(cff.val)) * 0.005)
    if abs(diff) <= tol:
        status, sev, detail = Status.PASS, Severity.INFO, "Operating + investing + financing (+FX) equals the reported change in cash."
    elif disc:
        status, sev = Status.WARN, Severity.LOW
        detail = f"Unreconciled {diff:,.0f}, likely discontinued-operations cash flows tagged separately."
    else:
        status, sev = Status.FAIL, Severity.HIGH
        detail = f"Cash flow sections do not reconcile to the change in cash; gap {diff:,.0f}."
    return Finding(check_id=cid, title=title, status=status, severity=sev, detail=detail, values=values, reg_query=q)


def _yoy(fb: FactBook, cid: str, title: str, concepts: list[str], label: str) -> Finding:
    q = (f"management's discussion and analysis results of operations material changes in {label} "
         "from period to period reasons underlying Item 303")
    cur = fb.cur(concepts)
    pri = fb.prior(concepts) if cur else None
    if cur and pri is None:
        pri = fb.prior([cur.concept])
    if not cur or not pri:
        return _na(cid, title, f"Current or prior-year {label} not tagged in the filing.", q)
    change = _pct(cur.val, pri.val)
    material = abs(change) >= MATERIAL_CHANGE_PCT
    return Finding(check_id=cid, title=title, status=Status.WARN if material else Status.PASS,
                   severity=Severity.MEDIUM if material else Severity.INFO,
                   detail=(f"{label.capitalize()} changed {change:+.1f}% year over year; Item 303 requires the "
                           f"MD&A to explain material changes." if material else
                           f"{label.capitalize()} changed {change:+.1f}% year over year (below the "
                           f"{MATERIAL_CHANGE_PCT:.0f}% review threshold)."),
                   values={"concept": cur.concept, "current": cur.val, "prior": pri.val, "change_pct": round(change, 2)},
                   reg_query=q)


def check_revenue_change(fb: FactBook) -> Finding:
    return _yoy(fb, "YOY_REVENUE", "Year-over-year revenue change", REVENUE, "revenue")


def check_net_income_change(fb: FactBook) -> Finding:
    return _yoy(fb, "YOY_NET_INCOME", "Year-over-year net income change", NET_INCOME, "net income")


def check_restatement(fb: FactBook, filings: list[Filing]) -> Finding:
    cid, title = "RESTATEMENT", "Prior-year figures match the previously filed 10-K"
    q = ("accounting restatement Rule 10D-1 correction of an error in previously issued financial statements "
         "material to the previously issued financial statements recast prior period")
    prev = [f for f in filings if f.form == "10-K" and FactBook._near(f.period_end, fb.prior_end, 14)]
    if not prev:
        return _na(cid, title, "No prior-year 10-K with XBRL data to compare against.", q)
    prev_accn = prev[-1].accn
    diffs, splits = {}, {}
    pairs = [(REVENUE, True), (NET_INCOME, True), (["Assets"], False), (EQUITY_TOTAL, False),
             (CFO, True), (["EarningsPerShareDiluted"], True)]
    for concepts, duration in pairs:
        now = fb.prior(concepts, duration)
        if not now:
            continue
        orig = fb.prior([now.concept], duration, accn=prev_accn)
        if not orig or orig.val == 0:
            continue
        gap = _pct(now.val, orig.val)
        if abs(gap) <= 0.5:
            continue
        entry = {"originally_reported": orig.val, "as_recast": now.val, "change_pct": round(gap, 2)}
        factor = _split_factor(orig.val, now.val) if now.unit.endswith("/shares") else None
        if factor:
            splits[now.concept] = entry | {"split_ratio": factor}
        else:
            diffs[now.concept] = entry
    if not diffs:
        detail = "Key prior-year figures match those in the prior-year 10-K."
        if splits:
            detail += " Per-share amounts were retroactively adjusted for a stock split (" + \
                      ", ".join(s["split_ratio"] for s in splits.values()) + "), which is not a restatement."
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO, detail=detail,
                       values={"prior_accession": prev_accn} | ({"split_adjusted": splits} if splits else {}),
                       reg_query=q)
    big = any(abs(v["change_pct"]) >= 5 for v in diffs.values())
    return Finding(check_id=cid, title=title, status=Status.WARN,
                   severity=Severity.HIGH if big else Severity.MEDIUM,
                   detail=(f"{len(diffs)} prior-year figure(s) differ from the prior-year 10-K, indicating a "
                           "restatement, reclassification or discontinued-operations recast that should be disclosed."),
                   values={"prior_accession": prev_accn, "differences": diffs}
                          | ({"split_adjusted": splits} if splits else {}), reg_query=q)


def _split_factor(original: float, recast: float) -> str | None:
    """'1-for-8 reverse split' style label when two per-share values differ by a split ratio."""
    if original == 0 or recast == 0 or (original > 0) != (recast > 0):
        return None
    ratio = recast / original
    for f in SPLIT_FACTORS:
        if abs(ratio - f) / f <= 0.02:
            return f"1-for-{f} reverse split"
        if abs(ratio - 1 / f) * f <= 0.02:
            return f"{f}-for-1 split"
    return None


def check_timeliness(fb: FactBook) -> Finding:
    cid, title = "FILING_TIMELINESS", "10-K filed within the deadline for the filer's category"
    q = ("annual report Form 10-K filing deadline days after fiscal year end Rule 12b-25 notification of late "
         "filing Rule 12b-2 large accelerated filer accelerated filer public float")
    floats = [f for f in fb.facts.get("EntityPublicFloat", []) if f.accn == fb.filing.accn]
    pf = floats[0].val if floats else None
    if pf is None:
        category, deadline = "unknown (public float not tagged; non-accelerated deadline assumed)", 90
    elif pf >= 700_000_000:
        category, deadline = "large accelerated filer", 60
    elif pf >= 75_000_000:
        category, deadline = "accelerated filer", 75
    else:
        category, deadline = "non-accelerated filer", 90
    days = (_d(fb.filing.filed) - fb.current_end).days
    if days <= deadline:
        status, sev = Status.PASS, Severity.INFO
        detail = f"Filed {days} days after fiscal year end; deadline for a {category} is {deadline} days."
    elif days <= deadline + 15:
        status, sev = Status.WARN, Severity.MEDIUM
        detail = (f"Filed {days} days after year end, past the {deadline}-day deadline for a {category} but within "
                  "the 15-day Rule 12b-25 extension window.")
    else:
        status, sev = Status.FAIL, Severity.HIGH
        detail = f"Filed {days} days after year end; deadline for a {category} is {deadline} days."
    return Finding(check_id=cid, title=title, status=status, severity=sev, detail=detail,
                   values={"days_to_file": days, "deadline_days": deadline, "public_float": pf,
                           "filer_category": category, "filed": fb.filing.filed, "period_end": fb.filing.period_end},
                   reg_query=q)


def check_liquidity(fb: FactBook) -> Finding:
    cid, title = "LIQUIDITY", "Liquidity and going-concern indicators"
    q = ("liquidity and capital resources known trends demands commitments events uncertainties "
         "going concern substantial doubt Item 303(b)(1)")
    eq = fb.cur(EQUITY_TOTAL, duration=False)
    ca = fb.cur(["AssetsCurrent"], duration=False)
    cl = fb.cur(["LiabilitiesCurrent"], duration=False)
    cfo = fb.cur(CFO)
    if not eq or not cfo:
        return _na(cid, title, "Equity or operating cash flow not tagged.", q)
    ratio = round(ca.val / cl.val, 3) if ca and cl and cl.val else None
    flags = []
    if eq.val < 0:
        flags.append("negative stockholders' equity")
    if cfo.val < 0:
        flags.append("negative operating cash flow")
    if ratio is not None and ratio < 1.0:
        flags.append(f"current ratio {ratio:.2f} below 1.0")
    values = {eq.concept: eq.val, "CFO": cfo.val, "current_ratio": ratio}
    if not flags:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail="Positive equity and operating cash flow; no going-concern indicators.", values=values,
                       reg_query=q)
    severe = cfo.val < 0 and (eq.val < 0 or (ratio is not None and ratio < 1.0))
    return Finding(check_id=cid, title=title, status=Status.WARN,
                   severity=Severity.HIGH if severe else Severity.LOW,
                   detail="Indicators present: " + "; ".join(flags) + ". Liquidity discussion in MD&A should address these.",
                   values=values, reg_query=q)


def check_conflicting_facts(fb: FactBook) -> Finding:
    cid, title = "XBRL_CONSISTENCY", "No conflicting values tagged for the same fact"
    q = ("Rule 405 of Regulation S-T interactive data file XBRL financial statements tagged values "
         "exhibit 101 Inline XBRL")
    concepts = ["Assets", "Liabilities", "LiabilitiesAndStockholdersEquity", "NetIncomeLoss", "EarningsPerShareDiluted",
                *REVENUE, *EQUITY_TOTAL, *CFO]
    conflicts = {}
    for c in concepts:
        for a, b in fb.conflicting(c):
            conflicts[c] = {"period_end": a.end, "values": [a.val, b.val]}
    if not conflicts:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail="Each key fact has a single value per period in this filing.", reg_query=q)
    return Finding(check_id=cid, title=title, status=Status.FAIL, severity=Severity.MEDIUM,
                   detail=f"{len(conflicts)} key concept(s) carry conflicting values for the same period.",
                   values={"conflicts": conflicts}, reg_query=q)


CHECKS: list[Callable[[FactBook], Finding]] = [
    check_balance_sheet_identity, check_balance_sheet_components, check_gross_profit, check_eps,
    check_cash_flow, check_revenue_change, check_net_income_change, check_timeliness, check_liquidity,
    check_conflicting_facts,
]


def run_all(company_facts: dict, fiscal_year: int | None) -> tuple[Filing, list[Finding]]:
    filings = annual_filings(company_facts)
    filing = select_filing(company_facts, fiscal_year)
    fb = FactBook(company_facts, filing)
    findings = [chk(fb) for chk in CHECKS]
    findings.insert(7, check_restatement(fb, filings))
    return filing, findings


def industry_for_sic(sic: str | None) -> str:
    """Map an SEC SIC code to the industry-specific regulation articles that apply."""
    if not sic or not sic.isdigit():
        return "general"
    code = int(sic)
    if 6020 <= code <= 6036 or code in (6111, 6199):
        return "bank"
    if 6311 <= code <= 6411:
        return "insurance"
    if 1310 <= code <= 1389 or code == 2911:
        return "oil_gas"
    if 1000 <= code <= 1499:
        return "mining"
    if code == 6726:
        return "investment_company"
    return "general"


def company_context(ticker: str, cik: str, company_facts: dict, filing: Filing,
                    sic: str | None = None, sic_description: str | None = None) -> CompanyContext:
    accn_path = filing.accn.replace("-", "")
    return CompanyContext(
        ticker=ticker, cik=cik, name=company_facts.get("entityName", ticker), fiscal_year=filing.fy,
        period_end=filing.period_end, form=filing.form, accession=filing.accn, filed=filing.filed,
        source_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn_path}/",
        sic=sic, sic_description=sic_description, industry=industry_for_sic(sic))
