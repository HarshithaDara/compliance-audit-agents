from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

import re

from pydantic import BaseModel, Field

# Matches CFR citations as the agents write them, e.g. "17 CFR 229.303", "17 CFR 240.10D-1".
CITATION_RE = re.compile(r"17 CFR \d{3}\.\d+[A-Za-z]{0,2}(?:-\d+)?")


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
    ticker: str
    fiscal_year: int | None = None
    company: CompanyContext | None = None
    findings: list[Finding] = Field(default_factory=list)
    refinement_round: int = 0
    refine_check_ids: list[str] = Field(default_factory=list)
    trace: list[TraceEntry] = Field(default_factory=list)

    @classmethod
    def new(cls, ticker: str, fiscal_year: int | None) -> "AuditMessage":
        return cls(job_id=uuid.uuid4().hex[:12], ticker=ticker.upper(), fiscal_year=fiscal_year)

    def stamp(self, agent: str, consumer: str, note: str = "") -> "AuditMessage":
        self.trace.append(TraceEntry(agent=agent, consumer=consumer, at=time.time(), note=note))
        return self
