"""Modèles Pydantic de l'extraction PDF et du bronze persistant."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

PdfExtractionStatus = Literal["success", "failed", "header_missing", "no_pdf", "no_lines", "too_large"]
PdfErrorType = Literal["ocr", "llm", "s3", "parse"]

ERROR_STATUSES: tuple[PdfExtractionStatus, ...] = (
    "failed",
    "header_missing",
    "no_pdf",
    "no_lines",
    "too_large",
)


class ExtractedLigne(BaseModel):
    line_id: str = ""
    item_name: str = ""
    item_description: str = ""
    item_reference: Optional[str] = None
    quantity: Optional[Decimal] = None
    quantity_unit_code: str = ""
    unit_price: Optional[Decimal] = None
    line_amount_excl_tax: Optional[Decimal] = None
    line_amount_incl_tax: Optional[Decimal] = None
    line_amount_vat: Optional[Decimal] = None
    currency: str = "EUR"


class ExtractedFacture(BaseModel):
    objet_facture: str | None = None
    lignes: list[ExtractedLigne] = Field(default_factory=list)


class BronzeExtractPdf(BaseModel):
    """Ligne de la table persistante `bronze_extract_pdf`."""

    id_cpro: str
    status: PdfExtractionStatus
    content: Optional[dict[str, Any]] = None
    pdf_path: Optional[str] = None
    pdf_filename: Optional[str] = None
    pdf_sha256: Optional[str] = None
    markdown_path: Optional[str] = None
    markdown_sha256: Optional[str] = None
    page_count: Optional[int] = None
    extraction_model: Optional[str] = None
    prompt_version: Optional[str] = None
    error_type: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0
    last_attempt_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
