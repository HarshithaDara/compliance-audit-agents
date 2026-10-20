"""Cross-checks over the facts extracted from an income-tax / GST evidence bundle.

Each check compares two or more independent sources (the return, the department's AIS/TIS, GST
returns, invoices, bank statements, certificates) or tests a statutory condition. Every finding
carries Evidence entries pointing at the pages its numbers came from. A check whose inputs are
missing from the bundle is not_applicable and names what was missing.

Statutory thresholds encoded here are for the assessment years they state; they are the
Income-tax Act, 1961 rules (old regime) as they stood for AY 2023-24 unless noted.
"""
from __future__ import annotations

import re
from collections import defaultdict

from common.schemas import Evidence, Finding, Severity, Status

from agents.document.parsers import Fact, Facts, fy_of, in_fy

LAKH = 100_000
CRORE = 10_000_000


def tolerance(amount: float) -> float:
    return max(1000.0, abs(amount) * 0.005)


def inr(v: float) -> str:
    """Indian digit grouping: 1234567 -> '12,34,567'."""
    neg, v = v < 0, abs(v)
    whole, frac = divmod(round(v, 2), 1)
    s = str(int(whole))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        s = f"{head},{tail}"
    out = f"₹{s}" + (f".{round(frac * 100):02d}" if frac >= 0.005 else "")
    return f"-{out}" if neg else out


def ev(f: Fact | None, label: str, value=None) -> list[Evidence]:
    if f is None:
        return []
    return [Evidence(page=f.page, printed_page=f.printed, label=label, value=f.value if value is None else value,
                     quote=f.quote)]


def na(check_id: str, title: str, missing: str, reg_query: str) -> Finding:
    return Finding(check_id=check_id, title=title, status=Status.NOT_APPLICABLE, severity=Severity.INFO,
                   detail=f"Not tested: {missing} not found in the document.", reg_query=reg_query)


# ------------------------------------------------------------------ fact helpers

def ais_sections(facts: Facts, code_prefix: str) -> list[Fact]:
    return [f for f in facts.all("ais.info") if f.value["code"].startswith(code_prefix)]


def ais_active_total(f: Fact, field: str = "amount") -> float:
    rows = [r for r in f.value["rows"] if r["status"] == "Active"]
    return sum(r[field] for r in rows) if rows else (f.value["amount"] if field == "amount" else 0)


def tis(facts: Facts, category: str) -> Fact | None:
    return next((f for f in facts.all("tis.category") if f.value["category"].lower() == category.lower()), None)


def assessment_year(facts: Facts) -> str | None:
    return facts.value("itr.assessment_year") or facts.value("ais.assessment_year")


# ------------------------------------------------------------------ checks

def check_turnover_ais(facts: Facts) -> Finding:
    cid, title = "TURNOVER_AIS_VS_ITR", "Business receipts in AIS/TIS vs gross receipts in the return"
    q = "section 44AD gross receipts turnover reported AIS TDS 194C 194H business receipts return of income"
    itr = facts.first("itr.gross_receipts_44ad")
    business = tis(facts, "Business receipts")
    sections = ais_sections(facts, "TDS-194C") + ais_sections(facts, "TDS-194H")
    if itr is None or (business is None and not sections):
        return na(cid, title, "the return's gross receipts or the AIS/TIS business receipts", q)
    if business is not None:
        ais_total, src = business.value["accepted"], business
        evidence = ev(business, "TIS business receipts (accepted)", ais_total)
    else:
        ais_total = sum(ais_active_total(f) for f in sections)
        src = sections[0]
        evidence = [e for f in sections for e in ev(f, f"AIS {f.value['code']} (active rows)", ais_active_total(f))]
    evidence += ev(itr, "ITR gross receipts (44AD)")
    gap = ais_total - itr.value
    values = {"ais_business_receipts": ais_total, "itr_gross_receipts": itr.value, "difference": gap}
    if abs(gap) <= tolerance(itr.value):
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"AIS/TIS business receipts {inr(ais_total)} agree with the {inr(itr.value)} declared "
                              f"(difference {inr(gap)}).", values=values, reg_query=q, evidence=evidence)
    sev = Severity.HIGH if gap > 0 else Severity.MEDIUM
    return Finding(check_id=cid, title=title, status=Status.FAIL if gap > 0 else Status.WARN, severity=sev,
                   detail=f"The department's AIS/TIS shows business receipts of {inr(ais_total)} but the return declares "
                          f"{inr(itr.value)}: {'under' if gap > 0 else 'over'}-reporting of {inr(abs(gap))} against the "
                          f"third-party data (source page {src.page}).", values=values, reg_query=q, evidence=evidence)


def _service_month_turnover(facts: Facts, fy: tuple[int, int]) -> float | None:
    invoices = facts.all("invoice")
    if not invoices or not any(i.value["lines"] for i in invoices):
        return None
    return round(sum(ln["taxable"] for i in invoices for ln in i.value["lines"] if in_fy(ln["service_month"], fy)), 2)


def check_turnover_gst(facts: Facts) -> Finding:
    cid, title = "TURNOVER_GST_VS_ITR", "GST turnover (GSTR-3B) vs gross receipts in the return"
    q = "GSTR-3B outward taxable supplies turnover mismatch income tax return gross receipts section 39 CGST"
    itr = facts.first("itr.gross_receipts_44ad")
    monthly = facts.all("gstr3b.outward")
    ais_gst = next((f for f in ais_sections(facts, "EXC-GSTR3B")), None) or tis(facts, "GST turnover")
    if itr is None or (not monthly and ais_gst is None):
        return na(cid, title, "the return's gross receipts or GSTR-3B / AIS GST turnover", q)
    evidence = ev(itr, "ITR gross receipts (44AD)")
    if monthly:
        gst = round(sum(f.value["taxable"] for f in monthly), 2)
        evidence += [Evidence(page=f.page, printed_page=f.printed, label=f"GSTR-3B {f.value['period']} 3.1(a)",
                              value=f.value["taxable"], quote=f.quote) for f in monthly]
        source = f"GSTR-3B returns for {len(monthly)} months"
    else:
        gst = ais_gst.value.get("amount", ais_gst.value.get("accepted"))
        evidence += ev(ais_gst, "AIS GST turnover (GSTR-3B)", gst)
        source = "the AIS GST turnover"
    gap = itr.value - gst
    values = {"gst_turnover": gst, "itr_gross_receipts": itr.value, "difference": round(gap, 2), "gst_source": source}
    if abs(gap) <= tolerance(itr.value):
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"GST turnover {inr(gst)} ({source}) agrees with the {inr(itr.value)} declared.",
                       values=values, reg_query=q, evidence=evidence)
    fy = fy_of(assessment_year(facts))
    by_service = _service_month_turnover(facts, fy) if fy else None
    if by_service is not None:
        values["invoices_by_service_month"] = by_service
        values["service_month_difference"] = round(itr.value - by_service, 2)
        if abs(itr.value - by_service) <= tolerance(itr.value):
            return Finding(
                check_id=cid, title=title, status=Status.WARN, severity=Severity.LOW,
                detail=f"GST turnover {inr(gst)} ({source}) is {inr(abs(gap))} {'below' if gap > 0 else 'above'} the "
                       f"{inr(itr.value)} declared, but the tax invoices re-bucketed by the month the service was "
                       f"rendered total {inr(by_service)} for the year, within {inr(abs(itr.value - by_service))} of the return. The gap is a "
                       f"timing difference: GST is reported by invoice date, which runs about a month behind the "
                       f"service period. The submission should state this reconciliation.",
                values=values, reg_query=q, evidence=evidence)
    return Finding(check_id=cid, title=title, status=Status.WARN, severity=Severity.MEDIUM,
                   detail=f"GST turnover {inr(gst)} ({source}) differs from the {inr(itr.value)} declared by "
                          f"{inr(abs(gap))}, and no invoice-level reconciliation explains it.",
                   values=values, reg_query=q, evidence=evidence)


def check_gstr1_vs_3b(facts: Facts) -> Finding:
    cid, title = "GSTR1_VS_GSTR3B", "GSTR-1 outward supplies vs GSTR-3B, month by month"
    q = "GSTR-1 details of outward supplies GSTR-3B return mismatch section 37 section 39 CGST Act"
    g1 = {f.value["period"]: f for f in facts.all("gstr1.b2b")}
    g3 = {f.value["period"]: f for f in facts.all("gstr3b.outward")}
    common = sorted(set(g1) & set(g3))
    if not common:
        return na(cid, title, "matching GSTR-1 and GSTR-3B periods", q)
    diffs = {p: round(g1[p].value["taxable"] - g3[p].value["taxable"], 2) for p in common}
    bad = {p: d for p, d in diffs.items() if abs(d) > 1}
    evidence = [e for p in (bad or common[:1]) for e in ev(g1[p], f"GSTR-1 {p}", g1[p].value["taxable"])
                + ev(g3[p], f"GSTR-3B {p}", g3[p].value["taxable"])]
    missing = sorted(set(g1) ^ set(g3))
    values = {"months_compared": len(common), "mismatched_months": bad, "months_in_one_return_only": missing}
    if not bad and not missing:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"GSTR-1 and GSTR-3B taxable values agree in all {len(common)} months.",
                       values=values, reg_query=q, evidence=evidence)
    parts = [f"{p}: GSTR-1 exceeds GSTR-3B by {inr(d)}" if d > 0 else f"{p}: GSTR-3B exceeds GSTR-1 by {inr(-d)}"
             for p, d in bad.items()]
    if missing:
        parts.append(f"periods present in only one return: {', '.join(missing)}")
    return Finding(check_id=cid, title=title, status=Status.WARN, severity=Severity.MEDIUM,
                   detail="Outward supplies differ between the returns - " + "; ".join(parts) + ".",
                   values=values, reg_query=q, evidence=evidence)


def check_invoices_vs_gstr1(facts: Facts) -> Finding:
    cid, title = "INVOICES_VS_GSTR1", "Tax invoices vs GSTR-1 B2B supplies, by invoice month"
    q = "tax invoice issued section 31 CGST Act outward supplies furnished GSTR-1 section 37"
    invoices = facts.all("invoice")
    g1 = {f.value["period"]: f for f in facts.all("gstr1.b2b")}
    if not invoices or not g1:
        return na(cid, title, "tax invoices or GSTR-1 returns", q)
    by_month: dict[str, list[Fact]] = defaultdict(list)
    for i in invoices:
        by_month[i.value["date"][:7]].append(i)
    months = sorted(set(by_month) & set(g1))
    diffs = {m: round(sum(i.value["taxable"] for i in by_month[m]) - g1[m].value["taxable"], 2) for m in months}
    bad = {m: d for m, d in diffs.items() if abs(d) > 1}
    no_invoices = sorted(m for m in g1 if m not in by_month and g1[m].value["taxable"] > 0)
    values = {"invoices": len(invoices), "months_compared": len(months), "mismatched_months": bad,
              "gstr1_months_without_invoices_in_bundle": no_invoices}
    evidence = [e for m in (bad or months[:1]) for e in ev(by_month[m][0], f"invoice(s) dated {m}",
                                                         round(sum(i.value["taxable"] for i in by_month[m]), 2))
                + ev(g1[m], f"GSTR-1 {m}", g1[m].value["taxable"])]
    if not bad and not no_invoices:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"All {len(invoices)} invoices agree with GSTR-1 in each of {len(months)} months.",
                       values=values, reg_query=q, evidence=evidence)
    parts = [f"{m}: invoices differ from GSTR-1 by {inr(d)}" for m, d in bad.items()]
    if no_invoices:
        parts.append(f"GSTR-1 reports supplies for {', '.join(no_invoices)} but the bundle has no invoices dated "
                     f"in those months")
    sev = Severity.MEDIUM if bad else Severity.LOW
    return Finding(check_id=cid, title=title, status=Status.WARN, severity=sev,
                   detail="; ".join(parts) + ".", values=values, reg_query=q, evidence=evidence)


def _slab_tax_old_regime(total_income: float, age: int | None) -> float:
    exempt = 500_000 if age is not None and age >= 80 else 300_000 if age is not None and age >= 60 else 250_000
    tax = 0.0
    bands = [(exempt, 500_000, 0.05), (500_000, 1_000_000, 0.20), (1_000_000, float("inf"), 0.30)]
    for lo, hi, rate in bands:
        if total_income > lo:
            tax += (min(total_income, hi) - lo) * rate
    return round(tax)


def _rebate_87a(total_income: float, tax: float) -> float:
    return min(tax, 12_500) if total_income <= 500_000 else 0.0


def _age(facts: Facts) -> int | None:
    fy, by = fy_of(assessment_year(facts)), facts.value("taxpayer.birth_year")
    return fy[1] - by if fy and by else None


def check_other_income(facts: Facts) -> Finding:
    cid, title = "OTHER_INCOME_OMITTED", "Interest reported in AIS vs income from other sources in the return"
    q = "interest income savings bank deposit section 80TTA income from other sources AIS SFT-016 not reported"
    sft = ais_sections(facts, "SFT-016")
    sb = tis(facts, "Interest from savings bank")
    td = tis(facts, "Interest from deposit")
    declared = facts.first("itr.other_sources_income")
    if declared is None or (not sft and sb is None and td is None):
        return na(cid, title, "AIS interest information or the return's income from other sources", q)
    if sb is not None or td is not None:
        savings = sb.value["accepted"] if sb else 0
        deposits = td.value["accepted"] if td else 0
        evidence = ev(sb, "TIS interest from savings bank", savings) + ev(td, "TIS interest from deposits", deposits)
    else:
        savings = sum(f.value["amount"] for f in sft if "(SB)" in f.value["code"])
        deposits = sum(f.value["amount"] for f in sft if "(SB)" not in f.value["code"])
        evidence = [e for f in sft for e in ev(f, f"AIS {f.value['code']}", f.value["amount"])]
    evidence += ev(declared, "ITR income from other sources")
    interest = savings + deposits
    omitted = interest - declared.value
    values = {"ais_interest_savings": savings, "ais_interest_deposits": deposits,
              "itr_other_sources_income": declared.value, "unreported": omitted}
    if omitted <= 1000:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"Interest of {inr(interest)} in the AIS is covered by the {inr(declared.value)} "
                              f"declared under other sources.", values=values, reg_query=q, evidence=evidence)
    detail = (f"The AIS reports interest of {inr(interest)} (savings {inr(savings)}, deposits {inr(deposits)}) but the "
              f"return declares {inr(declared.value)} under income from other sources: {inr(omitted)} is unreported.")
    total = facts.first("itr.total_income")
    sev = Severity.MEDIUM
    if total is not None:
        deduction_80tta = min(savings, 10_000)
        revised = total.value + omitted - deduction_80tta
        age = _age(facts)
        before = _slab_tax_old_regime(total.value, age)
        after = _slab_tax_old_regime(revised, age)
        tax_before = (before - _rebate_87a(total.value, before)) * 1.04
        tax_after = (after - _rebate_87a(revised, after)) * 1.04
        effect = round(tax_after - tax_before)
        values.update({"revised_total_income": revised, "deduction_80tta": deduction_80tta, "tax_effect": effect})
        if effect <= 0:
            detail += (f" Including it (less the s.80TTA deduction of {inr(deduction_80tta)}) gives total income of "
                       f"{inr(revised)}, still within the s.87A rebate, so there is no tax effect - but the omission "
                       f"remains a reporting mismatch the department's systems will flag.")
        else:
            sev = Severity.HIGH
            detail += (f" Including it (less the s.80TTA deduction of {inr(deduction_80tta)}) raises total income to "
                       f"{inr(revised)} and tax by about {inr(effect)} (old regime, including cess).")
    return Finding(check_id=cid, title=title, status=Status.WARN, severity=sev, detail=detail,
                   values=values, reg_query=q, evidence=evidence)


def check_tds_credit(facts: Facts) -> Finding:
    cid, title = "TDS_CREDIT", "TDS claimed in the return vs TDS reported in AIS"
    q = "credit for tax deducted at source claimed Form 26AS AIS Form 16A section 199 TDS 194C 194H"
    claimed = facts.first("itr.tds_claimed_total")
    rows = facts.all("itr.tds_row")
    sections = [f for f in ais_sections(facts, "TDS-") if not f.value["code"].startswith("TDS-194N")]
    if claimed is None or not sections:
        return na(cid, title, "the return's TDS schedule or AIS TDS entries", q)
    ais_tds = {f.value["code"]: ais_active_total(f, "tds") for f in sections}
    total_ais = sum(ais_tds.values())
    evidence = ev(claimed, "TDS claimed in the return") + \
        [e for f in sections for e in ev(f, f"AIS {f.value['code']} TDS (active rows)", ais_tds[f.value["code"]])]
    gap = claimed.value - total_ais
    values = {"itr_tds_claimed": claimed.value, "ais_tds": ais_tds, "difference": gap,
              "itr_rows": [r.value for r in rows]}
    if abs(gap) <= 10:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"TDS claimed ({inr(claimed.value)}) agrees with the AIS ({inr(total_ais)}).",
                       values=values, reg_query=q, evidence=evidence)
    return Finding(check_id=cid, title=title, status=Status.FAIL if gap > 0 else Status.WARN,
                   severity=Severity.HIGH if gap > 0 else Severity.LOW,
                   detail=f"The return claims TDS of {inr(claimed.value)} but the AIS shows {inr(total_ais)} deducted: "
                          f"{'excess claim' if gap > 0 else 'unclaimed credit'} of {inr(abs(gap))}.",
                   values=values, reg_query=q, evidence=evidence)


def check_tds_head(facts: Facts) -> Finding:
    cid, title = "TDS_HEAD", "TDS credit booked under the head of income the receipt was offered in"
    q = "TDS credit claimed in the year income offered head of income section 199 rule 37BA"
    rows = facts.all("itr.tds_row")
    if not rows:
        return na(cid, title, "the return's TDS schedule", q)
    other_sources = facts.value("itr.other_sources_income")
    bad = [r for r in rows if r.value["head"] == "OS" and other_sources is not None and other_sources < r.value["gross"]]
    values = {"rows": [r.value for r in rows], "itr_other_sources_income": other_sources}
    evidence = [e for r in (bad or rows[:1]) for e in ev(r, f"TDS2 row ({r.value['head']})")]
    if not bad:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail="Each TDS credit is booked under a head that carries the corresponding income.",
                       values=values, reg_query=q, evidence=evidence)
    gross = sum(r.value["gross"] for r in bad)
    return Finding(check_id=cid, title=title, status=Status.WARN, severity=Severity.LOW,
                   detail=f"TDS on receipts of {inr(gross)} is claimed under 'income from other sources' (head OS), but "
                          f"the return shows {inr(other_sources or 0)} under that head; the receipts appear to have been "
                          f"offered as business income instead. The head in Schedule TDS2 should match where the income "
                          f"was offered.", values=values, reg_query=q, evidence=evidence)


COMMISSION_WORDS = re.compile(r"\bcommission\b|\bbrokerage\b|\bagency business\b|\bfranchise agent\b", re.I)


def check_presumptive_44ad(facts: Facts, submission_text: str = "") -> Finding:
    cid, title = "PRESUMPTIVE_44AD", "Eligibility and rate for presumptive taxation under section 44AD"
    q = ("section 44AD presumptive taxation eligible business turnover two crore six per cent eight per cent "
         "commission or brokerage agency business not apply")
    receipts = facts.first("itr.gross_receipts_44ad")
    income = facts.first("itr.presumptive_income_44ad")
    if receipts is None or income is None or receipts.value == 0:
        return na(cid, title, "a section 44AD computation in the return", q)
    digital = facts.value("itr.receipts_digital_44ad", receipts.value)
    other = facts.value("itr.receipts_other_44ad", 0)
    minimum = 0.06 * digital + 0.08 * other
    rate = income.value / receipts.value
    ay = assessment_year(facts) or ""
    limit = 2 * CRORE
    if ay >= "2024-25" and other <= 0.05 * receipts.value:
        limit = 3 * CRORE
    commission_rows = ais_sections(facts, "TDS-194H")
    commission = sum(ais_active_total(f) for f in commission_rows)
    mentions = len(COMMISSION_WORDS.findall(submission_text))
    values = {"gross_receipts": receipts.value, "presumptive_income": income.value, "declared_rate_pct": round(rate * 100, 2),
              "minimum_income": round(minimum), "turnover_limit": limit, "commission_receipts_194h": commission,
              "submission_mentions_commission": mentions}
    evidence = ev(receipts, "ITR gross receipts (44AD)") + ev(income, "ITR presumptive income (44AD)") + \
        [e for f in commission_rows for e in ev(f, "AIS 194H commission or brokerage", commission)]
    problems, sev = [], Severity.INFO
    if income.value + 1 < minimum:
        problems.append(f"declared income {inr(income.value)} is below the statutory minimum of {inr(round(minimum))} "
                        f"(6% of digital and 8% of other receipts)")
        sev = Severity.HIGH
    if receipts.value > limit:
        problems.append(f"turnover {inr(receipts.value)} exceeds the {inr(limit)} limit for AY {ay}")
        sev = Severity.HIGH
    if commission > 0 or mentions >= 2:
        share = f"{inr(commission)} of the receipts are reported by the payer under s.194H (commission or brokerage)" \
            if commission else "the written submission describes the receipts as commission"
        problems.append(f"{share}. Section 44AD(6) excludes a person earning income in the nature of commission or "
                        f"brokerage, and a person carrying on agency business, so eligibility for the presumptive "
                        f"scheme on those receipts is open to challenge")
        sev = Severity.HIGH if sev == Severity.HIGH else Severity.MEDIUM
    if not problems:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"Presumptive income {inr(income.value)} is {rate:.2%} of receipts {inr(receipts.value)}, "
                              f"above the statutory minimum, and turnover is within the {inr(limit)} limit.",
                       values=values, reg_query=q, evidence=evidence)
    return Finding(check_id=cid, title=title, status=Status.WARN, severity=sev,
                   detail=f"Declared presumptive income is {rate:.2%} of receipts (minimum {inr(round(minimum))} met: "
                          f"{'yes' if income.value + 1 >= minimum else 'no'}). " + "; ".join(problems) + ".",
                   values=values, reg_query=q, evidence=evidence)


def check_audit_44ab(facts: Facts) -> Finding:
    cid, title = "AUDIT_44AB", "Tax audit applicability under section 44AB"
    q = "section 44AB audit of accounts turnover exceeds one crore ten crore cash receipts five per cent 44AD"
    receipts = facts.first("itr.gross_receipts_44ad")
    if receipts is None:
        return na(cid, title, "the return's turnover", q)
    other = facts.value("itr.receipts_other_44ad", 0)
    threshold = 10 * CRORE if other <= 0.05 * receipts.value else 1 * CRORE
    values = {"turnover": receipts.value, "threshold": threshold}
    evidence = ev(receipts, "ITR gross receipts")
    if receipts.value <= threshold:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"Turnover {inr(receipts.value)} is below the {inr(threshold)} threshold and income is "
                              f"declared under s.44AD, so a tax audit is not required on turnover grounds.",
                       values=values, reg_query=q, evidence=evidence)
    return Finding(check_id=cid, title=title, status=Status.FAIL, severity=Severity.HIGH,
                   detail=f"Turnover {inr(receipts.value)} exceeds the s.44AB threshold of {inr(threshold)}; accounts "
                          f"must be audited and the report furnished.", values=values, reg_query=q, evidence=evidence)


def check_tax_computation(facts: Facts) -> Finding:
    cid, title = "TAX_COMPUTATION", "Tax on total income and section 87A rebate recomputed"
    q = "rebate section 87A total income does not exceed five lakh rupees tax slab rates individual"
    total = facts.first("itr.total_income") or facts.first("ack.total_income")
    tax = facts.first("itr.tax_normal_rates")
    rebate = facts.first("itr.rebate_87a")
    if total is None or tax is None:
        return na(cid, title, "the return's tax computation", q)
    if (facts.value("itr.new_regime") or "").lower() == "yes":
        return na(cid, title, "an old-regime computation (the return opts for the new regime)", q)
    age = _age(facts)
    expected = _slab_tax_old_regime(total.value, age)
    expected_rebate = _rebate_87a(total.value, expected)
    values = {"total_income": total.value, "tax_in_return": tax.value, "tax_recomputed": expected,
              "rebate_in_return": rebate.value if rebate else None, "rebate_recomputed": expected_rebate, "age": age}
    evidence = ev(total, "Total income") + ev(tax, "Tax at normal rates") + ev(rebate, "Rebate u/s 87A")
    ok = abs(tax.value - expected) <= 10 and (rebate is None or abs(rebate.value - expected_rebate) <= 10)
    if ok:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"Tax of {inr(expected)} on total income {inr(total.value)} and the s.87A rebate of "
                              f"{inr(expected_rebate)} agree with the return.", values=values, reg_query=q, evidence=evidence)
    return Finding(check_id=cid, title=title, status=Status.WARN, severity=Severity.MEDIUM,
                   detail=f"Recomputed tax {inr(expected)} and rebate {inr(expected_rebate)} on total income "
                          f"{inr(total.value)} do not match the return ({inr(tax.value)} / "
                          f"{inr(rebate.value if rebate else 0)}).", values=values, reg_query=q, evidence=evidence)


def check_late_filing(facts: Facts) -> Finding:
    cid, title = "LATE_FILING", "Return filed after the due date; fee under section 234F"
    q = "belated return section 139(4) fee for default in furnishing return section 234F five thousand one thousand"
    section = facts.first("itr.filed_section")
    if section is None:
        return na(cid, title, "the ITR acknowledgement", q)
    filed = facts.first("itr.filing_date")
    fee = facts.first("ack.interest_fee_payable") or facts.first("comp.fee_234f")
    total = facts.value("itr.total_income") or facts.value("ack.total_income")
    values = {"filed_under": section.value, "filing_date": filed.value if filed else None,
              "fee_paid_or_payable": fee.value if fee else None, "total_income": total}
    evidence = ev(section, "Filed under section") + ev(filed, "Filing date") + ev(fee, "Interest and fee payable")
    if section.value != "139(4)":
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"Return filed under s.{section.value}.", values=values, reg_query=q, evidence=evidence)
    expected = 1000 if total is not None and total <= 5 * LAKH else 5000
    values["expected_fee"] = expected
    fee_ok = fee is not None and fee.value >= expected
    return Finding(check_id=cid, title=title, status=Status.WARN, severity=Severity.LOW if fee_ok else Severity.MEDIUM,
                   detail=f"The return is a belated return under s.139(4)"
                          f"{' filed on ' + filed.value if filed else ''}. The s.234F fee is {inr(expected)} for total "
                          f"income of {inr(total or 0)}; "
                          f"{'the return shows ' + inr(fee.value) + ' paid/payable, which covers it' if fee_ok else 'the return does not show it paid'}. "
                          f"A belated return also loses the right to carry forward most losses.",
                   values=values, reg_query=q, evidence=evidence)


def check_cash_withdrawals(facts: Facts) -> Finding:
    cid, title = "CASH_WITHDRAWAL_194N", "Cash withdrawals above ₹1 crore (s.194N) and WLATMO exemption certificates"
    q = ("section 194N deduction of tax on cash withdrawal exceeding one crore white label automated teller machine "
         "operator franchise agent cash replenishment exemption")
    sections = ais_sections(facts, "TDS-194N")
    if not sections:
        return na(cid, title, "AIS cash-withdrawal (194N) entries", q)
    fy = fy_of(assessment_year(facts))
    monthly: dict[str, float] = defaultdict(float)
    tds = 0.0
    for f in sections:
        for r in f.value["rows"]:
            if r["status"] == "Active":
                monthly[r["date"][:7]] += r["amount"]
                tds += r["tds"]
    total = sum(monthly.values()) or sum(f.value["amount"] for f in sections)
    certs = [c for c in facts.all("cert.194n") if fy is None or in_fy(c.value["month"], fy)]
    cert_monthly: dict[str, float] = defaultdict(float)
    for c in certs:
        cert_monthly[c.value["month"]] += c.value["amount"]
    uncovered = sorted(m for m in monthly if m not in cert_monthly)
    # Coverage per account: the exemption is account by account, so a month with certificates for
    # some accounts can still have an account whose withdrawals are uncertified.
    by_account: dict[str, set[str]] = defaultdict(set)
    for c in certs:
        by_account[c.value["account"]].add(c.value["month"])
    account_gaps = {}
    for account, months in sorted(by_account.items()):
        missing = sorted(m for m in monthly if m >= min(months) and m not in months and m not in uncovered)
        if missing:
            account_gaps[account] = missing
    mismatched = {m: {"ais": monthly[m], "certificates": cert_monthly[m]} for m in sorted(cert_monthly)
                  if m in monthly and abs(monthly[m] - cert_monthly[m]) > tolerance(monthly[m])}
    values = {"ais_withdrawals": total, "tds_deducted": tds, "months_with_withdrawals": len(monthly),
              "certificates_in_fy": len(certs), "months_without_certificate": uncovered,
              "uncovered_amount": sum(monthly[m] for m in uncovered), "accounts_certified": sorted(by_account),
              "account_gaps": account_gaps, "certificate_vs_ais_mismatch": mismatched}
    evidence = [e for f in sections for e in ev(f, "AIS 194N cash withdrawals", f.value["amount"])] + \
        [e for c in certs[:12] for e in ev(c, f"WLATMO certificate {c.value['month']} ({c.value['account']})")]
    if total <= CRORE:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"Cash withdrawals of {inr(total)} do not exceed ₹1 crore.", values=values, reg_query=q,
                       evidence=evidence)
    detail = (f"The AIS reports {inr(total)} of cash withdrawals with TDS of {inr(tds)} deducted. Withdrawals above ₹1 "
              f"crore attract 2% TDS under s.194N unless the account is a WLATMO franchise agent's exclusive "
              f"replenishment account certified monthly by the operator.")
    if not certs:
        return Finding(check_id=cid, title=title, status=Status.FAIL, severity=Severity.HIGH,
                       detail=detail + " No monthly certificates were found in the document.", values=values,
                       reg_query=q, evidence=evidence)
    issues = []
    if uncovered:
        issues.append(f"no certificate for any account in {', '.join(uncovered)} "
                      f"({inr(values['uncovered_amount'])} withdrawn in those months)")
    for account, missing in account_gaps.items():
        issues.append(f"account {account} has certificates from {min(by_account[account])} but none for "
                      f"{', '.join(missing)}")
    if mismatched:
        issues.append("certificate totals differ from the AIS in " + ", ".join(
            f"{m} (certificates {inr(v['certificates'])} vs AIS {inr(v['ais'])})" for m, v in mismatched.items()))
    if not issues:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=detail + " Certificates cover every month and agree with the AIS.", values=values,
                       reg_query=q, evidence=evidence)
    return Finding(check_id=cid, title=title, status=Status.WARN, severity=Severity.MEDIUM,
                   detail=detail + " " + _sentence("; ".join(issues)), values=values, reg_query=q,
                   evidence=evidence)


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:] + "."


def check_bank_integrity(facts: Facts) -> Finding:
    cid, title = "BANK_STATEMENT_INTEGRITY", "Bank statement transactions add up to the statement summary"
    q = "books of account bank statement reconciliation section 44AA records"
    summary, txns = facts.first("bank.summary"), facts.first("bank.transactions")
    if summary is None or txns is None:
        return na(cid, title, "a bank statement with a summary", q)
    rows = txns.value["rows"]
    credits = round(sum(r["amount"] for r in rows if r["direction"] == "credit"), 2)
    debits = round(sum(r["amount"] for r in rows if r["direction"] == "debit"), 2)
    unknown = [r for r in rows if r["direction"] == "unknown"]
    s = summary.value
    arithmetic = round(s["opening"] + s["credits"] - s["debits"] - s["closing"], 2)
    values = {"transactions": len(rows), "parsed_credits": credits, "parsed_debits": debits, "summary": s,
              "unresolved_rows": len(unknown), "summary_arithmetic_gap": arithmetic}
    evidence = ev(summary, "Statement summary") + ev(txns, "Parsed transactions", len(rows))
    ok = abs(credits - s["credits"]) < 1 and abs(debits - s["debits"]) < 1 and abs(arithmetic) < 1 and not unknown
    if ok:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"{len(rows)} transactions on {s['bank']} {s['account']} reproduce the summary exactly "
                              f"(credits {inr(credits)}, debits {inr(debits)}).", values=values, reg_query=q,
                       evidence=evidence)
    return Finding(check_id=cid, title=title, status=Status.WARN, severity=Severity.MEDIUM,
                   detail=f"Parsed credits {inr(credits)} / debits {inr(debits)} do not reproduce the summary "
                          f"({inr(s['credits'])} / {inr(s['debits'])}); {len(unknown)} rows could not be resolved. "
                          f"Pages may be missing from the statement.", values=values, reg_query=q, evidence=evidence)


PAYER_RE = re.compile(r"(?!)")  # no payer named in the AIS: every credit is "other"
NON_RECEIPT_RE = re.compile(r"REVERSAL|REFUND|INTEREST|INT\.PD|CASHBACK", re.I)
CASH_RE = re.compile(r"\bCASH DEPOSIT\b|\bBY CASH\b|\bCASH DEP\b(?!.*CHGS)", re.I)


def _counterparty(narration: str) -> str:
    """NEFT/RTGS/IMPS narrations put the remitter third: 'RTGS CR-<IFSC>-<REMITTER>-...'."""
    parts = narration.split("-")
    if len(parts) >= 3 and re.match(r"^(NEFT|RTGS|IMPS)", parts[0].strip(), re.I):
        return parts[2].strip()[:40]
    return narration[:40]


PAYER_SOURCE = re.compile(r"\(Section \w+\)\s+(.+?)\s+\([A-Z0-9.]{10,}\)$")


def declared_payers(facts: Facts) -> re.Pattern:
    """The payers named in the AIS as deducting TDS on the receipts (194C/194H/194J ...), matched in
    bank narrations by the first two words of their name."""
    names = []
    for f in ais_sections(facts, "TDS-"):
        if f.value["code"].startswith("TDS-194N"):
            continue
        m = PAYER_SOURCE.search(f.value["description"])
        if m:
            names.append(r"\s+".join(map(re.escape, m.group(1).split()[:2])))
    return re.compile("|".join(dict.fromkeys(names)), re.I) if names else PAYER_RE


def check_bank_third_party(facts: Facts, declared_payer: re.Pattern | None = None) -> Finding:
    cid, title = "BANK_THIRD_PARTY_CREDITS", "Bank credits from parties other than the declared payer"
    q = "cash credits unexplained section 68 sum credited in books nature and source explanation"
    txns = facts.first("bank.transactions")
    if txns is None:
        return na(cid, title, "a bank statement", q)
    declared_payer = declared_payer or declared_payers(facts)
    all_rows = txns.value["rows"]
    rows = [r for r in all_rows if r["direction"] == "credit"]
    reversed_debits = [r for r in all_rows if r["direction"] == "debit" and REVERSAL_DEBIT_RE.search(r["narration"])]
    name_tokens = {t for t in (facts.value("itr.name") or "").upper().split() if len(t) >= 3}
    classes: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        classes[classify_credit(r, declared_payer, name_tokens, reversed_debits)].append(r)
    flaggable = [r for c in ("business", "individual", "related party") for r in classes[c]]
    large = sorted([r for r in flaggable if r["amount"] >= 50_000], key=lambda r: -r["amount"])
    cash = classes["cash deposit"]
    total = lambda rs: round(sum(r["amount"] for r in rs), 2)  # noqa: E731
    unexplained = total(large) + (total(cash) if total(cash) >= 50_000 else 0)
    values = {"credits_total": total(rows), "from_declared_payer": total(classes["declared payer"]),
              "by_class": {c: {"count": len(rs), "total": total(rs)} for c, rs in sorted(classes.items())},
              "cash_deposits": total(cash), "cash_deposit_count": len(cash),
              "excluded_not_receipts": total(classes["reversal / provisional"]) + total(classes["self transfer"]),
              "large_other_credits": [{"date": r["date"], "amount": r["amount"], "from": _counterparty(r["narration"]),
                                       "class": classify_credit(r, declared_payer, name_tokens, reversed_debits),
                                       "page": r["page"]} for r in large[:15]],
              "unexplained_total": unexplained, "confirmations_in_bundle": False}
    evidence = [Evidence(page=r["page"], label=f"credit {r['date']} from {_counterparty(r['narration'])}",
                         value=r["amount"], quote=r["narration"][:160]) for r in large[:8]]
    if cash:
        evidence.append(Evidence(page=cash[0]["page"], label=f"{len(cash)} cash deposits", value=values["cash_deposits"],
                                 quote=cash[0]["narration"][:160]))
    if not large and values["cash_deposits"] < 50_000:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"Credits come from the declared payer ({inr(values['from_declared_payer'])}) or are small.",
                       values=values, reg_query=q, evidence=evidence)
    parts = []
    for cls, label in (("business", "businesses"), ("individual", "other individuals"),
                       ("related party", "persons sharing the taxpayer's name (possible relatives)")):
        big = [r for r in large if r in classes[cls]]
        if big:
            top = big[0]
            parts.append(f"{len(big)} credit(s) of ₹50,000 or more from {label} totalling {inr(total(big))} "
                         f"(largest {inr(top['amount'])} from {_counterparty(top['narration'])} on {top['date']}, "
                         f"page {top['page']})")
    if values["cash_deposits"] >= 50_000:
        parts.append(f"{len(cash)} cash deposits totalling {inr(values['cash_deposits'])}")
    excluded = values["excluded_not_receipts"]
    return Finding(check_id=cid, title=title, status=Status.WARN, severity=Severity.MEDIUM,
                   detail=f"Of {inr(values['credits_total'])} credited, {inr(values['from_declared_payer'])} is from the "
                          f"declared payer" + (f" and {inr(excluded)} are reversals, provisional credits or self "
                                               f"transfers (not receipts)" if excluded else "") +
                          ". The rest includes " + "; ".join(parts) + ". No confirmations, ledger extracts or the payers' "
                          "documents are in the bundle, so each is explained by assertion at most; under s.68 the "
                          "nature and source of each credit must be shown.",
                   values=values, reg_query=q, evidence=evidence)


REVERSAL_DEBIT_RE = re.compile(r"(?i)\bTEMP\s*CR\s*REVERSAL\b|\bREVERSAL\b")
NOT_RECEIPT_RE = re.compile(r"(?i)\bPROV\s*CR\b|\bTEMP\s*CR\b|^REV[-_ ]|\bREVERSAL\b|\bRETURN(?:ED)?\b|\bREFUND\b|"
                            r"\bINT\.?\s*PD\b|\bINTEREST\b|\bCASHBACK\b")
BUSINESS_RE = re.compile(r"(?i)\b(?:ENTERPRISES?|TRADERS?|TRADING|LTD|LIMITED|PVT|AGENC(?:Y|IES)|INDUSTRIES|STORES?|"
                         r"CORPORATION|COMPANY|CO\.?|LLP|SOLUTIONS|SERVICES)\b")


def classify_credit(r: dict, payer: re.Pattern, name_tokens: set[str], reversed_debits: list[dict]) -> str:
    """Bank credits are not all receipts: reversals and provisional credits undone later, transfers
    from the taxpayer's own accounts, relatives, businesses and cash deposits need different treatment."""
    n = r["narration"]
    if NOT_RECEIPT_RE.search(n) or any(abs(d["amount"] - r["amount"]) < 0.01 and d["date"] >= r["date"]
                                       for d in reversed_debits):
        return "reversal / provisional"
    if payer.search(n):
        return "declared payer"
    if CASH_RE.search(n):
        return "cash deposit"
    who = _counterparty(n).upper()
    tokens = {t for t in re.split(r"[^A-Z]+", who) if len(t) >= 3}
    if name_tokens and name_tokens <= tokens:
        return "self transfer"
    if BUSINESS_RE.search(who):
        return "business"
    if name_tokens & tokens:
        return "related party"
    return "individual"


def run_all(facts: Facts, submission_text: str = "") -> list[Finding]:
    return [
        check_turnover_ais(facts),
        check_turnover_gst(facts),
        check_gstr1_vs_3b(facts),
        check_invoices_vs_gstr1(facts),
        check_other_income(facts),
        check_tds_credit(facts),
        check_tds_head(facts),
        check_presumptive_44ad(facts, submission_text),
        check_audit_44ab(facts),
        check_tax_computation(facts),
        check_late_filing(facts),
        check_cash_withdrawals(facts),
        check_bank_integrity(facts),
        check_bank_third_party(facts),
    ]
