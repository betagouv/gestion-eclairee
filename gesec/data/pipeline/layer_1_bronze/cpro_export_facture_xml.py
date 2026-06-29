"""Insert facture xml in DB"""

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal

from django.conf import settings
from django.core.files.storage import default_storage

from tqdm import tqdm
from xmlschema import XMLSchema

from gesec.data.pipeline.db import save_list_pydantic
from gesec.data.pipeline.layer_1_bronze.schemas import BronzeCproExportFactureXml

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "bronze_" + __name__.split(".")[-1]

schema_path = settings.BASE_DIR / "gesec/data/processors/cpro/models/xsd/UBL-2.0/maindoc/UBL-Invoice-2.0.xsd"


def get_xsd_schema_path(version: str) -> str:
    path = settings.BASE_DIR / f"gesec/data/processors/cpro/models/xsd/UBL-{version}/maindoc/UBL-Invoice-{version}.xsd"
    if not os.path.exists(path):
        raise ValueError(f"Unknown xsd version {version}")
    return path


def get_xsd_schema(version: str) -> XMLSchema:
    path = get_xsd_schema_path(version)
    return XMLSchema(path)


def get_xsd_schemas() -> dict[str, XMLSchema]:
    versions = ["2.0", "2.1"]
    return {
        version: get_xsd_schema(version)
        for version in versions
    }


def detect_schema_version(xml: str) -> str | None:
    tag_2_0 = 'schemaLocation="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2 ./xsd/maindoc/UBL-Invoice-2.0.xsd'
    tag_2_1 = '<cbc:UBLVersionID>2.1</cbc:UBLVersionID>'
    xml_header = xml[:2000]
    if tag_2_0 in xml_header:
        return "2.0"
    elif tag_2_1 in xml_header:
        return "2.1"
    else:
        return None


def load_file(id_cpro: str, file_path: str, schemas: dict[str, XMLSchema] = None) -> BronzeCproExportFactureXml:
    if schemas is None:
        schemas = get_xsd_schemas()

    with default_storage.open(file_path, "r") as f:
        xml = f.read()

    schema_version = detect_schema_version(xml)
    if schema_version is None:
        raise ValueError(f"Cannot determine schema version for {id_cpro} {file_path}")

    schema = schemas[schema_version]

    content = schema.to_dict(xml)

    return BronzeCproExportFactureXml(
        id_cpro=id_cpro,
        xml_schema=f"UBL-Invoice-{schema_version}",
        content=content,
    )


def filter_files(directory: str, ids_cpro: list[str] | None = None) -> list[tuple[str, str]]:
    """Renvoie la liste (id_cpro, path) des fichiers factures xml."""
    result = []
    facture_folders, _ = default_storage.listdir(directory)
    for facture_folder in tqdm(facture_folders, "Recherche des factures XML"):
        id_cpro = re.match(r"facture_(\d+)", facture_folder).group(1)
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


def build_rows(files, n_workers: int | None = None) -> list[BronzeCproExportFactureXml]:

    all_rows = []

    if n_workers is None:
        if settings.STORAGE_BACKEND == "s3":
            n_workers = 10
        else:
            n_workers = 1

    schemas = get_xsd_schemas()
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = {
            executor.submit(load_file, id_cpro, filepath, schemas): (id_cpro, filepath)
            for id_cpro, filepath in files
        }

        for future in tqdm(as_completed(futures), total=len(files), desc="Chargement des factures XML"):
            try:
                all_rows.append(future.result())
            except Exception as e:
                id_cpro, filepath = futures[future]
                logger.error(f"Failed to process {id_cpro} {filepath}: {e}")
                raise

    logger.info(f"Aggregated {len(files)} files with {len(all_rows)} total rows")
    return all_rows


def clean_decimals(obj: dict) -> dict:
    if isinstance(obj, Decimal):
        return str(obj)
    elif isinstance(obj, dict):
        return {k: clean_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple, set)):
        return type(obj)(clean_decimals(item) for item in obj)
    return obj


def export_to_database(rows: list[BronzeCproExportFactureXml], table_name: str = DEFAULT_TABLE_NAME) -> None:
    if not rows:
        logger.warning("No data to export, skipping database insertion")
        return

    logger.info(f"Exporting {len(rows)} rows to table '{table_name}' using SQLAlchemy")

    for row in rows:
        row.content = clean_decimals(row.content)
    save_list_pydantic(rows, table_name, if_exists="replace")

    logger.info(f"Successfully exported {len(rows)} rows to '{table_name}'")


def process_files_to_bronze(directory: str, table_name: str = DEFAULT_TABLE_NAME, n_workers: int | None = None, ids_cpro: list[str] | None = None) -> None:
    # Filter CSV files matching the pattern
    files = filter_files(directory, ids_cpro)

    logger.info(f"Found {len(files)} matching facture XML files")
    for id_cpro, filepath in files:
        logger.debug(f"  - {id_cpro} {os.path.basename(filepath)}")

    # Aggregate all CSV files
    rows = build_rows(files, n_workers=n_workers)

    if not rows:
        logger.warning("No data to export")
        return

    # Export to database
    export_to_database(rows, table_name=table_name)

    logger.info("Operation completed successfully")
