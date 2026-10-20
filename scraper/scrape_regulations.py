"""Scrape SEC financial-reporting regulations from the official eCFR API.

Produces data/regulations.jsonl: one record per CFR section
    {"citation": "17 CFR 229.303", "section": "229.303", "part": "229",
     "heading": "...", "text": "...", "source_url": "...", "as_of": "YYYY-MM-DD"}

Sources (Title 17, Commodity and Securities Exchanges):
    Part 210  Regulation S-X  (form and content of financial statements)
    Part 229  Regulation S-K  (non-financial disclosure, incl. Item 303 MD&A, 308 ICFR)
    Part 244  Regulation G    (non-GAAP financial measures)
    Part 240  selected Exchange Act reporting rules (filer status, deadlines, controls)
    Part 249  Form 10-K
    Part 232  Regulation S-T Rule 405 (XBRL interactive data)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests
from lxml import etree

ECFR = "https://www.ecfr.gov/api/versioner/v1"
TITLE = 17
FULL_PARTS = ["210", "229", "244"]
SELECTED_SECTIONS = [
    "240.12b-2",   # accelerated / large accelerated filer definitions
    "240.12b-25",  # notification of late filing (NT 10-K)
    "240.13a-1",   # requirement of annual reports
    "240.13a-13",  # quarterly reports on Form 10-Q
    "240.13a-14",  # certification of disclosure (SOX 302)
    "240.13a-15",  # issuer's disclosure controls and ICFR (SOX 404)
    "240.10D-1",   # clawback listing standards; defines "accounting restatement"
    "249.310",     # Form 10-K
    "232.405",     # Regulation S-T Rule 405: Interactive Data (XBRL) files
]

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "ComplianceAuditAgents/1.0 (regulation scraper)",
                        "Accept-Encoding": "gzip, deflate"})


def _get(url: str, params: dict | None = None, retries: int = 4) -> requests.Response:
    for attempt in range(retries):
        resp = SESSION.get(url, params=params, timeout=120)
        if resp.status_code == 200:
            return resp
        if resp.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
    resp.raise_for_status()
    return resp


def latest_issue_date() -> str:
    titles = _get(f"{ECFR}/titles.json").json()["titles"]
    return next(t["latest_issue_date"] for t in titles if t["number"] == TITLE)


def _clean(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def parse_sections(xml_bytes: bytes, as_of: str) -> list[dict]:
    root = etree.fromstring(xml_bytes)
    out = []
    for div in root.iter("DIV8"):
        if div.get("TYPE") != "SECTION":
            continue
        section = div.get("N", "").strip()
        head_el = div.find("HEAD")
        heading = _clean("".join(head_el.itertext())) if head_el is not None else section
        paras = []
        for child in div:
            if child.tag == "HEAD":
                continue
            txt = _clean(" ".join(child.itertext()))
            if txt:
                paras.append(txt)
        body = "\n\n".join(paras)
        if not body:
            continue
        out.append({
            "citation": f"17 CFR {section}",
            "section": section,
            "part": section.split(".")[0],
            "heading": heading,
            "text": body,
            "source_url": f"https://www.ecfr.gov/current/title-17/section-{section}",
            "as_of": as_of,
        })
    return out


def scrape(out_path: Path) -> int:
    as_of = latest_issue_date()
    print(f"eCFR title {TITLE} latest issue date: {as_of}")
    records: dict[str, dict] = {}
    for part in FULL_PARTS:
        resp = _get(f"{ECFR}/full/{as_of}/title-{TITLE}.xml", params={"part": part})
        secs = parse_sections(resp.content, as_of)
        print(f"  part {part}: {len(secs)} sections")
        for s in secs:
            records[s["section"]] = s
    for sec in SELECTED_SECTIONS:
        part = sec.split(".")[0]
        resp = _get(f"{ECFR}/full/{as_of}/title-{TITLE}.xml", params={"part": part, "section": sec})
        secs = parse_sections(resp.content, as_of)
        print(f"  section {sec}: {len(secs)} record(s)")
        for s in secs:
            records[s["section"]] = s
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for rec in records.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} sections -> {out_path}")
    return len(records)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "data" / "regulations.jsonl"))
    args = ap.parse_args()
    n = scrape(Path(args.out))
    sys.exit(0 if n > 0 else 1)
