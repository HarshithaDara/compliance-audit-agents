"""Scrape Indian direct- and indirect-tax law for the document audits.

Produces data/regulations_in.jsonl in the same record shape as the SEC corpus, keyed by
statutory section so retrieval returns one hit per section:
    {"citation": "Income-tax Act, 1961 s.44AD", "section": "ITA-44AD", "part": "ITA",
     "heading": "...", "text": "...", "source_url": "...#page=N", "as_of": "YYYY-MM-DD"}

Sources (official; all fetched live):
    indiabudget.gov.in   Memoranda explaining the provisions of each Finance Bill (Ministry of
                         Finance). They state, section by section, what each amendment to the
                         Income-tax Act, 1961 does and from which assessment year: §44AD, §44AB,
                         §194N, §234F, §87A, ... The Finance (No. 2) Bill, 2019 adds the enacted text of §194N.
    indiacode.gov.in     The Central Goods and Services Tax Act, 2017 (DSpace REST API).
incometaxindia.gov.in and indiankanoon.org refuse automated clients (HTTP 403), so they are not used.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

import logging

import requests

logging.getLogger("pypdf").setLevel(logging.ERROR)  # font-encoding warnings on government PDFs are harmless

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "regulations_in.jsonl"

BUDGET = "https://www.indiabudget.gov.in"
# (label, url): the direct-tax memorandum of each Finance Bill from 2016 on.
MEMORANDA = [
    ("Finance Bill, 2016", f"{BUDGET}/budget2016-2017/ub2016-17/memo/mem1.pdf"),
    ("Finance Bill, 2017", f"{BUDGET}/budget2017-2018/ub2017-18/memo/memo.pdf"),
    ("Finance Bill, 2018", f"{BUDGET}/budget2018-2019/ub2018-19/memo/memo.pdf"),
    ("Finance (No. 2) Bill, 2019", f"{BUDGET}/budget2019-20/doc/memo.pdf"),
    ("Finance Bill, 2020", f"{BUDGET}/budget2020-21/doc/memo.pdf"),
    ("Finance Bill, 2021", f"{BUDGET}/budget2021-22/doc/memo.pdf"),
    ("Finance Bill, 2022", f"{BUDGET}/budget2022-23/doc/memo.pdf"),
    ("Finance Bill, 2023", f"{BUDGET}/budget2023-24/doc/memo.pdf"),
    ("Finance Bill, 2024", f"{BUDGET}/budget2024-25/doc/memo.pdf"),
]
BILLS = [("Finance (No. 2) Bill, 2019 (text)", f"{BUDGET}/budget2019-20/doc/Finance_Bill.pdf", ["194N"])]

INDIACODE = "https://indiacode.gov.in/server/api"
CGST_ITEM = "1f98f6d0-ec9d-42f0-bd50-dc34d25998e1"  # The Central Goods and Services Tax Act, 2017 (central)
CGST_SECTIONS = ["9", "15", "16", "22", "31", "34", "35", "37", "39", "44", "61", "73", "74", "122"]

SESSION = requests.Session()
# indiabudget.gov.in rejects user agents that do not start with "Mozilla/5.0"; this one still names the project.
SESSION.headers.update({"User-Agent": "Mozilla/5.0 ComplianceAuditAgents/1.0"})

SECTION_RE = re.compile(r"\bsections?\s+(\d{1,3}[A-Z]{0,4})\b(?!\s*of the (?:Customs|Central Excise|Finance))")
PARA_RE = re.compile(r"\n(?=\s*\d{1,2}\.\s+[A-Z])")


def _get(url: str, retries: int = 4) -> bytes:
    for attempt in range(retries):
        try:
            resp = SESSION.get(url, timeout=180)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 200:
            return resp.content
        if resp.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
    raise RuntimeError(f"giving up on {url}")


def pdf_pages(data: bytes) -> list[str]:
    from pypdf import PdfReader
    return [(p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages]


def clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"-\n(?=[a-z])", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def direct_tax_pages(pages: list[str]) -> list[str]:
    """The memorandum covers direct taxes first; stop where the indirect-tax part begins."""
    for i, t in enumerate(pages):
        if i > 3 and re.search(r"^\s*INDIRECT TAXES\s*$|^\s*CUSTOMS\s*$", t, re.MULTILINE | re.IGNORECASE):
            return pages[:i]
    return pages


def _record(sec: str, label: str, text: str, url: str, page: int, as_of: str) -> dict:
    title = " ".join(re.split(r"(?<=[a-z])\.\s", text, maxsplit=1)[0].split())
    title = re.sub(r"^\d{1,2}\.?\s+", "", title)[:140]
    return {"citation": f"Income-tax Act, 1961 s.{sec}", "section": f"ITA-{sec}", "part": "ITA",
            "heading": f"Section {sec} - {label}: {title}", "text": text,
            "source_url": f"{url}#page={page}", "as_of": as_of}


def memorandum_records(label: str, url: str, as_of: str) -> list[dict]:
    """Split the memorandum into numbered paragraphs and attribute each to the section(s) it cites
    most (ties count for each), or to the previous paragraph's sections when it cites none. Consecutive
    paragraphs about the same section are merged into one record."""
    pages = direct_tax_pages(pdf_pages(_get(url)))
    paras: list[tuple[int, str]] = []
    for n, t in enumerate(pages, 1):
        for para in PARA_RE.split(clean(t)):
            if len(para.strip()) > 80:
                paras.append((n, para.strip()))
    records: list[dict] = []
    open_recs: dict[str, tuple[int, dict]] = {}  # section -> (last paragraph index, record)
    previous: list[str] = []
    for i, (page, para) in enumerate(paras):
        counts = Counter(SECTION_RE.findall(para))
        top = max(counts.values(), default=0)
        cited = [s for s, c in counts.most_common(3) if c == top] or previous
        for sec in cited:
            last = open_recs.get(sec)
            if last and last[0] == i - 1 and len(last[1]["text"]) < 6000:
                last[1]["text"] += "\n\n" + para
                open_recs[sec] = (i, last[1])
            else:
                rec = {"sec": sec, "page": page, "text": para}
                records.append(rec)
                open_recs[sec] = (i, rec)
        previous = cited
    return [_record(r["sec"], label, r["text"], url, r["page"], as_of) for r in records]


def bill_records(label: str, url: str, as_of: str, sections: list[str]) -> list[dict]:
    """From a Finance Bill: the enacted text of an inserted section ("194N. Every person, ...")
    and the Notes on Clauses paragraph explaining it."""
    pages = [clean(t) for t in pdf_pages(_get(url))]
    out = []
    for sec in sections:
        for n, t in enumerate(pages, 1):
            m = re.search(rf"(?:^|\n){re.escape(sec)}\.\s+[A-Z]", t)
            if m and not any(r["heading"].startswith(f"Section {sec} - {label}: enacted") for r in out):
                text = (t[m.start():] + "\n" + (pages[n] if n < len(pages) else ""))[:4000]
                out.append({**_record(sec, label, text.strip(), url, n, as_of),
                            "heading": f"Section {sec} - {label}: enacted text"})
            m = re.search(rf"The proposed new section {re.escape(sec)}", t)
            if m:
                out.append({**_record(sec, label, t[m.start():m.start() + 2500].strip(), url, n, as_of),
                            "heading": f"Section {sec} - {label}: notes on clauses"})
    return out


def cgst_records(as_of: str) -> list[dict]:
    bundles = json.loads(_get(f"{INDIACODE}/core/items/{CGST_ITEM}/bundles"))["_embedded"]["bundles"]
    text_bundle = next(b for b in bundles if b["name"] == "TEXT")
    streams = json.loads(_get(text_bundle["_links"]["bitstreams"]["href"]))["_embedded"]["bitstreams"]
    english = next(s for s in streams if s["name"].startswith("a"))  # a2017-12 (English), not the Hindi h2017-12
    text = _get(english["_links"]["content"]["href"]).decode("utf-8", errors="replace")
    handle = f"https://indiacode.gov.in/items/{CGST_ITEM}"
    heads = list(re.finditer(r"^(\d{1,3}[A-Z]?)\. ([^\n—]{3,120}?)\.\s?—", text, re.MULTILINE))
    out = []
    for i, m in enumerate(heads):
        sec = m.group(1)
        if sec not in CGST_SECTIONS:
            continue
        body = text[m.start(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        out.append({"citation": f"CGST Act, 2017 s.{sec}", "section": f"CGST-{sec}", "part": "CGST",
                    "heading": f"Section {sec} - {m.group(2).strip()} (Central Goods and Services Tax Act, 2017)",
                    "text": clean(body)[:12000], "source_url": handle, "as_of": as_of})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    as_of = date.today().isoformat()
    records: list[dict] = []
    for label, url in MEMORANDA:
        recs = memorandum_records(label, url, as_of)
        print(f"{label}: {len(recs)} section records", file=sys.stderr)
        records += recs
    for label, url, only in BILLS:
        recs = bill_records(label, url, as_of, only)
        print(f"{label}: {len(recs)} section records", file=sys.stderr)
        records += recs
    cgst = cgst_records(as_of)
    print(f"CGST Act, 2017: {len(cgst)} sections", file=sys.stderr)
    records += cgst
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    sections = Counter(r["section"] for r in records)
    print(f"wrote {len(records)} records covering {len(sections)} sections -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
