"""Switchable AI reader for uploaded documents.

    local   Ollama on this machine / cluster (default). Page text never leaves it.
    claude  Anthropic API. Only when the uploader explicitly chose it.
    none    rules only.

The reader does two narrow jobs, both grounded against the page text so a model cannot put a
number or a quote into the report that is not on the page:
  * key figures on pages no deterministic parser understands
  * judging whether a passage of the written submission explains a discrepancy
"""
from __future__ import annotations

import json
import logging
import re

import requests

from common import config
from common.schemas import Evidence

from agents.document.pdftext import Page

log = logging.getLogger("document.llm")

MAX_PAGE_CHARS = 6000


class Reader:
    name = "none"

    def complete_json(self, system: str, prompt: str) -> dict | None:
        raise NotImplementedError


class OllamaReader(Reader):
    def __init__(self, url: str = config.OLLAMA_URL, model: str = config.OLLAMA_MODEL, timeout: float = 180):
        self.url, self.model, self.timeout = url.rstrip("/"), model, timeout
        self.name = f"Ollama {model} (local)"

    def available(self) -> bool:
        try:
            tags = requests.get(f"{self.url}/api/tags", timeout=5).json()
        except (requests.RequestException, ValueError):
            return False
        names = {m.get("name", "") for m in tags.get("models", [])}
        return self.model in names or f"{self.model}:latest" in names

    def complete_json(self, system: str, prompt: str) -> dict | None:
        resp = requests.post(f"{self.url}/api/chat", timeout=self.timeout, json={
            "model": self.model, "stream": False, "format": "json", "options": {"temperature": 0},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
        resp.raise_for_status()
        return _parse_json(resp.json().get("message", {}).get("content", ""))


class ClaudeReader(Reader):
    def __init__(self, client=None):
        import anthropic
        self.client = client or anthropic.Anthropic()
        self.name = f"Claude {config.ANTHROPIC_MODEL} (cloud, chosen by uploader)"

    def complete_json(self, system: str, prompt: str) -> dict | None:
        response = self.client.messages.create(model=config.ANTHROPIC_MODEL, max_tokens=2048, system=system,
                                               messages=[{"role": "user", "content": prompt}])
        return _parse_json("".join(b.text for b in response.content if b.type == "text"))


def _parse_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return out if isinstance(out, dict) else None


def make_reader(mode: str) -> tuple[Reader | None, str]:
    """Returns (reader or None, what to report as having run)."""
    if mode == "none":
        return None, "rules only (AI reader off)"
    if mode == "claude":
        reader = ClaudeReader()
        return reader, reader.name
    reader = OllamaReader()
    if reader.available():
        return reader, reader.name
    log.warning("Ollama model %s not reachable at %s; continuing rules-only", config.OLLAMA_MODEL, config.OLLAMA_URL)
    return None, f"rules only (local AI reader unavailable: Ollama {config.OLLAMA_MODEL} not reachable)"


# ------------------------------------------------------------------ grounding

def _digits(s: str) -> str:
    return re.sub(r"[^\d]", "", s)


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def number_on_page(value: str, page_text: str) -> bool:
    """A figure is grounded when its digits appear as a whole number on the page (formatting
    such as 1,00,000 vs 100000 or a trailing .00 is ignored)."""
    d = _digits(str(value).split(".")[0])
    if len(d) < 3:
        return False
    page_numbers = {_digits(m.split(".")[0]) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", page_text)}
    return d in page_numbers


def quote_on_page(quote: str, page_text: str) -> bool:
    q = _norm(quote)
    return len(q) >= 12 and q in _norm(page_text)


def line_with(value: str, page_text: str) -> str:
    d = _digits(str(value).split(".")[0])
    for line in page_text.splitlines():
        if d and d in _digits(line):
            return " ".join(line.split())[:200]
    return ""


# ------------------------------------------------------------------ jobs

FIGURES_SYSTEM = """You read one page of an Indian tax / accounting document and list its key monetary figures.
Return JSON: {"figures": [{"label": "<what the amount is>", "value": "<the amount exactly as printed>", "quote": "<the line it appears on, copied exactly>"}]}
At most 8 figures. Only amounts printed on the page. No commentary."""


def extract_figures(reader: Reader, pages: list[Page], progress=lambda: None) -> list[Evidence]:
    out: list[Evidence] = []
    for page in pages:
        progress()
        try:
            data = reader.complete_json(FIGURES_SYSTEM, f"Page {page.number}:\n{page.text[:MAX_PAGE_CHARS]}")
        except Exception as e:  # a reader failure must not fail the audit
            log.warning("AI reader failed on page %d: %s", page.number, type(e).__name__)
            continue
        for fig in (data or {}).get("figures", [])[:8]:
            if not isinstance(fig, dict) or not number_on_page(str(fig.get("value", "")), page.text):
                continue  # ungrounded: the number is not on the page
            quote = str(fig.get("quote", ""))
            if not quote_on_page(quote, page.text):
                quote = line_with(str(fig["value"]), page.text)
            out.append(Evidence(page=page.number, printed_page=page.printed, label=str(fig.get("label", "figure"))[:80],
                                value=str(fig["value"])[:40], quote=quote))
    return out


COVERAGE_SYSTEM = """You check whether a taxpayer's written submission addresses a specific discrepancy.
Return JSON: {"addresses": true|false, "quote": "<the sentence that addresses it, copied exactly, or empty>"}
"addresses" is true only if the passage explains or justifies the discrepancy itself, not merely the general topic."""


def judge_coverage(reader: Reader, discrepancy: str, page: Page) -> tuple[bool, str]:
    try:
        data = reader.complete_json(COVERAGE_SYSTEM, f"Discrepancy: {discrepancy}\n\nSubmission page {page.number}:\n"
                                                     f"{page.text[:MAX_PAGE_CHARS]}")
    except Exception as e:
        log.warning("AI coverage check failed on page %d: %s", page.number, type(e).__name__)
        return False, ""
    if not data or not data.get("addresses"):
        return False, ""
    quote = str(data.get("quote", ""))
    return (True, quote) if quote_on_page(quote, page.text) else (False, "")
