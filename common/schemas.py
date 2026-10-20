from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

import re

from pydantic import BaseModel, Field

# Matches citations as the agents write them: CFR ("17 CFR 229.303", "17 CFR 240.10D-1") and
# Indian statutes ("Income-tax Act, 1961 s.44AD", "CGST Act, 2017 s.39").
CITATION_RE = re.compile(r"17 CFR \d{3}\.\d+[A-Za-z]{0,2}(?:-\d+)?|(?:Income-tax|CGST) Act, \d{4} s\.\d+[A-Z]{0,3}")


class Status(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Citation(BaseModel):
    citation: str
    heading: str
    excerpt: str
    source_url: str
    score: float


class Evidence(BaseModel):
    """Where a number in a finding came from inside an uploaded document."""
    page: int                    # 1-based PDF page index
    printed_page: str | None = None  # page number printed on the page, when the bundle has its own numbering
    label: str
    value: Any = None
    quote: str = ""


class Finding(BaseModel):
    check_id: str
    title: str
    status: Status
    severity: Severity
    detail: str
    values: dict[str, Any] = Field(default_factory=dict)
    # Natural-language query the regulation agent uses to find the governing rules.
    reg_query: str
    citations: list[Citation] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class DocumentContext(BaseModel):
    """An uploaded PDF (document audits). Identifiers are masked; raw text never leaves the document agent."""
    filename: str
    sha256: str
    size_bytes: int
    pages: int = 0
    ocr_pages: int = 0
    empty_pages: int = 0
    assessment_year: str | None = None
    form: str | None = None
    pan_masked: str | None = None
    taxpayer: str | None = None
    ai_reader: str = "local"      # local (Ollama) | claude | none
    ai_reader_used: str = ""      # what actually ran, e.g. "ollama qwen2.5:3b" or "unavailable"
    allow_cloud: bool = False     # True only when the uploader chose the Claude reader
    page_types: dict[str, int] = Field(default_factory=dict)
    ai_figures: list[Evidence] = Field(default_factory=list)


class CompanyContext(BaseModel):
    ticker: str
    cik: str
    name: str
    fiscal_year: int
    period_end: str
    form: str
    accession: str
    filed: str
    source_url: str
    sic: str | None = None
    sic_description: str | None = None
    industry: str = "general"  # general | bank | insurance | oil_gas | mining | investment_company


class TraceEntry(BaseModel):
    agent: str
    consumer: str
    at: float
    note: str = ""


class AuditMessage(BaseModel):
    """Envelope passed between agents on the Redis streams."""

    job_id: str
    kind: str = "sec"  # sec | document
    ticker: str = ""
    fiscal_year: int | None = None
    company: CompanyContext | None = None
    document: DocumentContext | None = None
    findings: list[Finding] = Field(default_factory=list)
    refinement_round: int = 0
    refine_check_ids: list[str] = Field(default_factory=list)
    trace: list[TraceEntry] = Field(default_factory=list)

    @classmethod
    def new(cls, ticker: str, fiscal_year: int | None) -> "AuditMessage":
        return cls(job_id=uuid.uuid4().hex[:12], ticker=ticker.upper(), fiscal_year=fiscal_year)

    @classmethod
    def new_document(cls, document: DocumentContext) -> "AuditMessage":
        return cls(job_id=uuid.uuid4().hex[:12], kind="document", document=document)

    def stamp(self, agent: str, consumer: str, note: str = "") -> "AuditMessage":
        self.trace.append(TraceEntry(agent=agent, consumer=consumer, at=time.time(), note=note))
        return self
