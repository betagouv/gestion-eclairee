"""Chemins et constantes par défaut du paquet extract_pdf."""

from __future__ import annotations

import os
from pathlib import Path

PDF4LLM_MD_SUBDIR = "pdf4llm"
FACTURES_DIRNAME = "factures"
OCR_DIRNAME = "facture_ocr"

SOURCE = "extract_pdf"

OCR_MODEL = "openweight-ocr"
EXTRACTION_MODEL = "gpt-oss-120b"

OCR_MAX_TOKENS = 8192
OCR_LLM_TIMEOUT = 300.0
EXTRACTION_LLM_TIMEOUT = 180.0
DEFAULT_MAX_WORKERS = 5
MAX_PAGES = 50

LIGNES_CSV_NAME = "extract_pdf_lignes.csv"
ENTETE_CSV_NAME = "extract_pdf_entete.csv"
TIMINGS_CSV_NAME = "extract_pdf_timings.csv"

PDF4LLM_USE_OCR = True
PDF4LLM_OCR_DPI = 300
PDF4LLM_OCR_LANGUAGE = "fra+eng"
PDF4LLM_OCR_BACKEND = "lighton"
PDF4LLM_OCR_BACKENDS = ("lighton", "tesseract")
PDF4LLM_MD_MAX_WORKERS = max(1, min(4, os.cpu_count() or 2))

_MISSING_DATA_ROOT = (
    "Définir EXTRACT_PDF_DATA_ROOT dans l'env (répertoire hors dépôt) "
    "ou passer --factures-dir, --ocr-dir et --output-dir."
)


def resolve_data_paths(
    *,
    factures_dir: Path | str | None,
    ocr_dir: Path | str | None,
    output_dir: Path | str | None,
) -> tuple[Path, Path, Path]:
    from django.conf import settings

    root_raw = getattr(settings, "EXTRACT_PDF_DATA_ROOT", "") or ""
    data_root = Path(root_raw) if root_raw else None

    if factures_dir is not None:
        factures_path = Path(factures_dir)
    elif data_root is not None:
        factures_path = data_root / FACTURES_DIRNAME
    else:
        raise ValueError(_MISSING_DATA_ROOT)

    if ocr_dir is not None:
        ocr_path = Path(ocr_dir)
    elif data_root is not None:
        ocr_path = data_root / OCR_DIRNAME
    else:
        raise ValueError(_MISSING_DATA_ROOT)

    if output_dir is not None:
        output_path = Path(output_dir)
    elif data_root is not None:
        output_path = data_root
    else:
        raise ValueError(_MISSING_DATA_ROOT)

    return factures_path, ocr_path, output_path
