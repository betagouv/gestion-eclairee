import logging
from typing import Optional

from sqlalchemy import text
from tqdm import tqdm

from gesec.data.pipeline.db import (
    DEFAULT_BATCH_SIZE,
    TableWriter,
    create_engine,
    iter_rows_from_table,
)
from gesec.data.pipeline.layer_1_bronze.cpro_export_facture_xml import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME
from gesec.data.pipeline.layer_1_bronze.schemas import BronzeCproExportFactureXml

from .schemas import SilverCproExportFactureXmlFacture, SilverCproExportFactureXmlFactureStatus

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]


def count_bronze_rows(table_name: str) -> int:
    engine = create_engine()
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one()


def extract_numero(content: dict) -> Optional[str]:
    value = content.get("cbc:ID")
    if isinstance(value, dict):
        value = value.get("$")
    if value is None:
        return None
    return str(value)


def extract_delivery_id(content: dict) -> Optional[str]:
    delivery = content.get("cac:Delivery")
    if isinstance(delivery, list):
        deliveries = delivery
    elif isinstance(delivery, dict):
        deliveries = [delivery]
    else:
        return None
    for item in deliveries:
        if not isinstance(item, dict):
            continue
        value = item.get("cbc:ID")
        if isinstance(value, dict):
            value = value.get("$")
        if isinstance(value, str) and value.strip():
            return value
    return None


def extract_note(content: dict) -> str:
    notes = content.get("cbc:Note")
    if notes is None:
        return ""
    if isinstance(notes, (str, dict)):
        notes = [notes]
    elif not isinstance(notes, list):
        return ""
    result: list[str] = []
    for note in notes:
        if isinstance(note, dict):
            note = note.get("$")
        if isinstance(note, str) and note:
            result.append(note)
    return "\n".join(result)


def transform_to_silver(
    bronze: BronzeCproExportFactureXml,
) -> tuple[Optional[SilverCproExportFactureXmlFacture], SilverCproExportFactureXmlFactureStatus]:
    try:
        numero = extract_numero(bronze.content)
        if numero is None:
            raise ValueError(f"No cbc:ID for {bronze.id_cpro}")
        facture = SilverCproExportFactureXmlFacture(
            id_cpro=bronze.id_cpro,
            xml_schema=bronze.xml_schema,
            numero=numero,
            delivery=bronze.content.get("cac:Delivery"),
            delivery_id=extract_delivery_id(bronze.content),
            note=extract_note(bronze.content),
        )
        status = SilverCproExportFactureXmlFactureStatus(id_cpro=bronze.id_cpro, status="Ok")
    except Exception as e:
        logger.exception(f"Error processing facture {bronze.id_cpro}")
        facture = None
        status = SilverCproExportFactureXmlFactureStatus(id_cpro=bronze.id_cpro, status="Error", status_details=repr(e))
    return facture, status


def process_to_silver(
    bronze_table_name: str = BRONZE_DEFAULT_TABLE_NAME,
    silver_table_name: str = DEFAULT_TABLE_NAME,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
    total = count_bronze_rows(bronze_table_name)
    rows = iter_rows_from_table(bronze_table_name, BronzeCproExportFactureXml, batch_size=batch_size)
    factures_writer = TableWriter(silver_table_name, SilverCproExportFactureXmlFacture, batch_size=batch_size)
    status_writer = TableWriter(
        silver_table_name + "_status",
        SilverCproExportFactureXmlFactureStatus,
        batch_size=batch_size,
    )
    with factures_writer, status_writer:
        for bronze in tqdm(rows, total=total, desc="Transformation des factures XML en silver"):
            facture, status = transform_to_silver(bronze)
            if facture is not None:
                factures_writer.add(facture)
            status_writer.add(status)

    written = factures_writer.written
    if written:
        logger.info(f"Saved {written} rows in {silver_table_name}")
