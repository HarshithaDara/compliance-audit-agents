"""HTTP gateway: accepts audit requests, enqueues them for the agents, serves status and reports."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

import redis
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from common import blobs, bus, config
from common.schemas import AuditMessage, DocumentContext

STATIC_DIR = Path(__file__).resolve().parent / "static"
# Workers block on XREADGROUP for 5s at a time, so a live consumer is never idle much longer.
LIVE_CONSUMER_IDLE_MS = 15000

app = FastAPI(title="Compliance Audit Agents", version="1.0.0")
_redis = None


def r():
    global _redis
    if _redis is None:
        _redis = bus.connect()
    return _redis


class AuditRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=10, pattern=r"^[A-Za-z.\-]+$")
    fiscal_year: int | None = Field(default=None, ge=2009, le=2100)


@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/livez")
def livez():
    """Liveness: the process is serving. Deliberately ignores Redis; restarting the
    gateway can't fix a Redis outage."""
    return {"ok": True}


@app.get("/healthz")
def healthz():
    """Readiness: Redis is reachable, so requests can be queued."""
    try:
        r().ping()
    except (redis.ConnectionError, redis.TimeoutError) as e:
        raise HTTPException(503, f"redis unavailable: {e}")
    return {"ok": True}


@app.post("/audits", status_code=202)
def create_audit(req: AuditRequest):
    msg = AuditMessage.new(req.ticker, req.fiscal_year)
    msg.stamp("gateway", config.CONSUMER_NAME, "accepted")
    bus.set_status(r(), msg.job_id, "queued", ticker=msg.ticker, fiscal_year=req.fiscal_year or "latest",
                   created_at=f"{time.time():.3f}")
    bus.publish(r(), config.STREAM_CROSSCHECK, msg)
    return {"job_id": msg.job_id, "status": "queued"}


AI_READERS = ("local", "claude", "none")


def _safe_name(name: str | None) -> str:
    base = re.split(r"[\\/]", name or "document.pdf")[-1]
    base = re.sub(r"[^\w .()\-]", "_", base).strip() or "document.pdf"
    return base[:120]


@app.post("/documents", status_code=202)
async def create_document_audit(file: UploadFile = File(...), ai_reader: str = Form("local")):
    """Audit an uploaded PDF (e.g. an income-tax / GST evidence bundle). The file is held in Redis
    only until the document agent has read it, and never written to disk or logs."""
    if ai_reader not in AI_READERS:
        raise HTTPException(422, f"ai_reader must be one of {', '.join(AI_READERS)}")
    if ai_reader == "claude" and not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(400, "the Claude reader needs ANTHROPIC_API_KEY on the server; choose 'local' or 'none'")
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    chunks, size = [], 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, f"file is larger than {config.MAX_UPLOAD_MB} MB")
        chunks.append(chunk)
    pdf = b"".join(chunks)
    if not pdf.startswith(b"%PDF-"):
        raise HTTPException(415, "only PDF files can be audited")
    doc = DocumentContext(filename=_safe_name(file.filename), sha256=hashlib.sha256(pdf).hexdigest(), size_bytes=size,
                          ai_reader=ai_reader, allow_cloud=(ai_reader == "claude"))
    msg = AuditMessage.new_document(doc)
    msg.stamp("gateway", config.CONSUMER_NAME, f"accepted {size // 1024} KB PDF, AI reader: {ai_reader}")
    blobs.store_pdf(r(), msg.job_id, pdf)
    bus.set_status(r(), msg.job_id, "queued", kind="document", document=doc.filename, created_at=f"{time.time():.3f}")
    bus.publish(r(), config.STREAM_DOCUMENT, msg)
    return {"job_id": msg.job_id, "status": "queued"}


@app.get("/audits/{job_id}")
def get_audit(job_id: str):
    state = r().hgetall(bus.job_key(job_id))
    if not state:
        raise HTTPException(404, "unknown job")
    if "summary" in state:
        state["summary"] = json.loads(state["summary"])
    return state


@app.get("/audits/{job_id}/report", response_class=PlainTextResponse)
def get_report(job_id: str):
    report = r().get(f"audit:job:{job_id}:report")
    if report is None:
        raise HTTPException(404, "report not ready")
    return report


@app.get("/audits/{job_id}/result")
def get_result(job_id: str):
    raw = r().get(f"audit:job:{job_id}:result")
    if raw is None:
        raise HTTPException(404, "result not ready")
    return json.loads(raw)


@app.get("/queues")
def queues():
    out = {}
    for stream, group in [(config.STREAM_CROSSCHECK, "crosscheck"), (config.STREAM_DOCUMENT, "document"),
                          (config.STREAM_REGULATION, "regulation"), (config.STREAM_REPORT, "reporter")]:
        try:
            g = next((x for x in r().xinfo_groups(stream) if x["name"] == group), None)
            # lag = not yet delivered to any consumer; pending = delivered but not yet acked.
            # Redis keeps consumers of deleted pods registered, so count only those that polled recently.
            live = sum(1 for c in r().xinfo_consumers(stream, group) if c["idle"] < LIVE_CONSUMER_IDLE_MS) if g else 0
            out[stream] = {"length": r().xlen(stream), "lag": (g.get("lag") or 0) if g else 0,
                           "pending": g["pending"] if g else 0, "consumers": live}
        except Exception:
            out[stream] = {"length": 0, "lag": 0, "pending": 0, "consumers": 0}
    out[config.STREAM_DLQ] = {"length": r().xlen(config.STREAM_DLQ)}
    return out
