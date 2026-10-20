"""Page-level text extraction with provenance.

Every page keeps its 1-based PDF index, the page number printed on it (bundles carry their own
numbering, which rarely matches the PDF index) and how its text was obtained:
    text   the PDF's own text layer (pypdf)
    ocr    rendered with pypdfium2 and read by RapidOCR (local ONNX model, nothing leaves the machine)
    empty  no text layer and OCR unavailable or found nothing
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from typing import Callable

from common import config

log = logging.getLogger("document.pdftext")

MIN_TEXT_CHARS = 25
_PRINTED = re.compile(r"^\s*(\d{1,4})\s*$")


class UnreadablePdf(ValueError):
    pass


@dataclass
class Page:
    number: int
    text: str
    method: str  # text | ocr | empty
    printed: str | None = None
    doc_type: str = "other"


def printed_page_number(text: str, number: int) -> str | None:
    """The page number printed in the footer: the last short numeric line, if it is close
    enough to the PDF index to be a page number rather than an amount."""
    for line in reversed([ln for ln in text.splitlines() if ln.strip()][-4:]):
        m = _PRINTED.match(line)
        if m and abs(int(m.group(1)) - number) <= 60:
            return m.group(1)
    return None


OcrFn = Callable[[bytes, int], str]


def rapidocr_engine() -> OcrFn | None:
    """Returns an OCR function (pdf bytes, page number) -> text, or None when the OCR stack
    isn't installed. The model is loaded once and reused."""
    if config.DOC_OCR == "off":
        return None
    try:
        import pypdfium2 as pdfium
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        log.warning("OCR unavailable (install rapidocr-onnxruntime and pypdfium2); scanned pages stay empty")
        return None
    engine = RapidOCR()
    cache: dict[int, object] = {}

    def ocr(pdf: bytes, number: int) -> str:
        doc = cache.get(id(pdf))
        if doc is None:
            cache.clear()
            doc = cache[id(pdf)] = pdfium.PdfDocument(pdf)
        image = doc[number - 1].render(scale=2).to_pil()
        result, _ = engine(image)
        return "\n".join(r[1] for r in (result or []))
    return ocr


def extract_pages(pdf: bytes, ocr: OcrFn | None = None) -> list[Page]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    try:
        reader = PdfReader(io.BytesIO(pdf))
        if reader.is_encrypted and not reader.decrypt(""):
            raise UnreadablePdf("the PDF is password-protected")
        raw = [(p.extract_text() or "") for p in reader.pages]
    except (PdfReadError, ValueError, KeyError) as e:
        if isinstance(e, UnreadablePdf):
            raise
        raise UnreadablePdf(f"could not read the PDF: {e}") from e
    pages = []
    for i, text in enumerate(raw, 1):
        method = "text"
        if len(text.strip()) < MIN_TEXT_CHARS:
            method = "empty"
            if ocr is not None:
                try:
                    ocr_text = ocr(pdf, i)
                except Exception as e:  # one bad page must not sink a 400-page bundle
                    log.warning("OCR failed on page %d: %s", i, type(e).__name__)
                    ocr_text = ""
                if len(ocr_text.strip()) >= MIN_TEXT_CHARS:
                    text, method = ocr_text, "ocr"
        pages.append(Page(i, text, method, printed_page_number(text, i)))
    return pages
