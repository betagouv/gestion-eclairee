"""Extraction Markdown PyMuPDF4LLM et cache S3."""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

import pymupdf
import pymupdf4llm
from pymupdf4llm.helpers import utils as pdf4llm_utils

from gesec.data.extract_pdf.ocr_lighton import LightonOcrClient, OpenWeightOcrClient
from gesec.data.extract_pdf.paths import (
    OCR_LLM_TIMEOUT,
    OCR_MODEL,
    PDF4LLM_OCR_DPI,
    PDF4LLM_USE_OCR,
    markdown_storage_path,
)
from gesec.data.extract_pdf.pdf_utils import page_count, png_bytes_to_data_uri, sha256_bytes, sha256_file
from gesec.data.extract_pdf.schemas import PdfErrorType, PdfExtractionStatus

logger = logging.getLogger(__name__)


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
    client = ocr_client
    parts: list[str] = []
    with pymupdf.open(pdf_path) as doc:
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            page.remove_rotation()
            page_number = page_index + 1
            if use_ocr and pdf4llm_utils.analyze_page(page).get("needs_ocr"):
                if client is None:
                    client = build_lighton_ocr_client()
                text = client.ocr_image_data_uri(_page_png_data_uri(page)).rstrip()
                parts.append(f"--- page {page_number} ---\n{text}")
            else:
                parts.append(_markdown_for_page_native(doc, page_index))
    return "\n\n".join(parts)


def extract_invoice_pdf4llm_markdown(
    pdf_path: Path,
    *,
    ocr_client: LightonOcrClient | None = None,
    use_ocr: bool = PDF4LLM_USE_OCR,
) -> str:
    return extract_invoice_pdf4llm_markdown_lighton(pdf_path, ocr_client=ocr_client, use_ocr=use_ocr)


@dataclass(frozen=True)
class PdfMarkdownResult:
    markdown: str
    duration_s: float
    page_count: int
    pdf_sha256: str | None
    markdown_sha256: str | None
    markdown_cached: bool
    markdown_path: str
    status: PdfExtractionStatus | None = None
    error: str = ""
    error_type: PdfErrorType | None = None


def _read_markdown(path: str) -> str:
    with default_storage.open(path, "rb") as handle:
        return handle.read().decode("utf-8")


def _write_markdown(path: str, markdown: str) -> None:
    if default_storage.exists(path):
        default_storage.delete(path)
    default_storage.save(path, ContentFile(markdown.encode("utf-8")))


def extract_pdf_markdown(
    *,
    id_cpro: str,
    pdf_path: str,
    pdf_filename: str,
    ocr_client: LightonOcrClient,
    force_refresh: bool,
    max_pages: int,
) -> PdfMarkdownResult:
    """Télécharge le PDF, produit ou relit le Markdown S3, sans appeler le LLM d'extraction."""
    markdown_path = markdown_storage_path(id_cpro, pdf_filename)
    started = time.perf_counter()

    with tempfile.TemporaryDirectory() as tmp_dir:
        local_pdf = Path(tmp_dir) / Path(pdf_filename).name
        try:
            with default_storage.open(pdf_path, "rb") as source, local_pdf.open("wb") as target:
                shutil.copyfileobj(source, target)
        except Exception as e:
            logger.warning("Téléchargement S3 impossible pour %s : %s", id_cpro, e)
            return PdfMarkdownResult(
                markdown="",
                duration_s=round(time.perf_counter() - started, 3),
                page_count=0,
                pdf_sha256=None,
                markdown_sha256=None,
                markdown_cached=False,
                markdown_path=markdown_path,
                status="failed",
                error=repr(e),
                error_type="s3",
            )

        try:
            pdf_sha256 = sha256_file(local_pdf)
            pages = page_count(local_pdf)
        except Exception as e:
            logger.warning("Lecture PDF impossible pour %s : %s", id_cpro, e)
            return PdfMarkdownResult(
                markdown="",
                duration_s=round(time.perf_counter() - started, 3),
                page_count=0,
                pdf_sha256=None,
                markdown_sha256=None,
                markdown_cached=False,
                markdown_path=markdown_path,
                status="failed",
                error=repr(e),
                error_type="parse",
            )

        if pages > max_pages:
            return PdfMarkdownResult(
                markdown="",
                duration_s=round(time.perf_counter() - started, 3),
                page_count=pages,
                pdf_sha256=pdf_sha256,
                markdown_sha256=None,
                markdown_cached=False,
                markdown_path=markdown_path,
                status="too_large",
                error=f"{pages} pages > max {max_pages}",
            )

        if not force_refresh and default_storage.exists(markdown_path):
            try:
                markdown = _read_markdown(markdown_path)
            except Exception as e:
                logger.warning("Lecture du cache Markdown impossible pour %s : %s", id_cpro, e)
            else:
                return PdfMarkdownResult(
                    markdown=markdown,
                    duration_s=round(time.perf_counter() - started, 3),
                    page_count=pages,
                    pdf_sha256=pdf_sha256,
                    markdown_sha256=sha256_bytes(markdown.encode("utf-8")),
                    markdown_cached=True,
                    markdown_path=markdown_path,
                )

        try:
            markdown = extract_invoice_pdf4llm_markdown(local_pdf, ocr_client=ocr_client)
        except Exception as e:
            logger.warning("OCR/Markdown impossible pour %s : %s", id_cpro, e)
            return PdfMarkdownResult(
                markdown="",
                duration_s=round(time.perf_counter() - started, 3),
                page_count=pages,
                pdf_sha256=pdf_sha256,
                markdown_sha256=None,
                markdown_cached=False,
                markdown_path=markdown_path,
                status="failed",
                error=repr(e),
                error_type="ocr",
            )

        try:
            _write_markdown(markdown_path, markdown)
        except Exception as e:
            logger.warning("Écriture du Markdown S3 impossible pour %s : %s", id_cpro, e)
            return PdfMarkdownResult(
                markdown=markdown,
                duration_s=round(time.perf_counter() - started, 3),
                page_count=pages,
                pdf_sha256=pdf_sha256,
                markdown_sha256=sha256_bytes(markdown.encode("utf-8")),
                markdown_cached=False,
                markdown_path=markdown_path,
                status="failed",
                error=repr(e),
                error_type="s3",
            )

        return PdfMarkdownResult(
            markdown=markdown,
            duration_s=round(time.perf_counter() - started, 3),
            page_count=pages,
            pdf_sha256=pdf_sha256,
            markdown_sha256=sha256_bytes(markdown.encode("utf-8")),
            markdown_cached=False,
            markdown_path=markdown_path,
        )
