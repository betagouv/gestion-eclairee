"""Chemins et constantes du paquet extract_pdf."""

from __future__ import annotations

import os

UNZIPPED_PREFIX = "cpro/factures_unzipped"
EXTRACT_PDF_PREFIX = "cpro/extract_pdf"

SOURCE = "extract_pdf"

OCR_MODEL = "openweight-ocr"
EXTRACTION_MODEL = "gpt-oss-120b"
PROMPT_VERSION = "extract_pdf_v1"

OCR_MAX_TOKENS = 8192
OCR_LLM_TIMEOUT = 300.0
EXTRACTION_LLM_TIMEOUT = 180.0
DEFAULT_MAX_WORKERS = 5
MAX_PAGES = 50

PDF4LLM_USE_OCR = True
PDF4LLM_OCR_DPI = 300
PDF4LLM_MD_MAX_WORKERS = max(1, min(4, os.cpu_count() or 2))


def markdown_storage_path(id_cpro: str, pdf_filename: str) -> str:
    return f"{EXTRACT_PDF_PREFIX}/facture_{id_cpro}/{pdf_filename}.md"
