"""End-to-end document audit against a running deployment (kind cluster, compose or local).

Uploads a synthetic income-tax / GST bundle (tests/doc_factories.py, no real taxpayer data),
waits for the pipeline, and checks the findings, page provenance and citations.
    python scripts/run_doc_e2e.py --url http://localhost:8080 [--reader none] [--pdf path/to/real.pdf]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default="http://localhost:8080")
    ap.add_argument("--reader", default="none", choices=["none", "local", "claude"])
    ap.add_argument("--pdf", type=Path, help="audit this PDF instead of the synthetic bundle (no assertions)")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--out", type=Path, help="write the report here")
    args = ap.parse_args()

    if args.pdf:
        data, name = args.pdf.read_bytes(), args.pdf.name
    else:
        from tests.doc_factories import bundle_pdf
        data, name = bundle_pdf(), "synthetic-bundle.pdf"
    t0 = time.time()
    res = requests.post(f"{args.url}/documents", files={"file": (name, data, "application/pdf")},
                        data={"ai_reader": args.reader}, timeout=120)
    res.raise_for_status()
    job = res.json()["job_id"]
    status = "queued"
    while time.time() - t0 < args.timeout:
        state = requests.get(f"{args.url}/audits/{job}", timeout=30).json()
        if state["status"] != status:
            status = state["status"]
            print(f"{time.time() - t0:6.1f}s  {status}")
        if status in ("completed", "failed"):
            break
        time.sleep(1)
    if status != "completed":
        print(f"FAILED: {state.get('error', status)}")
        return 1
    summary = state["summary"]
    report = requests.get(f"{args.url}/audits/{job}/report", timeout=30).text
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
    print(f"{summary['pages']} pages, {summary['checks']} checks, flagged: {', '.join(summary['flagged'])}")
    if args.pdf:
        return 0
    problems = []
    for cid in ("TURNOVER_GST_VS_ITR", "PRESUMPTIVE_44AD", "CASH_WITHDRAWAL_194N", "OTHER_INCOME_OMITTED"):
        if cid not in summary["flagged"]:
            problems.append(f"expected {cid} to be flagged")
    for needle in ("Income-tax Act, 1961 s.44AD", "Income-tax Act, 1961 s.194N", "- p."):
        if needle not in report:
            problems.append(f"report lacks {needle!r}")
    if summary["drafter"] != "template drafter (deterministic)" and args.reader != "claude":
        problems.append(f"confidential document drafted by {summary['drafter']}")
    for p in problems:
        print("FAIL:", p)
    print("document e2e passed" if not problems else "document e2e FAILED")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
