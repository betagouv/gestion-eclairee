import logging
from typing import Optional

from gesec.data.pipeline.db import load_rows_from_table, save_list_pydantic
from gesec.data.pipeline.layer_1_bronze.cpro_export_facture_xml import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME
from gesec.data.pipeline.layer_1_bronze.schemas import BronzeCproExportFactureXml

from .schemas import SilverCproExportFactureXmlFacture

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]


def extract_numero(content: dict) -> Optional[str]:
    value = content.get("cbc:ID")
    if isinstance(value, dict):
        value = value.get("$")
    if value is None:
        return None
    return str(value)


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
