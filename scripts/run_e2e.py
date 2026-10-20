"""End-to-end regression run against a live deployment (local processes, compose, or k8s).

Submits audits for real tickers through the gateway, repeats each one several times, and
verifies on every run that:
  * the job completes and passes through all three agents
  * the report has every required section
  * every flagged finding carries at least one regulation citation
  * every CFR citation in the report was actually retrieved (grounding)
  * repeated runs give identical findings and citations (determinism)

    python scripts/run_e2e.py --url http://localhost:8000 --repeats 3 AAPL MSFT JPM
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.schemas import CITATION_RE  # noqa: E402

DEFAULT_TICKERS = ["AAPL", "MSFT", "JPM", "TSLA", "BA", "GE", "SBUX", "NVDA", "CVX", "PFE"]
# Inputs the pipeline must reject quickly and cleanly: (ticker, fiscal_year, expected error text)
NEGATIVE_CASES = [("ZZZZZQ", None, "unknown ticker"), ("AAPL", 2099, "no 10-K for fiscal year 2099"),
                  ("AAPL", 2003, "greater than or equal to 2009")]
REQUIRED_SECTIONS = ["## Executive summary", "## Observations", "## Recommended follow-up",
                     "## Scope and limitations", "## Appendix A", "## Appendix B"]


def run_one(url: str, ticker: str, fiscal_year: int | None, timeout: float) -> dict:
    t0 = time.time()
    body = {"ticker": ticker} | ({"fiscal_year": fiscal_year} if fiscal_year else {})
    resp = requests.post(f"{url}/audits", json=body, timeout=10)
    if resp.status_code == 422:
        return {"ticker": ticker, "job_id": None, "status": "rejected", "ok": False,
                "errors": [f"rejected by gateway validation: {resp.json()['detail'][0]['msg']}"],
                "seconds": round(time.time() - t0, 2)}
    job = resp.json()["job_id"]
    while time.time() - t0 < timeout:
        state = requests.get(f"{url}/audits/{job}", timeout=10).json()
        if state["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    else:
        return {"ticker": ticker, "job_id": job, "ok": False, "errors": ["timeout"], "seconds": timeout}
    out = {"ticker": ticker, "job_id": job, "status": state["status"], "seconds": round(time.time() - t0, 2)}
    if state["status"] != "completed":
        out.update(ok=False, errors=[f"job failed: {state.get('error')}"])
        return out
    report = requests.get(f"{url}/audits/{job}/report", timeout=10).text
    result = requests.get(f"{url}/audits/{job}/result", timeout=10).json()
    errors = []
    for s in REQUIRED_SECTIONS:
        if s not in report:
            errors.append(f"missing section {s}")
    agents = [t["agent"] for t in result["trace"]]
    for a in ("gateway", "crosscheck", "regulation", "reporter"):
        if a not in agents:
            errors.append(f"agent {a} missing from trace")
    retrieved = {c["citation"] for f in result["findings"] for c in f["citations"]}
    for f in result["findings"]:
        if f["status"] in ("warn", "fail") and not f["citations"]:
            errors.append(f"{f['check_id']} flagged without citations")
    for cite in set(CITATION_RE.findall(report)):
        if cite not in retrieved:
            errors.append(f"ungrounded citation {cite}")
    fingerprint = [(f["check_id"], f["status"], json.dumps(f["values"], sort_keys=True),
                    [c["citation"] for c in f["citations"]]) for f in result["findings"]]
    trace_at = [t["at"] for t in result["trace"]]
    out.update(ok=not errors, errors=errors, accession=result["company"]["accession"],
               pipeline_seconds=round(max(trace_at) - min(trace_at), 3),
               fiscal_year=result["fiscal_year"], flagged=state["summary"]["flagged"],
               drafter=state["summary"]["drafter"], refinement_rounds=result["refinement_round"],
               pods=sorted({f"{t['agent']}:{t['consumer']}" for t in result["trace"]}),
               fingerprint=fingerprint, report=report)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="*", default=DEFAULT_TICKERS)
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--fiscal-year", type=int)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--out", default="e2e-results")
    args = ap.parse_args()

    out_dir = Path(args.out)
    (out_dir / "reports").mkdir(parents=True, exist_ok=True)
    jobs = [(t, i) for i in range(args.repeats) for t in args.tickers]
    with ThreadPoolExecutor(args.concurrency) as pool:
        results = list(pool.map(lambda j: run_one(args.url, j[0], args.fiscal_year, args.timeout), jobs))

    failures = []
    by_ticker: dict[str, list[dict]] = {}
    for r in results:
        by_ticker.setdefault(r["ticker"], []).append(r)
        if not r["ok"]:
            failures.append(f"{r['ticker']} {r['job_id']}: {r['errors']}")
    print(f"{'ticker':6} {'runs':>4} {'ok':>3} {'FY':>5} {'flagged checks':40} {'wall s':>6} {'agents s':>8}  "
          f"deterministic")
    for t, runs in by_ticker.items():
        good = [r for r in runs if r["ok"]]
        prints = {json.dumps(r["fingerprint"]) for r in good}
        deterministic = len(prints) == 1 and len(good) == len(runs)
        if len(prints) > 1:
            failures.append(f"{t}: runs disagree ({len(prints)} distinct results)")
        first = good[0] if good else runs[0]
        print(f"{t:6} {len(runs):>4} {len(good):>3} {str(first.get('fiscal_year', '-')):>5} "
              f"{','.join(first.get('flagged', [])) or '-':40} {statistics.mean(r['seconds'] for r in runs):6.1f} "
              f"{statistics.mean(r.get('pipeline_seconds', 0) for r in runs):8.2f}  {deterministic}")
        if good:
            (out_dir / "reports" / f"{t}.md").write_text(good[0]["report"], encoding="utf-8")
    for ticker, fy, expected in NEGATIVE_CASES:
        r = run_one(args.url, ticker, fy, 30)
        good = r.get("status") in ("failed", "rejected") and any(expected in e for e in r["errors"])
        print(f"negative case {ticker} FY{fy or 'latest'}: {'rejected as expected' if good else 'UNEXPECTED'} "
              f"({r['seconds']}s)")
        if not good:
            failures.append(f"negative case {ticker}/{fy}: {r.get('errors')}")
    pods = sorted({p for r in results for p in r.get("pods", [])})
    print(f"\nconsumers seen: {', '.join(pods)}")
    summary = {"runs": len(results), "passed": sum(r["ok"] for r in results), "failures": failures,
               "consumers": pods,
               "results": [{k: v for k, v in r.items() if k not in ("report", "fingerprint")} for r in results]}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"{summary['passed']}/{summary['runs']} runs passed")
    for f in failures:
        print("FAIL", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
