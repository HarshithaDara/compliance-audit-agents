"""Score the document agent against cases with expert-expected findings.

Each case file (JSON) names a PDF and what an expert expects:
    {"name": "...", "pdf": "data/private/x.pdf",            # or "synthetic": "case_bundle" (tests/doc_factories)
     "expected": [{"id": "ledger-not-furnished", "check": "NOTICE_COMPLIANCE", "status": ["fail"],
                   "contains": ["ledger"]}, ...],
     "needs_documents_not_in_bundle": [{"id": "...", "why": "..."}],   # expert issues the PDF can't show
     "acceptable_extra": ["LATE_FILING"],                     # flags that are true but not on the expert list
     "facts": {"itr.total_income": 445200}}                   # figure accuracy

Metrics:
    issue recall      expected findings the agent raised (right check, right status, wording present)
    precision         agent flags that match an expected or acceptable finding
    figure accuracy   extracted facts equal to the expected values
Real cases live in data/private/ (git-ignored); the synthetic case runs in CI.

    python scripts/eval_documents.py data/private/eval/*.json tests/eval/*.json [--ocr]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_pages(case: dict, ocr: bool):
    from agents.document import classify
    from agents.document.pdftext import extract_pages, rapidocr_engine
    if case.get("synthetic"):  # the name of a tests/doc_factories bundle builder
        from tests import doc_factories
        build = getattr(doc_factories, case["synthetic"] if isinstance(case["synthetic"], str) else "bundle")
        return classify.classify(build(**case.get("overrides", {})))
    pdf = (ROOT / case["pdf"]).read_bytes()
    return classify.classify(extract_pages(pdf, rapidocr_engine() if ocr else None))


def score(case: dict, ocr: bool = False) -> dict:
    from agents.document import parsers
    from agents.document.agent import analyse
    pages = load_pages(case, ocr)
    facts = parsers.parse_all(pages)
    findings = {f.check_id: f for f in analyse(pages, facts)}
    flagged = {cid for cid, f in findings.items() if f.status.value in ("warn", "fail")}
    hits, misses = [], []
    matched_checks = set()
    for exp in case["expected"]:
        f = findings.get(exp["check"])
        text = (f.detail + " " + json.dumps(f.values, default=str)).lower() if f else ""
        ok = (f is not None and f.status.value in exp.get("status", ["warn", "fail"])
              and all(w.lower() in text for w in exp.get("contains", [])))
        (hits if ok else misses).append(exp["id"])
        if ok:
            matched_checks.add(exp["check"])
    acceptable = set(case.get("acceptable_extra", []))
    true_flags = flagged & (matched_checks | acceptable)
    false_flags = sorted(flagged - matched_checks - acceptable)
    fact_results = {k: (facts.value(k), v) for k, v in case.get("facts", {}).items()}
    fact_ok = sum(1 for got, want in fact_results.values() if got == want)
    return {
        "name": case["name"], "pages": len(pages),
        "recall": len(hits) / len(case["expected"]) if case["expected"] else 1.0,
        "precision": len(true_flags) / len(flagged) if flagged else 1.0,
        "figure_accuracy": fact_ok / len(fact_results) if fact_results else None,
        "missed": misses, "false_flags": false_flags,
        "wrong_figures": {k: v for k, v in fact_results.items() if v[0] != v[1]},
        "out_of_scope": [x["id"] for x in case.get("needs_documents_not_in_bundle", [])],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cases", nargs="+", type=Path)
    ap.add_argument("--ocr", action="store_true", help="OCR scanned pages (slower, needed for scanned evidence)")
    ap.add_argument("--min-recall", type=float, default=0.0)
    args = ap.parse_args()
    results = [score(json.loads(p.read_text(encoding="utf-8")), args.ocr) for p in args.cases]
    print("| Case | Pages | Issue recall | Precision | Figure accuracy | Out of scope |")
    print("|---|---|---|---|---|---|")
    for r in results:
        fig = f"{r['figure_accuracy']:.0%}" if r["figure_accuracy"] is not None else "-"
        print(f"| {r['name']} | {r['pages']} | {r['recall']:.0%} | {r['precision']:.0%} | {fig} | {len(r['out_of_scope'])} |")
    for r in results:
        for label, key in (("missed", "missed"), ("unexpected flags", "false_flags"), ("wrong figures", "wrong_figures"),
                           ("needs documents not in the bundle", "out_of_scope")):
            if r[key]:
                print(f"- {r['name']}: {label}: {r[key]}")
    return 0 if all(r["recall"] >= args.min_recall for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
