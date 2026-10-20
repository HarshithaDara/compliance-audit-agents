"""Agent-outage drill: submit audits while one agent role is down, then bring it back and
confirm every queued job completes (Redis Streams keep the work; nothing is lost).

    python scripts/resilience_test.py --url http://127.0.0.1:8000 --stop "<cmd to stop agent>" --start "<cmd>"
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

import requests


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--stop", required=True, help="shell command that stops the agent")
    ap.add_argument("--start", required=True, help="shell command that starts it again")
    ap.add_argument("tickers", nargs="*", default=["AAPL", "MSFT", "NVDA", "BA", "PFE"])
    args = ap.parse_args()

    subprocess.run(args.stop, shell=True, check=True)
    time.sleep(2)
    jobs = {t: requests.post(f"{args.url}/audits", json={"ticker": t}, timeout=10).json()["job_id"]
            for t in args.tickers}
    time.sleep(8)
    stalled = {t: requests.get(f"{args.url}/audits/{j}", timeout=10).json()["status"] for t, j in jobs.items()}
    print("while agent down:", stalled)
    backlog = requests.get(f"{args.url}/queues", timeout=10).json()
    print("queues while down:", backlog)

    subprocess.run(args.start, shell=True, check=True)
    deadline = time.time() + 120
    final = {}
    while time.time() < deadline:
        final = {t: requests.get(f"{args.url}/audits/{j}", timeout=10).json()["status"] for t, j in jobs.items()}
        if all(s == "completed" for s in final.values()):
            break
        time.sleep(1)
    print("after restart:", final)
    ok = all(s != "completed" for s in stalled.values()) and all(s == "completed" for s in final.values())
    print("RESILIENCE TEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
