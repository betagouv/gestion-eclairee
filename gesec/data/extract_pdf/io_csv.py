"""Écriture des CSV de résultats."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from gesec.data.extract_pdf.schemas import EnteteCsvRow, LigneCsvRow, TimingsCsvRow

ENTETE_FIELDNAMES = [
    "run_id",
    "id_cpro",
    "pdf_filename",
    "objet_facture",
]

LIGNE_FIELDNAMES = [
    "run_id",
    "id_cpro",
    "pdf_filename",
    "source",
    "line_id",
    "item_name",
    "item_description",
    "item_reference",
    "quantity",
    "quantity_unit_code",
    "unit_price",
    "line_amount_excl_tax",
    "line_amount_incl_tax",
    "line_amount_vat",
    "currency",
]

TIMINGS_FIELDNAMES = [
    "run_id",
    "id_cpro",
    "pdf_filename",
    "duration_ocr_s",
    "duration_text_or_render_s",
    "duration_llm_s",
    "duration_total_s",
    "page_count",
    "ocr_cached",
    "error",
    "llm_prompt_tokens",
    "llm_completion_tokens",
    "extraction_model",
]


def _serialize_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _row_to_csv_dict(row: EnteteCsvRow | LigneCsvRow | TimingsCsvRow) -> dict[str, str]:
    return {key: _serialize_value(getattr(row, key)) for key in row.model_fields}


def write_entete_rows(path: Path, rows: Sequence[EnteteCsvRow]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.is_file() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ENTETE_FIELDNAMES)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(_row_to_csv_dict(row))


def write_ligne_rows(path: Path, rows: Sequence[LigneCsvRow]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.is_file() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LIGNE_FIELDNAMES)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(_row_to_csv_dict(row))


def write_timings_rows(path: Path, rows: Sequence[TimingsCsvRow]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.is_file() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TIMINGS_FIELDNAMES)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(_row_to_csv_dict(row))
