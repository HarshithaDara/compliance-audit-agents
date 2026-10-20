"""Case-level review: what the bundle is for, and how each fact bears on the dispute.

A remand or appeal bundle exists because an officer questioned (or added to) the returned income.
These checks read the case papers, namely the notice, the order under dispute, the taxpayer's
evidence index and written submission. They test what an officer would test:
  * was everything the notice asked for actually furnished?
  * which additions were made, and do the officer's figures agree with the documents?
  * do the taxpayer's claims have evidence in the bundle, or are they only asserted?
  * is the year consistent with the years before and after?
Every finding then carries the amount at stake and whether it helps or hurts the taxpayer.
"""
from __future__ import annotations

import re

from common.schemas import Evidence, Finding, Severity, Status

from agents.document.checks import CRORE, LAKH, ev, inr, na, tolerance
from agents.document.parsers import Facts, fy_of, in_fy
from agents.document.pdftext import Page

SUPPORTS, WEAKENS, NEUTRAL = "supports the taxpayer", "weakens the taxpayer's case", "neutral"


def _case_ay(facts: Facts) -> str | None:
    notice = facts.first("case.notice")
    return (notice.value.get("assessment_year") if notice else None) or facts.value("itr.assessment_year") \
        or facts.value("ais.assessment_year")


def _orders(facts: Facts, same_year: bool) -> list:
    ay = _case_ay(facts)
    return [o for o in facts.all("order") if (o.value["assessment_year"] == ay) == same_year]


def check_case_context(facts: Facts) -> Finding:
    cid, title = "CASE_CONTEXT", "What this bundle is for, and whether the order under dispute is in it"
    q = "assessment order addition section 143(3) section 144B appeal remand report"
    notice, ack = facts.first("case.notice"), facts.first("case.response_ack")
    ay = _case_ay(facts)
    proceeding = notice.value["proceeding"] if notice else None
    same, other = _orders(facts, True), _orders(facts, False)
    values = {"proceeding": proceeding, "assessment_year": ay,
              "order_under_dispute_in_bundle": bool(same),
              "other_year_orders": [o.value["assessment_year"] for o in other]}
    evidence = ev(notice, "Notice / letter") + ev(ack, "Response acknowledgement") + \
        [e for o in same + other for e in ev(o, f"Assessment order AY {o.value['assessment_year']}", None)]
    if proceeding is None and not same:
        return Finding(check_id=cid, title=title, status=Status.NOT_APPLICABLE, severity=Severity.INFO,
                       detail="No notice, letter or assessment order for the year was found, so the bundle is reviewed "
                              "as a return with its supporting documents.", values=values, reg_query=q, evidence=evidence)
    kind = {"remand": "a remand-report proceeding (the appellate authority asked the officer to examine "
                      "additional evidence)", "appeal": "an appeal", "show_cause": "a response to a show-cause notice",
            "reassessment": "a reassessment", "scrutiny": "a scrutiny assessment"}.get(proceeding, "a proceeding")
    if same:
        o = same[0].value
        added = sum(a["amount"] for a in o["additions"])
        values.update({"additions": o["additions"], "additions_total": added, "assessed_income": o["assessed_income"],
                       "returned_income": o["returned_income"], "amount_at_stake": added})
        if o["no_variation"]:
            return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                           detail=f"The bundle is {kind} for AY {ay}. The order for the year (pages "
                                  f"{o['pages'][0]}-{o['pages'][-1]}) accepted the returned income without variation.",
                           values=values, reg_query=q, evidence=evidence)
        lines = "; ".join(f"{inr(a['amount'])}{' u/s ' + a['section'] if a['section'] else ''} ({a['description'][:60]})"
                          for a in o["additions"]) or "amounts not itemised"
        return Finding(check_id=cid, title=title, status=Status.WARN,
                       severity=Severity.HIGH if added >= 10 * LAKH else Severity.MEDIUM,
                       detail=f"The bundle is {kind} for AY {ay}. The order under dispute adds {inr(added)} to the returned "
                              f"income of {inr(o['returned_income'] or 0)}: {lines}. Each finding below is read against "
                              f"these additions.", values=values, reg_query=q, evidence=evidence)
    detail = (f"The bundle is {kind} for AY {ay}"
              + (f" (letter dated {notice.value['date']})" if notice and notice.value.get("date") else "")
              + ". The assessment order under dispute for that year is not in the bundle, so its additions and the "
                "officer's figures cannot be tested here.")
    if other:
        detail += " An order for " + ", ".join(f"AY {o.value['assessment_year']}" for o in other) + \
                  " is included as supporting material."
    detail += " Add the order (and the appeal memo) to the upload to have each addition reconciled."
    return Finding(check_id=cid, title=title, status=Status.WARN, severity=Severity.MEDIUM, detail=detail,
                   values=values, reg_query=q, evidence=evidence)


# What a notice may ask for, and how to recognise it in the bundle: (label, request pattern, page types or text pattern)
REQUEST_KINDS = [
    ("ledger account extracts", r"(?i)ledger", None, r"(?i)ledger\s*(?:account|a/c)|account\s*ledger"),
    ("confirmations from the parties", r"(?i)confirm", None, r"(?i)confirmation\s*(?:letter|of\s*account|of\s*balance)"),
    ("reasons for admitting additional evidence", r"(?i)reasons?.*(?:accept|admi)", {"submission"},
     r"(?i)sufficient\s*cause|reason\s*for\s*furnishing"),
    ("the documents listed as additional evidence", r"(?i)(?:additional\s*evidence|documents\s*listed)", {"annexure_index"}, None),
    ("bank statements", r"(?i)bank\s*statement", {"bank_statement"}, None),
    ("tax invoices", r"(?i)invoice", {"invoice"}, None),
    ("agreements", r"(?i)agreement", {"agreement"}, None),
    ("books of account", r"(?i)books\s*of\s*account|cash\s*book|day\s*book", None, r"(?i)cash\s*book|day\s*book|ledger"),
]


def check_notice_compliance(facts: Facts, pages: list[Page]) -> Finding:
    cid, title = "NOTICE_COMPLIANCE", "Everything the notice asked for is in the response"
    q = "Rule 46A production of additional evidence before appellate authority remand report"
    notice = facts.first("case.notice")
    if notice is None or not notice.value["requests"]:
        return na(cid, title, "a notice or letter listing what was called for", q)
    others = [p for p in pages if p.number != notice.page and p.doc_type != "notice"]
    results = []
    for request in notice.value["requests"]:
        kind = next((k for k in REQUEST_KINDS if re.search(k[1], request)), None)
        if kind is None:
            results.append({"request": request, "found": None, "pages": []})
            continue
        label, _, types, text = kind
        hits = [p.number for p in others if (types and p.doc_type in types) or (text and re.search(text, p.text))]
        results.append({"request": request, "what": label, "found": bool(hits), "pages": hits[:10]})
    missing = [r for r in results if r["found"] is False]
    unknown = [r for r in results if r["found"] is None]
    values = {"requests": results, "missing": [r["what"] for r in missing]}
    evidence = ev(notice, "What the notice asked for", None) + \
        [Evidence(page=r["pages"][0], label=f"furnished: {r['what']}", quote="") for r in results if r.get("pages")]
    if not missing:
        return Finding(check_id=cid, title=title, status=Status.PASS if not unknown else Status.WARN,
                       severity=Severity.INFO if not unknown else Severity.LOW,
                       detail=f"All {len(results) - len(unknown)} recognised requests in the notice are answered in the bundle"
                              + (f"; {len(unknown)} could not be matched automatically." if unknown else "."),
                       values=values, reg_query=q, evidence=evidence)
    return Finding(check_id=cid, title=title, status=Status.FAIL, severity=Severity.HIGH,
                   detail=f"The notice (page {notice.page}) asked for " + "; ".join(f"\"{r['request'][:120]}\"" for r in missing)
                          + ", but the bundle contains no " + " or ".join(r["what"] for r in missing) +
                          ". Not furnishing what the officer specifically called for is the weakest point of the response.",
                   values={**values, "bearing": WEAKENS}, reg_query=q, evidence=evidence)


AO_FIGURE = re.compile(r"(?i)Rs\.?\s*([\d,]{6,})(?:\.\d+)?\s*/?-?")


def check_ao_figures(facts: Facts, pages: list[Page]) -> Finding:
    """Every amount the order under dispute relies on should trace to a document in the bundle."""
    cid, title = "AO_FIGURE_RECONCILIATION", "Figures in the order under dispute agree with the source documents"
    q = "assessment order computation addition unexplained cash credit section 68 section 69A bank credits"
    same = [o for o in _orders(facts, True) if o.value["additions"]]
    if not same:
        return na(cid, title, "the assessment order under dispute (with additions)", q)
    o = same[0]
    known = {}
    summary = facts.first("bank.summary")
    if summary:
        s = summary.value
        known[f"credits in {s['bank']} {s['account']}"] = (s["credits"], summary)
        known[f"debits in {s['bank']} {s['account']}"] = (s["debits"], summary)
    for key, label in [("itr.gross_receipts_44ad", "gross receipts in the return"),
                       ("itr.total_income", "total income in the return")]:
        f = facts.first(key)
        if f:
            known[label] = (f.value, f)
    for f in facts.all("ais.info"):
        known[f"AIS {f.value['code']}"] = (f.value["amount"], f)
    for f in facts.all("tis.category"):
        known[f"TIS {f.value['category']}"] = (f.value["accepted"], f)
    text = "\n".join(p.text for p in pages if p.number in o.value["pages"])
    quoted = sorted({float(m.group(1).replace(",", "")) for m in AO_FIGURE.finditer(text)} - {o.value["returned_income"] or -1})
    matched, unmatched = [], []
    for amount in quoted:
        hit = next((label for label, (v, _) in known.items() if abs(v - amount) <= tolerance(v)), None)
        (matched if hit else unmatched).append({"amount": amount, "matches": hit})
    receipts = facts.value("itr.gross_receipts_44ad")
    overlap = [a for a in o.value["additions"] if re.search(r"(?i)credit|deposit|receipt", a["description"])]
    values = {"figures_in_order": len(quoted), "matched": matched, "not_traceable": unmatched,
              "additions": o.value["additions"], "amount_at_stake": sum(a["amount"] for a in o.value["additions"])}
    evidence = ev(o, f"Assessment order AY {o.value['assessment_year']}", None) + \
        [e for label, (v, f) in known.items() if any(m["matches"] == label for m in matched) for e in ev(f, label, v)]
    issues = []
    if unmatched:
        issues.append(f"{len(unmatched)} figure(s) in the order match no document in the bundle: "
                      + ", ".join(inr(u["amount"]) for u in unmatched[:6]))
    if overlap and receipts and o.value["returned_income"]:
        issues.append(f"the order keeps the returned income and also adds {inr(sum(a['amount'] for a in overlap))} on "
                      f"bank credits or receipts; the {inr(receipts)} of receipts already offered are part of those "
                      f"credits, so the addition double counts unless it excludes them")
    if not issues:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"All {len(quoted)} amounts in the order trace to documents in the bundle.",
                       values=values, reg_query=q, evidence=evidence)
    return Finding(check_id=cid, title=title, status=Status.WARN, severity=Severity.HIGH,
                   detail=_sentence("; ".join(issues)), values={**values, "bearing": SUPPORTS}, reg_query=q,
                   evidence=evidence)


def check_year_consistency(facts: Facts) -> Finding:
    cid, title = "YEAR_CONSISTENCY", "Consistency with the orders and returns of other years"
    q = "section 44AD presumptive income consistency subsequent assessment year accepted section 143(3)"
    other = _orders(facts, False)
    receipts, income = facts.first("itr.gross_receipts_44ad"), facts.first("itr.presumptive_income_44ad")
    if not other or receipts is None:
        return na(cid, title, "an order or return for another year", q)
    o = other[0]
    v = o.value
    rate = round(income.value / receipts.value * 100, 2) if income and receipts.value else None
    values = {"other_year": v["assessment_year"], "other_year_receipts": v["gross_receipts"],
              "other_year_rate_44ad": v["rate_44ad"], "this_year_receipts": receipts.value, "this_year_rate": rate,
              "other_year_accepted": v["no_variation"], "other_year_offers_other_sources": v["offers_other_sources"],
              "this_year_other_sources": facts.value("itr.other_sources_income")}
    evidence = ev(o, f"Order AY {v['assessment_year']}", None) + ev(receipts, "Receipts this year") + \
        ev(income, "Presumptive income this year")
    parts = []
    if v["no_variation"]:
        parts.append(f"the order for AY {v['assessment_year']} (u/s {v['section'] or '?'}) accepted the returned income "
                     f"after examining the same business"
                     + (f" (receipts {inr(v['gross_receipts'])}" + (f", income at {v['rate_44ad']}% under s.44AD"
                                                                    if v["rate_44ad"] else "") + ")"
                        if v["gross_receipts"] else "")
                     + (f", against {inr(receipts.value)} at {rate}% this year" if rate else ""))
    contrast = v["offers_other_sources"] and not facts.value("itr.other_sources_income")
    if contrast:
        parts.append(f"that year's return offered income from other sources, while this year's return shows none "
                     f"even though the AIS reports interest, which an officer will contrast")
    detail = _sentence("; ".join(parts)) + (" Each year is assessed independently, so the other year's acceptance "
                                            "supports the explanation of the business but does not bind the officer.")
    return Finding(check_id=cid, title=title, status=Status.WARN if contrast else Status.PASS,
                   severity=Severity.LOW if contrast else Severity.INFO, detail=detail,
                   values={**values, "bearing": SUPPORTS if not contrast else NEUTRAL}, reg_query=q, evidence=evidence)


def check_deduction_evidence(facts: Facts) -> Finding:
    cid, title = "DEDUCTION_EVIDENCE", "Evidence for the Chapter VI-A deductions claimed"
    q = "section 80C deduction tuition fees full-time education payment during the previous year"
    claimed = facts.first("itr.chapter_via")
    if claimed is None or not claimed.value:
        return na(cid, title, "Chapter VI-A deductions in the return", q)
    fy = fy_of(_case_ay(facts))
    receipts = facts.all("deduction.fee_receipt")

    def place(r):
        hits = [fy is not None and in_fy(d[:7], fy) for d in r.value["dates"]]
        return "in the year" if hits and all(hits) else "unclear date" if any(hits) else "outside the year"
    where = {id(r): place(r) for r in receipts}
    inside = [r for r in receipts if where[id(r)] == "in the year"]
    unclear = [r for r in receipts if where[id(r)] == "unclear date"]
    outside = [r for r in receipts if where[id(r)] == "outside the year"]
    supported = sum(r.value["amount"] for r in inside + unclear)
    gap = max(0.0, claimed.value - supported)
    values = {"claimed": claimed.value, "evidence_in_year": sum(r.value["amount"] for r in inside),
              "evidence_with_conflicting_dates": sum(r.value["amount"] for r in unclear), "unsupported": gap,
              "receipts_outside_year": [{"amount": r.value["amount"], "dates": r.value["dates"], "page": r.page}
                                        for r in outside], "amount_at_stake": gap}
    evidence = ev(claimed, "Chapter VI-A deductions claimed") + \
        [e for r in receipts for e in ev(r, f"fee receipt ({where[id(r)]})")]
    if unclear and gap <= 1000:
        return Finding(check_id=cid, title=title, status=Status.WARN, severity=Severity.LOW,
                       detail=f"Receipts support the {inr(claimed.value)} claimed only if "
                              + ", ".join(f"the {inr(r.value['amount'])} receipt on page {r.page}" for r in unclear)
                              + " is accepted as paid in the year: it shows dates both inside and outside it ("
                              + "; ".join(", ".join(r.value["dates"]) for r in unclear) + ").",
                       values={**values, "bearing": WEAKENS}, reg_query=q, evidence=evidence)
    if gap <= 1000:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"Receipts dated within the year support the {inr(claimed.value)} claimed.",
                       values=values, reg_query=q, evidence=evidence)
    detail = (f"The return claims {inr(claimed.value)} under Chapter VI-A; the receipts annexed for it support "
              f"{inr(supported)}, leaving {inr(gap)} without evidence in the bundle.")
    if unclear:
        detail += " That counts " + ", ".join(f"{inr(r.value['amount'])} (page {r.page})" for r in unclear) + \
                  ", whose receipt shows dates both inside and outside the year."
    if outside:
        detail += (" " + ", ".join(f"{inr(r.value['amount'])} (page {r.page}, dated {', '.join(r.value['dates']) or 'not legible'})"
                                   for r in outside) + " fall outside the year and cannot support it.")
    return Finding(check_id=cid, title=title, status=Status.WARN, severity=Severity.MEDIUM, detail=detail,
                   values={**values, "bearing": WEAKENS}, reg_query=q, evidence=evidence)


def check_evidence_relevance(facts: Facts) -> Finding:
    cid, title = "EVIDENCE_RELEVANCE", "Additional evidence relates to the year under review"
    q = "Rule 46A additional evidence relevant to the year under appeal"
    index = facts.first("case.evidence_index")
    fy = fy_of(_case_ay(facts))
    if index is None or fy is None:
        return na(cid, title, "an evidence index", q)
    import datetime as _dt
    end = _dt.date(fy[1], 3, 31)
    later = []
    for row in index.value:
        if row["dated"]:
            d, m, y = re.split(r"[./-]", row["dated"])
            when = _dt.date(int(y), int(m), int(d))
            if when > end:
                later.append({**row, "date": when.isoformat()})
    values = {"annexures": len(index.value), "dated_after_year_end": later}
    evidence = ev(index, "Evidence index", None)
    if not later:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"None of the {len(index.value)} dated annexures postdates the year.", values=values,
                       reg_query=q, evidence=evidence)
    return Finding(check_id=cid, title=title, status=Status.WARN, severity=Severity.LOW,
                   detail="Annexure " + ", ".join(f"{r['annexure']} ({r['description'][:70]}, dated {r['date']})" for r in later)
                          + f" postdates the end of the previous year ({end.isoformat()}); it can show the arrangement "
                            f"continued but cannot evidence the year's transactions.",
                   values={**values, "bearing": NEUTRAL}, reg_query=q, evidence=evidence)


# The taxpayer's claims: (label, pattern in the submission, how to test it)
def _accounts_in(text: str) -> set[str]:
    return {"XX" + m[-4:] for m in re.findall(r"\b\d{12,18}\b", text)}


def check_claims(facts: Facts, submission: list[Page], findings: dict[str, Finding]) -> Finding:
    cid, title = "SUBMISSION_CLAIMS", "Claims in the written submission: supported, asserted or contradicted"
    q = "Rule 46A additional evidence sufficient cause prevented from producing evidence"
    if not submission:
        return na(cid, title, "a written submission", q)
    text = " ".join(" ".join(p.text.split()) for p in submission)

    def page_of(pattern):
        return next((p for p in submission if re.search(pattern, " ".join(p.text.split()), re.I)), None)

    def status_of(check_id, good=(Status.PASS,)):
        f = findings.get(check_id)
        return None if f is None or f.status == Status.NOT_APPLICABLE else f.status in good

    statement_accounts = {f.value["account"] for f in facts.all("bank.summary")}
    claims = []

    def claim(label, pattern, verdict, why):
        p = page_of(pattern)
        if p is not None:
            m = re.search(r"[^.]*" + pattern + r"[^.]*\.?", " ".join(p.text.split()), re.I)
            claims.append({"claim": label, "page": p.number, "status": verdict, "why": why,
                           "quote": m.group(0).strip()[:220] if m else ""})

    medical_docs = any(re.search(r"(?i)hospital|discharge\s*summary|medical\s*certificate|prescription", f.quote)
                       for f in facts.items) or False
    claim("A medical exigency prevented production of the documents earlier (Rule 46A sufficient cause)",
          r"medical\s*exigency", "supported" if medical_docs else "asserted only",
          "no medical record is among the annexures" if not medical_docs else "medical records are annexed")
    other = _orders(facts, False)
    claim("The identical issue was examined and accepted in the subsequent year", r"subsequent\s*assessment\s*year",
          "supported" if any(o.value["no_variation"] for o in other) else "asserted only",
          "the AY " + other[0].value["assessment_year"] + " order in the bundle accepted the returned income"
          if other else "no order for another year is annexed")
    exclusive = page_of(r"maintained\s*exclusively|exclusively\s*for\s*the\s*purpose")
    if exclusive is not None:
        named = _accounts_in(" ".join(exclusive.text.split()))
        covered = named & statement_accounts
        third = findings.get("BANK_THIRD_PARTY_CREDITS")
        if covered and third is not None and third.status == Status.WARN:
            verdict, why = "contradicted", f"the statement of {', '.join(sorted(covered))} shows third-party credits"
        elif named and not covered:
            verdict, why = "asserted only", (f"the accounts named ({', '.join(sorted(named))}) have no statement in the "
                                            f"bundle; only {', '.join(sorted(statement_accounts)) or 'no'} statement is annexed")
        else:
            verdict, why = "asserted only", "no statement of the accounts named is annexed"
        claim("The bank accounts are used exclusively for the franchise business", r"exclusively", verdict, why)
    pres = findings.get("PRESUMPTIVE_44AD")
    if pres is not None and pres.values.get("submission_mentions_commission", 0) >= 2:
        claim("The receipts are commission / fees from the franchisor", r"commission",
              "contradicted" if pres.values.get("commission_receipts_194h") else "asserted only",
              "describing the receipts as commission undercuts the s.44AD claim, since s.44AD(6) excludes commission income")
    ok = status_of("AUDIT_44AB")
    if ok is not None:
        claim("The taxpayer was not liable to a tax audit under s.44AB", r"not\s*liable\s*to\s*get\s*the\s*accounts\s*audited",
              "supported" if ok else "contradicted", "turnover is below the s.44AB threshold" if ok else "turnover exceeds it")
    rate = re.search(r"(\d{1,2}\.\d{1,2})\s*%", text)
    receipts, income = facts.value("itr.gross_receipts_44ad"), facts.value("itr.presumptive_income_44ad")
    if rate and receipts and income:
        actual = income / receipts * 100
        claim(f"Income was declared at {rate.group(1)}% of receipts", re.escape(rate.group(1)) + r"\s*%",
              "supported" if abs(actual - float(rate.group(1))) < 0.05 else "contradicted",
              f"the return shows {actual:.2f}%")
    ok = status_of("TDS_CREDIT")
    if ok is not None:
        claim("The receipts suffered TDS and appear in the AIS / Form 26AS", r"(?:AIS|26AS)", "supported" if ok else "contradicted",
              "TDS in the return agrees with the AIS" if ok else "TDS in the return does not agree with the AIS")
    cash = findings.get("CASH_WITHDRAWAL_194N")
    if cash is not None and cash.status != Status.NOT_APPLICABLE:
        gaps = cash.values.get("months_without_certificate") or cash.values.get("account_gaps")
        claim("The operator certifies the withdrawals to the bank every month", r"monthly\s*certificate",
              "supported" if not gaps else "partly supported",
              "certificates cover every month" if not gaps else "certificates are missing for some months or accounts")
    weak = [c for c in claims if c["status"] in ("asserted only", "contradicted", "partly supported")]
    values = {"claims": claims, "asserted_only": sum(c["status"] == "asserted only" for c in claims),
              "contradicted": sum(c["status"] == "contradicted" for c in claims)}
    evidence = [Evidence(page=c["page"], label=f"claim ({c['status']})", quote=c["quote"]) for c in claims]
    if not claims:
        return na(cid, title, "recognisable claims in the submission", q)
    summary = "; ".join(f"{c['claim']}: {c['status']} ({c['why']})" for c in claims)
    if not weak:
        return Finding(check_id=cid, title=title, status=Status.PASS, severity=Severity.INFO,
                       detail=f"Every claim recognised in the submission is supported by the bundle. {summary}.",
                       values=values, reg_query=q, evidence=evidence)
    sev = Severity.HIGH if values["contradicted"] else Severity.MEDIUM
    return Finding(check_id=cid, title=title, status=Status.WARN, severity=sev,
                   detail=f"{len(weak)} of {len(claims)} claims are not carried by the evidence. {summary}.",
                   values={**values, "bearing": WEAKENS}, reg_query=q, evidence=evidence)


# ------------------------------------------------------------------ materiality and bearing

AMOUNT_KEYS = {
    "TURNOVER_AIS_VS_ITR": "difference", "TURNOVER_GST_VS_ITR": "difference", "OTHER_INCOME_OMITTED": "unreported",
    "TDS_CREDIT": "difference", "PRESUMPTIVE_44AD": "commission_receipts_194h", "CASH_WITHDRAWAL_194N": "uncovered_amount",
    "BANK_THIRD_PARTY_CREDITS": "unexplained_total", "LATE_FILING": "expected_fee",
}
BEARING_WHEN_FLAGGED = {"TURNOVER_GST_VS_ITR": NEUTRAL, "LATE_FILING": NEUTRAL, "EVIDENCE_RELEVANCE": NEUTRAL, "CASE_CONTEXT": NEUTRAL,
                        "AO_FIGURE_RECONCILIATION": SUPPORTS}


def annotate(findings: list[Finding], case_mode: bool) -> None:
    """Attach the amount at stake and the finding's bearing on the taxpayer's case, and size the
    severity by the money involved rather than by the type of check."""
    for f in findings:
        key = AMOUNT_KEYS.get(f.check_id)
        if "amount_at_stake" not in f.values and key and isinstance(f.values.get(key), (int, float)):
            f.values["amount_at_stake"] = abs(f.values[key])
        if f.status in (Status.WARN, Status.FAIL):
            f.values.setdefault("bearing", BEARING_WHEN_FLAGGED.get(f.check_id, WEAKENS))
            if f.check_id == "TURNOVER_GST_VS_ITR" and "timing difference" not in f.detail:
                f.values["bearing"] = WEAKENS
        elif f.status == Status.PASS and case_mode:
            f.values.setdefault("bearing", SUPPORTS)
        at_stake = f.values.get("amount_at_stake") or 0
        if f.status in (Status.WARN, Status.FAIL) and f.values.get("bearing") == WEAKENS:
            if at_stake >= CRORE:
                f.severity = Severity.HIGH
            elif at_stake >= 10 * LAKH and f.severity in (Severity.LOW, Severity.INFO):
                f.severity = Severity.MEDIUM
            elif 0 < at_stake < 25_000 and f.severity == Severity.MEDIUM:
                f.severity = Severity.LOW


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:] + ("." if not text.endswith(".") else "")


def run_case_checks(facts: Facts, pages: list[Page], findings: list[Finding]) -> list[Finding]:
    by_id = {f.check_id: f for f in findings}
    submission = [p for p in pages if p.doc_type == "submission"]
    out = [check_case_context(facts), check_notice_compliance(facts, pages), check_ao_figures(facts, pages),
           check_year_consistency(facts), check_deduction_evidence(facts), check_evidence_relevance(facts)]
    out.append(check_claims(facts, submission, by_id))
    return out
