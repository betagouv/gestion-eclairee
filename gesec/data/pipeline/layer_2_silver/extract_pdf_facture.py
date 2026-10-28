"""Transformation du bronze PDF en tables silver facture et ligne."""

from __future__ import annotations

import logging

from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy import text
from tqdm import tqdm

from gesec.data.extract_pdf.extract_llm import parse_extraction
from gesec.data.extract_pdf.result_table import TABLE_NAME as BRONZE_TABLE_NAME
from gesec.data.extract_pdf.schemas import BronzeExtractPdf, ExtractedFacture
from gesec.data.pipeline.db import (
    DEFAULT_BATCH_SIZE,
    TableWriter,
    create_engine,
    iter_rows_from_table,
)
from gesec.data.pipeline.layer_2_silver.extract_pdf_ligne import (
    DEFAULT_TABLE_NAME as LIGNE_TABLE_NAME,
)
from gesec.data.pipeline.layer_2_silver.extract_pdf_ligne import (
    transform_to_silver,
)
from gesec.data.pipeline.layer_2_silver.schemas import (
    SilverExtractPdfFacture,
    SilverExtractPdfLigne,
)

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]


def _facture_row(
    bronze: BronzeExtractPdf,
    *,
    status: str,
    objet_facture: str | None = None,
    error_type: str | None = None,
    error: str | None = None,
) -> SilverExtractPdfFacture:
    return SilverExtractPdfFacture(
        id_cpro=bronze.id_cpro,
        objet_facture=objet_facture,
        pdf_filename=bronze.pdf_filename,
        pdf_sha256=bronze.pdf_sha256,
        markdown_path=bronze.markdown_path,
        markdown_sha256=bronze.markdown_sha256,
        status=status,
        error_type=error_type,
        error=error,
    )


def transform_bronze(
    bronze: BronzeExtractPdf,
) -> tuple[SilverExtractPdfFacture, list[SilverExtractPdfLigne]]:
    if bronze.status not in ("success", "no_lines"):
        return (
            _facture_row(bronze, status=bronze.status, error_type=bronze.error_type, error=bronze.error),
            [],
        )

    try:
        facture: ExtractedFacture = parse_extraction(bronze.content)
    except Exception as e:
        logger.warning("JSON d'extraction illisible pour %s : %s", bronze.id_cpro, e)
        return _facture_row(bronze, status="failed", error_type="parse", error=repr(e)), []

    status = "success" if facture.lignes else "no_lines"
    row = _facture_row(bronze, status=status, objet_facture=facture.objet_facture)
    if not facture.lignes:
        return row, []

    if bronze.pdf_filename is None:
        error = f"pdf_filename absent pour {bronze.id_cpro}"
        return (
            _facture_row(bronze, status="failed", objet_facture=facture.objet_facture, error_type="parse", error=error),
            [],
        )

    lignes, error = transform_to_silver(
        facture,
        id_cpro=bronze.id_cpro,
        pdf_filename=bronze.pdf_filename,
    )
    if error is not None:
        logger.warning("Validation PDF échouée pour %s : %s", bronze.id_cpro, error)
        return (
            _facture_row(
                bronze, status="failed", objet_facture=facture.objet_facture, error_type="validation", error=error
            ),
            [],
        )

    return row, lignes


def process_to_silver(
    bronze_table_name: str = BRONZE_TABLE_NAME,
    facture_table_name: str = DEFAULT_TABLE_NAME,
    ligne_table_name: str = LIGNE_TABLE_NAME,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
    engine = create_engine()
    bronze_exists = sqlalchemy_inspect(engine).has_table(bronze_table_name)

    total = 0
    if bronze_exists:
        with engine.connect() as conn:
            total = conn.execute(text(f"SELECT count(*) FROM {bronze_table_name}")).scalar_one()

    rows = (
        iter_rows_from_table(bronze_table_name, BronzeExtractPdf, batch_size=batch_size) if bronze_exists else iter(())
    )
    facture_writer = TableWriter(facture_table_name, SilverExtractPdfFacture, batch_size=batch_size)
    ligne_writer = TableWriter(ligne_table_name, SilverExtractPdfLigne, batch_size=batch_size)

    with facture_writer, ligne_writer:
        for bronze in tqdm(rows, total=total, desc="Transformation des PDF en silver"):
            facture, lignes = transform_bronze(bronze)
            facture_writer.add(facture)
            ligne_writer.add_all(lignes)

    logger.info(
        "Silver PDF : %s factures, %s lignes",
        facture_writer.written,
        ligne_writer.written,
    )
