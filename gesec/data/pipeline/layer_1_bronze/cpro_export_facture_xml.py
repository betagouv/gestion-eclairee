"""Insert facture xml in DB"""

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal

from django.conf import settings
from django.core.files.storage import default_storage

from sqlalchemy import text
from tqdm import tqdm
from xmlschema import XMLSchema, XMLSchemaValidationError

from gesec.data.pipeline.db import execute_sql, save_list_pydantic
from gesec.data.pipeline.layer_1_bronze.schemas import BronzeCproExportFactureXml, BronzeCproExportFactureXmlStatus

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "bronze_" + __name__.split(".")[-1]


def get_xsd_schema_path(version: str) -> str:
    path = settings.BASE_DIR / f"gesec/data/processors/cpro/models/xsd/UBL-{version}/maindoc/UBL-Invoice-{version}.xsd"
    if not os.path.exists(path):
        raise ValueError(f"Unknown xsd version {version}")
    return path


def get_xsd_schema(version: str) -> XMLSchema:
    path = get_xsd_schema_path(version)
    return XMLSchema(path)


def detect_schema_version(xml: str) -> str | None:
    version = None
    re_tag_version = re.compile("<cbc:UBLVersionID>(.*?)</cbc:UBLVersionID>")
    tags_2 = [
        'xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"',
    ]
    tags_2_0 = [
        "UBL-Invoice-2.0.xsd",
    ]

    xml_header = xml[:2000]

    t = re_tag_version.search(xml_header)
    if t:
        version = t.group(1)

    # Si la version n'a pas pu être déterminée via UBLVersionID, test avec des chaines hardcodées
    if version is None:
        for tag_version, tag_list in [("2.0", tags_2_0), ("2", tags_2)]:
            for tag in tag_list:
                if tag in xml_header:
                    version = tag_version
                    break

    return version


def load_file(id_cpro: str, file_path: str, schema: XMLSchema = None) -> BronzeCproExportFactureXml:
    if schema is None:
        schema = get_xsd_schema("2.4")

    with default_storage.open(file_path, "r") as f:
        xml = f.read()

    schema_version = detect_schema_version(xml)
    if schema_version is None:
        raise ValueError(f"Cannot determine schema version for {id_cpro} {file_path}")

    # Nettoyage des tags vides
    xml = xml.replace('<cbc:AllowanceTotalAmount currencyID="EUR"/>', "")
    xml = xml.replace('<cbc:Amount currencyID="EUR"/>', '<cbc:Amount currencyID="EUR">0.0</cbc:Amount>')

    try:
        content = schema.to_dict(xml)
    except XMLSchemaValidationError:
        raise

    return BronzeCproExportFactureXml(
        id_cpro=id_cpro,
        xml_schema=f"UBL-Invoice-{schema_version}",
        content=content,
    )


def get_ids_cpro_for_ministere(ministere: str) -> list[str]:
    rows = execute_sql(
        text("select identifiant_chorus_pro from gesec_facture where ministere = :ministere"),
        {"ministere": ministere},
    )
    return [row.identifiant_chorus_pro for row in rows]


def filter_files(directory: str, ids_cpro: list[str] | None = None) -> list[tuple[str, str]]:
    """Renvoie la liste (id_cpro, path) des fichiers factures xml."""
    result = []
    facture_folders, _ = default_storage.listdir(directory)
    for facture_folder in tqdm(facture_folders, "Recherche des factures XML"):
        id_cpro = re.match(r".*facture_(\d+)", facture_folder).group(1)
        if ids_cpro is not None:
            if id_cpro not in ids_cpro:
                continue
        pivot_dir = os.path.join(directory, facture_folder, "pivot")
        _, files = default_storage.listdir(pivot_dir)
        for file in files:
            if file.endswith(".xml") and not file.endswith(".factur-x.xml"):
                filepath = os.path.join(pivot_dir, file)
                result.append((id_cpro, filepath))
    return result


def build_rows(
    files, n_workers: int | None = None
) -> tuple[list[BronzeCproExportFactureXml], list[BronzeCproExportFactureXmlStatus]]:

    all_rows = []
    all_status = []

    if n_workers is None:
        if settings.STORAGE_BACKEND == "s3":
            n_workers = 10
        else:
            n_workers = 1

    schema = get_xsd_schema("2.4")
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = {
            executor.submit(load_file, id_cpro, filepath, schema): (id_cpro, filepath) for id_cpro, filepath in files
        }

        for future in tqdm(as_completed(futures), total=len(files), desc="Chargement des factures XML"):
            id_cpro, filepath = futures[future]
            try:
                result = future.result()
                all_rows.append(result)
                all_status.append(
                    BronzeCproExportFactureXmlStatus(
                        id_cpro=result.id_cpro,
                        status="Ok",
                    )
                )
            except XMLSchemaValidationError as e:
                id_cpro, filepath = futures[future]
                logger.warning("Validation Error for %s %s: %s", id_cpro, filepath, (e.reason, e.path))
                all_status.append(
                    BronzeCproExportFactureXmlStatus(
                        id_cpro=result.id_cpro,
                        status="Validation error",
                        status_details=f"Path: {e.path}\nReason: {e.reason}\n{e}",
                    )
                )
            except Exception as e:
                logger.error(f"Failed to process {id_cpro} {filepath}: {e}")
                raise

    logger.info(f"Aggregated {len(files)} files with {len(all_rows)} total rows")
    return all_rows, all_status


def clean_decimals(obj: dict) -> dict:
    if isinstance(obj, Decimal):
        return str(obj)
    elif isinstance(obj, dict):
        return {k: clean_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple, set)):
        return type(obj)(clean_decimals(item) for item in obj)
    return obj


def export_to_database(
    rows: list[BronzeCproExportFactureXml],
    rows_status: list[BronzeCproExportFactureXmlStatus],
    table_name: str = DEFAULT_TABLE_NAME,
) -> None:
    if not rows:
        logger.warning("No data to export, skipping database insertion")
        return

    logger.info(f"Exporting {len(rows)} rows to table '{table_name}' using SQLAlchemy")

    for row in rows:
        row.content = clean_decimals(row.content)
    save_list_pydantic(rows, table_name, if_exists="replace")
    save_list_pydantic(rows_status, table_name + "_status", if_exists="replace")

    logger.info(f"Successfully exported {len(rows)} rows to '{table_name}'")


def process_files_to_bronze(
    directory: str,
    table_name: str = DEFAULT_TABLE_NAME,
    n_workers: int | None = None,
    ids_cpro: list[str] | None = None,
    ministere: str | None = None,
) -> None:
    """
    Args:
        ids_cpro: Traite uniquement les factures avec ces ids
        ministere: Traite uniquement les factures rattachées à ce ministère
    """
    if (ministere is not None) and (ids_cpro is not None):
        raise ValueError("Either ministere or ids_cpro may be provided")
    if ministere is not None:
        ids_cpro = get_ids_cpro_for_ministere(ministere)

    # Filter CSV files matching the pattern
    files = filter_files(directory, ids_cpro)

    logger.info(f"Found {len(files)} matching facture XML files")
    for id_cpro, filepath in files:
        logger.debug(f"  - {id_cpro} {os.path.basename(filepath)}")

    # Aggregate all CSV files
    rows, rows_status = build_rows(files, n_workers=n_workers)

    # Export to database
    export_to_database(rows, rows_status, table_name=table_name)

    logger.info("Operation completed successfully")
