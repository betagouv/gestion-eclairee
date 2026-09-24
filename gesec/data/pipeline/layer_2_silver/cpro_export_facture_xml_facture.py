import logging
from typing import Optional

from gesec.data.pipeline.db import load_rows_from_table, save_list_pydantic
from gesec.data.pipeline.layer_1_bronze.cpro_export_facture_xml import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME
from gesec.data.pipeline.layer_1_bronze.schemas import BronzeCproExportFactureXml

from .schemas import SilverCproExportFactureXmlFacture, SilverCproExportFactureXmlFactureStatus

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]


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
    bronze_factures: list[BronzeCproExportFactureXml],
) -> tuple[list[SilverCproExportFactureXmlFacture], list[SilverCproExportFactureXmlFactureStatus]]:
    silver_factures: list[SilverCproExportFactureXmlFacture] = []
    silver_factures_status: list[SilverCproExportFactureXmlFactureStatus] = []
    for bronze in bronze_factures:
        try:
            numero = extract_numero(bronze.content)
            if numero is None:
                raise ValueError(f"No cbc:ID for {bronze.id_cpro}")
            silver_factures.append(
                SilverCproExportFactureXmlFacture(
                    id_cpro=bronze.id_cpro,
                    xml_schema=bronze.xml_schema,
                    numero=numero,
                    delivery=bronze.content.get("cac:Delivery"),
                    delivery_id=extract_delivery_id(bronze.content),
                    note=extract_note(bronze.content),
                )
            )
            silver_factures_status.append(SilverCproExportFactureXmlFactureStatus(id_cpro=bronze.id_cpro, status="Ok"))
        except Exception as e:
            logger.exception(f"Error processing facture {bronze.id_cpro}")
            silver_factures_status.append(
                SilverCproExportFactureXmlFactureStatus(
                    id_cpro=bronze.id_cpro,
                    status="Error",
                    status_details=repr(e),
                )
            )
    return silver_factures, silver_factures_status


def process_to_silver(
    bronze_table_name: str = BRONZE_DEFAULT_TABLE_NAME,
    silver_table_name: str = DEFAULT_TABLE_NAME,
) -> tuple[list[SilverCproExportFactureXmlFacture], list[SilverCproExportFactureXmlFactureStatus]]:
    bronze_factures = load_rows_from_table(bronze_table_name, BronzeCproExportFactureXml)
    silver_factures, silver_factures_status = transform_to_silver(bronze_factures)

    if not silver_factures:
        logger.warning("No data to export, skipping database insertion")
        return silver_factures, silver_factures_status

    save_list_pydantic(silver_factures, silver_table_name, if_exists="replace")
    if silver_factures_status:
        save_list_pydantic(silver_factures_status, silver_table_name + "_status", if_exists="replace")
    return silver_factures, silver_factures_status
