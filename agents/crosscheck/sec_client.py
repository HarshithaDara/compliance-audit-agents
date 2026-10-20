"""Live client for SEC EDGAR XBRL data (https://www.sec.gov/edgar/sec-api-documentation).

Downloads are cached in Redis (when available) so repeated audits don't re-hit SEC,
and requests are throttled well under SEC's 10 requests/second limit.
"""
from __future__ import annotations

import gzip
import json
import threading
import time

import requests

from common import config

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
CACHE_TTL = 24 * 3600

_lock = threading.Lock()
_last_call = 0.0


class SecError(RuntimeError):
    pass


class SecNotFound(SecError):
    """Permanent: unknown ticker or no XBRL data. Not worth retrying."""


def _throttled_get(url: str) -> dict:
    global _last_call
    with _lock:
        wait = 0.2 - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
    headers = {"User-Agent": config.SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    for attempt in range(4):
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            raise SecNotFound(f"no XBRL data published at {url}")
        if resp.status_code in (403, 429, 500, 502, 503):
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
    raise SecError(f"SEC request failed ({resp.status_code}) for {url}; check SEC_USER_AGENT")


class SecClient:
    def __init__(self, redis_client=None):
        self.r = redis_client

    def _cached(self, key: str, url: str) -> dict:
        if self.r is not None:
            blob = self.r.get(key)
            if blob:
                return json.loads(gzip.decompress(bytes.fromhex(blob)))
        data = _throttled_get(url)
        if self.r is not None:
            self.r.set(key, gzip.compress(json.dumps(data).encode()).hex(), ex=CACHE_TTL)
        return data

    def lookup_cik(self, ticker: str) -> tuple[str, str]:
        data = self._cached("sec:tickers", TICKERS_URL)
        t = ticker.upper()
        for row in data.values():
            if row["ticker"].upper() == t:
                return str(row["cik_str"]).zfill(10), row["title"]
        raise SecNotFound(f"unknown ticker {ticker}")

    def company_facts(self, cik: str) -> dict:
        return self._cached(f"sec:facts:{cik}", FACTS_URL.format(cik=cik))

    def sic(self, cik: str) -> tuple[str | None, str | None]:
        """Standard Industrial Classification code and description from the submissions API."""
        try:
            data = self._cached(f"sec:subm:{cik}", SUBMISSIONS_URL.format(cik=cik))
        except SecError:
            return None, None
        return (data.get("sic") or None), (data.get("sicDescription") or None)
