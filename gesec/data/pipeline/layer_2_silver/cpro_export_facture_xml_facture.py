import logging
import re
from typing import Optional

from gesec.data.pipeline.db import load_rows_from_table, save_list_pydantic
from gesec.data.pipeline.layer_1_bronze.cpro_export_facture_xml import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME
from gesec.data.pipeline.layer_1_bronze.schemas import BronzeCproExportFactureXml

from .schemas import SilverCproExportFactureXmlFacture

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]

RE_REFERENCE_UGAP = re.compile(r"Référence UGAP\s*:\s*(\d+)")


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
    identifiers: list[str] = []
    for item in deliveries:
        value = item.get("cbc:ID")
        if isinstance(value, dict):
            value = value.get("$")
        if value is None or not str(value).strip():
            continue
        identifiers.append(str(value))
    if not identifiers:
        return None
    if len(set(identifiers)) > 1:
        logger.warning(f"Multiple distinct cac:Delivery cbc:ID, keeping first: {identifiers}")
    return identifiers[0]


def extract_reference_ugap(content: dict) -> Optional[str]:
    notes = content.get("cbc:Note")
    if notes is None:
        return None
    if isinstance(notes, (str, dict)):
        notes = [notes]
    elif not isinstance(notes, list):
        return None
    for note in notes:
        if isinstance(note, dict):
            note = note.get("$")
        if not isinstance(note, str):
            continue
        match = RE_REFERENCE_UGAP.search(note)
        if match is not None:
            return match.group(1).lstrip("0") or "0"
    return None


def transform_to_silver(bronze_factures: list[BronzeCproExportFactureXml]) -> list[SilverCproExportFactureXmlFacture]:
    result = []
    for bronze in bronze_factures:
        numero = extract_numero(bronze.content)
        if numero is None:
            logger.warning(f"No cbc:ID for {bronze.id_cpro}, skipping")
            continue
        result.append(
            SilverCproExportFactureXmlFacture(
                id_cpro=bronze.id_cpro,
                xml_schema=bronze.xml_schema,
                numero=numero,
                delivery_id=extract_delivery_id(bronze.content),
                reference_ugap=extract_reference_ugap(bronze.content),
            )
        )
    return result


def process_to_silver(
    bronze_table_name: str = BRONZE_DEFAULT_TABLE_NAME,
    silver_table_name: str = DEFAULT_TABLE_NAME,
) -> list[SilverCproExportFactureXmlFacture]:
    bronze_factures = load_rows_from_table(bronze_table_name, BronzeCproExportFactureXml)
    silver_factures = transform_to_silver(bronze_factures)

    if not silver_factures:
        logger.warning("No data to export, skipping database insertion")
        return silver_factures

    save_list_pydantic(silver_factures, silver_table_name, if_exists="replace")
    return silver_factures
