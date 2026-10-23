"""Extraction Markdown PyMuPDF4LLM."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pymupdf
import pymupdf4llm
from pymupdf4llm.helpers import utils as pdf4llm_utils

from gesec.data.extract_pdf.ocr_lighton import LightonOcrClient, OpenWeightOcrClient
from gesec.data.extract_pdf.paths import (
    OCR_LLM_TIMEOUT,
    OCR_MODEL,
    PDF4LLM_MD_SUBDIR,
    PDF4LLM_OCR_BACKEND,
    PDF4LLM_OCR_DPI,
    PDF4LLM_OCR_LANGUAGE,
    PDF4LLM_USE_OCR,
)
from gesec.data.extract_pdf.pdf_utils import page_count, png_bytes_to_data_uri

Pdf4llmOcrBackend = Literal["lighton", "tesseract"]

_TESSERACT_THREAD_LOCK = threading.Lock()


def pdf4llm_markdown_cache_path(ocr_dir: Path, id_cpro: str) -> Path:
    return ocr_dir / PDF4LLM_MD_SUBDIR / f"{id_cpro}.md"


def pdf4llm_tesseract_function() -> Callable[..., Any]:
    from pymupdf4llm.ocr import tesseract_api

    return tesseract_api.exec_ocr


def _ensure_django() -> None:
    import os

    import django
    from django.conf import settings

    if not settings.configured:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gesec.settings")
        django.setup()


def build_lighton_ocr_client() -> OpenWeightOcrClient:
    _ensure_django()
    from django.conf import settings

    from gesec.data.classify_gm.llm import LLMClient

    llm = LLMClient(
        api_key=settings.ALBERT_API_KEY,
        base_url=settings.ALBERT_BASE_URL,
        timeout=OCR_LLM_TIMEOUT,
    )
    return OpenWeightOcrClient(llm, model=OCR_MODEL)


def _page_png_data_uri(page: pymupdf.Page, *, dpi: int = PDF4LLM_OCR_DPI) -> str:
    zoom = dpi / 72.0
    matrix = pymupdf.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    return png_bytes_to_data_uri(pixmap.tobytes(output="png"))


def _markdown_from_chunks(chunks: str | list[dict[str, Any]]) -> str:
    if isinstance(chunks, str):
        return chunks
    parts: list[str] = []
    for chunk in chunks:
        page_number = chunk.get("metadata", {}).get("page_number") or len(parts) + 1
        text = (chunk.get("text") or "").rstrip()
        parts.append(f"--- page {page_number} ---\n{text}")
    return "\n\n".join(parts)


def _markdown_for_page_native(doc: pymupdf.Document, page_index: int) -> str:
    chunks = pymupdf4llm.to_markdown(
        doc,
        pages=[page_index],
        page_chunks=True,
        use_ocr=False,
    )
    return _markdown_from_chunks(chunks)


def extract_invoice_pdf4llm_markdown_lighton(
    pdf_path: Path,
    *,
    ocr_client: LightonOcrClient | None = None,
    use_ocr: bool = PDF4LLM_USE_OCR,
) -> str:
    client = ocr_client or build_lighton_ocr_client()
    parts: list[str] = []
    with pymupdf.open(pdf_path) as doc:
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            page.remove_rotation()
            page_number = page_index + 1
            if use_ocr and pdf4llm_utils.analyze_page(page).get("needs_ocr"):
                text = client.ocr_image_data_uri(_page_png_data_uri(page)).rstrip()
                parts.append(f"--- page {page_number} ---\n{text}")
            else:
                parts.append(_markdown_for_page_native(doc, page_index))
    return "\n\n".join(parts)


def extract_invoice_pdf4llm_markdown_tesseract(
    pdf_path: Path,
    *,
    use_ocr: bool = PDF4LLM_USE_OCR,
) -> str:
    kwargs: dict[str, Any] = {
        "page_chunks": True,
        "use_ocr": use_ocr,
        "force_ocr": False,
    }
    if use_ocr:
        kwargs["ocr_function"] = pdf4llm_tesseract_function()
        kwargs["ocr_dpi"] = PDF4LLM_OCR_DPI
        kwargs["ocr_language"] = PDF4LLM_OCR_LANGUAGE

    def _run_to_markdown() -> str | list[dict[str, Any]]:
        return pymupdf4llm.to_markdown(str(pdf_path), **kwargs)

    if use_ocr:
        with _TESSERACT_THREAD_LOCK:
            chunks = _run_to_markdown()
    else:
        chunks = _run_to_markdown()
    return _markdown_from_chunks(chunks)


def extract_invoice_pdf4llm_markdown(
    pdf_path: Path,
    *,
    use_ocr: bool = PDF4LLM_USE_OCR,
    ocr_backend: Pdf4llmOcrBackend = PDF4LLM_OCR_BACKEND,
) -> str:
    if ocr_backend == "tesseract":
        return extract_invoice_pdf4llm_markdown_tesseract(pdf_path, use_ocr=use_ocr)
    return extract_invoice_pdf4llm_markdown_lighton(pdf_path, use_ocr=use_ocr)


def extract_invoice_pdf4llm_markdown_cached(
    pdf_path: Path,
    cache_path: Path,
    *,
    force_refresh: bool = False,
    use_ocr: bool = PDF4LLM_USE_OCR,
    ocr_backend: Pdf4llmOcrBackend = PDF4LLM_OCR_BACKEND,
) -> tuple[str, bool]:
    if cache_path.is_file() and not force_refresh:
        return cache_path.read_text(encoding="utf-8"), True
    markdown = extract_invoice_pdf4llm_markdown(pdf_path, use_ocr=use_ocr, ocr_backend=ocr_backend)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(markdown, encoding="utf-8")
    return markdown, False


@dataclass(frozen=True)
class Pdf4llmWorkerJob:
    pdf_path_str: str
    cache_path_str: str
    force_refresh: bool
    ocr_backend: Pdf4llmOcrBackend = PDF4LLM_OCR_BACKEND


@dataclass(frozen=True)
class Pdf4llmMarkdownResult:
    markdown: str
    duration_s: float
    error: str
    page_count: int
    markdown_cached: bool


def pdf4llm_markdown_worker(job: Pdf4llmWorkerJob) -> Pdf4llmMarkdownResult:
    pdf_path = Path(job.pdf_path_str)
    cache_path = Path(job.cache_path_str)
    t0 = time.perf_counter()
    try:
        markdown, from_cache = extract_invoice_pdf4llm_markdown_cached(
            pdf_path,
            cache_path,
            force_refresh=job.force_refresh,
            ocr_backend=job.ocr_backend,
        )
        duration = round(time.perf_counter() - t0, 3)
        return Pdf4llmMarkdownResult(
            markdown=markdown,
            duration_s=duration,
            error="",
            page_count=page_count(pdf_path),
            markdown_cached=from_cache,
        )
    except Exception as e:
        duration = round(time.perf_counter() - t0, 3)
        return Pdf4llmMarkdownResult(
            markdown="",
            duration_s=duration,
            error=repr(e),
            page_count=page_count(pdf_path),
            markdown_cached=False,
        )
