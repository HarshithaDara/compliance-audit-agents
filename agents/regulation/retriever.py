"""Hybrid retrieval over the scraped eCFR corpus.

    sparse  BM25 over section text (exact accounting vocabulary)
    dense   bge-small-en-v1.5 embeddings via fastembed/ONNX (paraphrase matching)
    fusion  reciprocal-rank fusion, deduplicated to one hit per CFR section
    pinning explicit references in the query ("Item 303", "Rule 5-02", "Rule 12b-25")
            are resolved directly to their sections and ranked first
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parents[2]
CORPUS = Path(os.getenv("REG_CORPUS", ROOT / "data" / "regulations.jsonl"))
INDEX_DIR = Path(os.getenv("REG_INDEX_DIR", ROOT / "data" / "index"))
# Indian income-tax / GST corpus for document audits (scraper/scrape_india_tax.py).
IN_CORPUS = Path(os.getenv("REG_CORPUS_IN", ROOT / "data" / "regulations_in.jsonl"))
IN_INDEX_DIR = Path(os.getenv("REG_INDEX_DIR_IN", ROOT / "data" / "index_in"))
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
MODE = os.getenv("RETRIEVER_MODE", "hybrid")  # hybrid | bm25

CHUNK_CHARS = 1400
RRF_K = 60

_STOP = set("""a an and are as at be by for from has in is it its of on or that the this to was were will with
which shall any such other than under each not may be been all their there these those into also""".split())


def tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+(?:-[0-9a-z]+)?", text.lower())
    return [t[:-1] if len(t) > 4 and t.endswith("s") else t for t in toks if t not in _STOP]


def section_scope(section: str) -> str:
    """Which filers a CFR section applies to: 'general', an industry, or 'transaction'
    (rules for specific deals such as roll-ups, tender offers, ABS or SPACs)."""
    part, _, num = section.partition(".")
    if part == "210":
        article = num.split("-")[0]
        if num == "4-10":
            return "oil_gas"
        return {"6": "investment_company", "7": "insurance", "9": "bank"}.get(article, "general")
    if part == "229" and num.isdigit():
        item = int(num)
        if 1200 <= item <= 1299:
            return "oil_gas"
        if 1300 <= item <= 1399:
            return "mining"
        if 1400 <= item <= 1499:
            return "bank"
        if 900 <= item <= 1199 or 1600 <= item <= 1699:
            return "transaction"
    return "general"


@dataclass
class Chunk:
    chunk_id: int
    section: str
    citation: str
    heading: str
    text: str
    source_url: str


def chunk_sections(records: list[dict]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for rec in records:
        paras = rec["text"].split("\n\n")
        buf = ""
        for p in paras:
            if buf and len(buf) + len(p) > CHUNK_CHARS:
                chunks.append(Chunk(len(chunks), rec["section"], rec["citation"], rec["heading"], buf.strip(),
                                    rec["source_url"]))
                buf = ""
            # Very long single paragraphs are split on sentence boundaries.
            while len(p) > CHUNK_CHARS * 1.5:
                cut = p.rfind(". ", 0, CHUNK_CHARS)
                cut = cut + 1 if cut > 200 else CHUNK_CHARS
                chunks.append(Chunk(len(chunks), rec["section"], rec["citation"], rec["heading"], p[:cut].strip(),
                                    rec["source_url"]))
                p = p[cut:]
            buf += p + "\n\n"
        if buf.strip():
            chunks.append(Chunk(len(chunks), rec["section"], rec["citation"], rec["heading"], buf.strip(),
                                rec["source_url"]))
    return chunks


def _embedder():
    from fastembed import TextEmbedding
    return TextEmbedding(EMBED_MODEL, cache_dir=os.getenv("FASTEMBED_CACHE", None))


def build_index(corpus: Path = CORPUS, out: Path = INDEX_DIR, dense: bool = True) -> int:
    records = [json.loads(line) for line in corpus.open(encoding="utf-8")]
    chunks = chunk_sections(records)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.__dict__, ensure_ascii=False) + "\n")
    if dense:
        model = _embedder()
        docs = [f"{c.heading}\n{c.text}" for c in chunks]
        vecs = np.array(list(model.embed(docs, batch_size=64)), dtype=np.float32)
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        np.save(out / "embeddings.npy", vecs)
    return len(chunks)


@dataclass
class Hit:
    section: str
    citation: str
    heading: str
    excerpt: str
    source_url: str
    score: float      # fused relevance in [0, 1]
    dense: float      # cosine similarity of the best chunk (0 when bm25-only)
    pinned: bool = False


class Retriever:
    def __init__(self, index_dir: Path = INDEX_DIR, mode: str = MODE, corpus: Path | None = None):
        corpus = corpus or (IN_CORPUS if index_dir == IN_INDEX_DIR else CORPUS)
        chunk_file = index_dir / "chunks.jsonl"
        if not chunk_file.exists():
            build_index(corpus, out=index_dir, dense=(mode == "hybrid"))
        self.chunks = [Chunk(**json.loads(line)) for line in chunk_file.open(encoding="utf-8")]
        self.bm25 = BM25Okapi([tokenize(f"{c.heading} {c.text}") for c in self.chunks])
        self.mode = mode
        self.vecs = None
        self.model = None
        if mode == "hybrid":
            emb = index_dir / "embeddings.npy"
            if not emb.exists():
                build_index(corpus, out=index_dir, dense=True)
            self.vecs = np.load(emb)
            self.model = _embedder()
        self.by_section: dict[str, list[Chunk]] = {}
        for c in self.chunks:
            self.by_section.setdefault(c.section, []).append(c)
        self.scope = [section_scope(c.section) for c in self.chunks]
        self._item_map = {}
        for sec, cs in self.by_section.items():
            m = re.search(r"\(Item (\d+)\)", cs[0].heading)
            if m and sec.startswith("229."):
                self._item_map[m.group(1)] = sec

    def _pinned_sections(self, query: str) -> list[str]:
        out = []
        for item in re.findall(r"\bItem (\d{3})\b", query):
            if item in self._item_map:
                out.append(self._item_map[item])
        for rule in re.findall(r"\bRule (\d{1,2}-\d{2})\b", query):
            if f"210.{rule}" in self.by_section:
                out.append(f"210.{rule}")
        for rule in re.findall(r"\bRule (\d{1,2}[A-Za-z]{1,2}-\d+)\b", query):
            if f"240.{rule}" in self.by_section:
                out.append(f"240.{rule}")
        if re.search(r"\bRule 405 of Regulation S-T\b", query) and "232.405" in self.by_section:
            out.append("232.405")
        if re.search(r"\bForm 10-K\b", query) and "249.310" in self.by_section:
            out.append("249.310")
        # Indian corpus: "section 44AD" -> ITA-44AD; with "CGST" in the query, "section 39" -> CGST-39.
        act = "CGST" if re.search(r"\bCGST\b", query) else "ITA"
        for sec in re.findall(r"\bsection (\d{1,3}[A-Z]{0,4})\b", query, re.IGNORECASE):
            for key in (f"{act}-{sec}", f"ITA-{sec}"):
                if key in self.by_section:
                    out.append(key)
                    break
        return list(dict.fromkeys(out))

    def search(self, query: str, k: int = 3, candidates: int = 40, industry: str = "general") -> list[Hit]:
        """Top-k distinct CFR sections. Industry-specific articles are only eligible for
        filers in that industry; deal-specific rules only when cited explicitly."""
        allowed = np.array([s == "general" or s == industry for s in self.scope])
        sparse = self.bm25.get_scores(tokenize(query))
        sparse = np.where(allowed, sparse, -np.inf)
        sparse_rank = [i for i in np.argsort(-sparse)[:candidates] if allowed[i]]
        fused: dict[int, float] = {}
        for rank, idx in enumerate(sparse_rank):
            fused[int(idx)] = fused.get(int(idx), 0.0) + 1.0 / (RRF_K + rank + 1)
        dense_scores = None
        if self.model is not None:
            qv = np.array(next(iter(self.model.query_embed([query]))), dtype=np.float32)
            qv /= np.linalg.norm(qv)
            dense_scores = self.vecs @ qv
            masked = np.where(allowed, dense_scores, -np.inf)
            for rank, idx in enumerate(np.argsort(-masked)[:candidates]):
                fused[int(idx)] = fused.get(int(idx), 0.0) + 1.0 / (RRF_K + rank + 1)
        max_possible = 2.0 / (RRF_K + 1) if dense_scores is not None else 1.0 / (RRF_K + 1)

        def best_chunk_for(section: str) -> int:
            ids = [c.chunk_id for c in self.by_section[section]]
            if dense_scores is not None:
                return max(ids, key=lambda i: dense_scores[i])
            return max(ids, key=lambda i: sparse[i])

        hits: list[Hit] = []
        seen: set[str] = set()

        def add(idx: int, score: float, pinned: bool) -> None:
            c = self.chunks[idx]
            if c.section in seen:
                return
            seen.add(c.section)
            hits.append(Hit(c.section, c.citation, c.heading, c.text[:700], c.source_url,
                            round(min(1.0, score / max_possible), 4),
                            round(float(dense_scores[idx]), 4) if dense_scores is not None else 0.0, pinned))

        for sec in self._pinned_sections(query):
            add(best_chunk_for(sec), max_possible, True)
        for idx, score in sorted(fused.items(), key=lambda kv: (-kv[1], kv[0])):
            if len(hits) >= k:
                break
            add(idx, score, False)
        return hits[:k]


if __name__ == "__main__":
    import sys
    n = build_index(dense=(MODE == "hybrid"))
    print(f"indexed {n} chunks -> {INDEX_DIR}")
    if IN_CORPUS.exists():
        # CI's tests query the Indian corpus with BM25 only, so they can skip its embeddings.
        in_mode = os.getenv("REG_INDEX_IN_MODE", MODE)
        n = build_index(IN_CORPUS, IN_INDEX_DIR, dense=(in_mode == "hybrid"))
        print(f"indexed {n} chunks -> {IN_INDEX_DIR}")
    if len(sys.argv) > 1:
        for h in Retriever().search(" ".join(sys.argv[1:])):
            print(h.score, h.dense, h.citation, h.heading)
