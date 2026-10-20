"""Record a trimmed snapshot of real SEC data, or seed it into Redis.

SEC rejects automated requests from many cloud IP ranges (including GitHub Actions
runners), so CI seeds the agents' SEC cache from a snapshot recorded on a normal network.
The agents then read it through their usual cache path.

    python scripts/sec_snapshot.py record AAPL MSFT JPM BA PFE      # live SEC -> tests/fixtures
    python scripts/sec_snapshot.py seed --redis redis://localhost:6379/0
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.crosscheck.sec_client import SecClient  # noqa: E402

SNAPSHOT = ROOT / "tests" / "fixtures" / "sec_snapshot.json.gz"


def used_concepts() -> set[str]:
    """Every XBRL concept name the cross-checks reference."""
    src = (ROOT / "agents" / "crosscheck" / "checks.py").read_text(encoding="utf-8")
    return set(re.findall(r'"([A-Z][A-Za-z0-9]{3,})"', src)) | {"EntityPublicFloat"}


def record(tickers: list[str], out: Path) -> None:
    sec = SecClient()
    keep = used_concepts()
    all_tickers = sec._cached("sec:tickers", "https://www.sec.gov/files/company_tickers.json")
    wanted = {t.upper() for t in tickers}
    snap = {"tickers": {k: v for k, v in all_tickers.items() if v["ticker"].upper() in wanted},
            "facts": {}, "submissions": {}}
    for t in tickers:
        cik, _ = sec.lookup_cik(t)
        facts = sec.company_facts(cik)
        facts["facts"] = {tax: {c: body for c, body in concepts.items() if c in keep}
                          for tax, concepts in facts["facts"].items()}
        snap["facts"][cik] = facts
        sic, desc = sec.sic(cik)
        snap["submissions"][cik] = {"sic": sic, "sicDescription": desc}
        print(f"recorded {t} (CIK {cik}): {sum(len(v) for v in facts['facts'].values())} concepts")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gzip.compress(json.dumps(snap, sort_keys=True).encode()))
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KiB)")


def seed(redis_url: str, path: Path) -> None:
    from common import bus
    snap = json.loads(gzip.decompress(path.read_bytes()))
    sec = SecClient(bus.connect(redis_url))
    sec.seed_tickers(snap["tickers"])
    for cik, facts in snap["facts"].items():
        sec.seed_facts(cik, facts)
        sec.seed_submissions(cik, snap["submissions"][cik])
    print(f"seeded {len(snap['facts'])} companies into {redis_url}")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("tickers", nargs="+")
    sd = sub.add_parser("seed")
    sd.add_argument("--redis", default="redis://localhost:6379/0")
    for p in (rec, sd):
        p.add_argument("--file", default=str(SNAPSHOT))
    args = ap.parse_args()
    if args.cmd == "record":
        record(args.tickers, Path(args.file))
    else:
        seed(args.redis, Path(args.file))
    return 0


if __name__ == "__main__":
    sys.exit(main())
