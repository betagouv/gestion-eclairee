"""Utilitaires PDF : identifiant, listage, rendu."""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pymupdf

_ID_CPRO_RE = re.compile(r"^(\d+)_")


def parse_id_cpro(filename: str | Path) -> str:
    name = Path(filename).name
    match = _ID_CPRO_RE.match(name)
    if not match:
        raise ValueError(f"Impossible d'extraire id_cpro du nom de fichier : {name!r}")
    return match.group(1)


def list_pdf_paths(factures_dir: Path) -> list[Path]:
    if not factures_dir.is_dir():
        return []
    return sorted(p for p in factures_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")


def page_count(pdf_path: Path) -> int:
    with pymupdf.open(pdf_path) as doc:
        return doc.page_count


def skip_too_many_pages_error(*, page_count: int, max_pages: int) -> str:
    return f"skipped: {page_count} pages > max {max_pages}"


def pdf_within_page_limit(pdf_path: Path, max_pages: int) -> bool:
    return page_count(pdf_path) <= max_pages


def png_bytes_to_data_uri(png_bytes: bytes) -> str:
    encoded = base64.standard_b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"
