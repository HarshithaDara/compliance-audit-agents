"""Short-lived storage for uploaded PDFs, shared by the gateway (writer) and the document agent
(reader). Redis keeps the bytes base64-encoded because agent connections decode responses as
text; every blob expires after DOC_BLOB_TTL_SECONDS even if no agent ever picks it up."""
from __future__ import annotations

import base64

from common import config


def blob_key(job_id: str) -> str:
    return f"audit:doc:{job_id}:pdf"


def store_pdf(r, job_id: str, pdf: bytes) -> None:
    r.set(blob_key(job_id), base64.b64encode(pdf).decode("ascii"), ex=config.DOC_BLOB_TTL_SECONDS)


def load_pdf(r, job_id: str) -> bytes | None:
    raw = r.get(blob_key(job_id))
    return base64.b64decode(raw) if raw else None


def delete_pdf(r, job_id: str) -> None:
    r.delete(blob_key(job_id))
