"""Utilitaires PDF : pages, hash et rendu."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pymupdf


def page_count(pdf_path: Path) -> int:
    with pymupdf.open(pdf_path) as doc:
        return doc.page_count


def pdf_within_page_limit(pdf_path: Path, max_pages: int) -> bool:
    return page_count(pdf_path) <= max_pages


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def png_bytes_to_data_uri(png_bytes: bytes) -> str:
    encoded = base64.standard_b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"
