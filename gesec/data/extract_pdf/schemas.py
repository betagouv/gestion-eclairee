"""Modèles Pydantic pour l'extraction et l'export CSV."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from gesec.data.extract_pdf.paths import SOURCE


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


class ExtractTimings(BaseModel):
    duration_ocr_s: float = 0.0
    duration_text_or_render_s: float = 0.0
    duration_llm_s: float = 0.0
    duration_total_s: float = 0.0
    page_count: int = 0
    ocr_cached: bool = False
    error: str = ""
    llm_usage: Optional[dict[str, int]] = None


class EnteteCsvRow(BaseModel):
    run_id: str
    id_cpro: str
    pdf_filename: str
    objet_facture: str | None = None

    @classmethod
    def from_extraction(
        cls,
        *,
        run_id: str,
        id_cpro: str,
        pdf_filename: str,
        facture: ExtractedFacture,
    ) -> EnteteCsvRow:
        return cls(
            run_id=run_id,
            id_cpro=id_cpro,
            pdf_filename=pdf_filename,
            objet_facture=facture.objet_facture,
        )


class LigneCsvRow(BaseModel):
    run_id: str
    id_cpro: str
    pdf_filename: str
    source: str
    line_id: str
    item_name: str
    item_description: str
    item_reference: Optional[str]
    quantity: Optional[Decimal]
    quantity_unit_code: str
    unit_price: Optional[Decimal]
    line_amount_excl_tax: Optional[Decimal]
    line_amount_incl_tax: Optional[Decimal]
    line_amount_vat: Optional[Decimal]
    currency: str

    @classmethod
    def from_extraction(
        cls,
        *,
        run_id: str,
        id_cpro: str,
        pdf_filename: str,
        ligne: ExtractedLigne,
    ) -> LigneCsvRow:
        return cls(
            run_id=run_id,
            id_cpro=id_cpro,
            pdf_filename=pdf_filename,
            source=SOURCE,
            line_id=ligne.line_id,
            item_name=ligne.item_name,
            item_description=ligne.item_description,
            item_reference=ligne.item_reference,
            quantity=ligne.quantity,
            quantity_unit_code=ligne.quantity_unit_code,
            unit_price=ligne.unit_price,
            line_amount_excl_tax=ligne.line_amount_excl_tax,
            line_amount_incl_tax=ligne.line_amount_incl_tax,
            line_amount_vat=ligne.line_amount_vat,
            currency=ligne.currency,
        )


class TimingsCsvRow(BaseModel):
    run_id: str
    id_cpro: str
    pdf_filename: str
    duration_ocr_s: float
    duration_text_or_render_s: float
    duration_llm_s: float
    duration_total_s: float
    page_count: int
    ocr_cached: bool
    error: str
    llm_prompt_tokens: Optional[int] = None
    llm_completion_tokens: Optional[int] = None
    extraction_model: str = ""

    @classmethod
    def from_timings(
        cls,
        *,
        run_id: str,
        id_cpro: str,
        pdf_filename: str,
        timings: ExtractTimings,
        extraction_model: str = "",
    ) -> TimingsCsvRow:
        usage = timings.llm_usage or {}
        return cls(
            run_id=run_id,
            id_cpro=id_cpro,
            pdf_filename=pdf_filename,
            duration_ocr_s=timings.duration_ocr_s,
            duration_text_or_render_s=timings.duration_text_or_render_s,
            duration_llm_s=timings.duration_llm_s,
            duration_total_s=timings.duration_total_s,
            page_count=timings.page_count,
            ocr_cached=timings.ocr_cached,
            error=timings.error,
            llm_prompt_tokens=usage.get("prompt_tokens"),
            llm_completion_tokens=usage.get("completion_tokens"),
            extraction_model=extraction_model,
        )
