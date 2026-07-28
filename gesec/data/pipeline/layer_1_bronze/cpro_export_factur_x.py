"""Insert factur-x in DB"""

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from typing import Literal

from django.conf import settings
from django.core.files.storage import default_storage

from tqdm import tqdm
from xmlschema import XMLSchema, XMLSchemaException, XMLSchemaValidationError

from gesec.data.pipeline.db import save_list_pydantic

from .schemas import BronzeCproExportFacturX, BronzeCproExportFacturXStatus
from .utils import get_ids_cpro_for_ministere

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "bronze_" + __name__.split(".")[-1]
DEFAULT_SCHEMA_PROFILE = "EN16931"
DEFAULT_SCHEMA_VERSION = "1.09"
XsdProfile = Literal["MINIMUM", "EN16931"]


def get_xsd_schema_path(profile: XsdProfile, version: str) -> str:
    path = (
        settings.BASE_DIR
        / f"gesec/data/processors/cpro/models/xsd/Factur-X_{version}_{profile}/Factur-X_{version}_{profile}.xsd"
    )
    if not os.path.exists(path):
        raise ValueError(f"Unknown xsd {profile} {version}")
    return path


def get_xsd_schema(profile: XsdProfile, version: str) -> XMLSchema:
    path = get_xsd_schema_path(profile, version)
    return XMLSchema(path)


def detect_schema_version(xml: str) -> tuple[str, str]:
    return DEFAULT_SCHEMA_PROFILE, DEFAULT_SCHEMA_VERSION


def load_file(id_cpro: str, file_path: str, schema: XMLSchema = None) -> BronzeCproExportFacturX:
    if schema is None:
        schema = get_xsd_schema(DEFAULT_SCHEMA_PROFILE, DEFAULT_SCHEMA_VERSION)

    with default_storage.open(file_path, "r") as f:
        xml = f.read()

    schema_profile, schema_version = detect_schema_version(xml)

    content, errors = schema.to_dict(xml, validation="lax")
    str_errors = ""
    for err in errors:
        if isinstance(err, XMLSchemaValidationError):
            str_errors += f"Path: {err.path}, Reason: {err.reason}\n"
        else:
            str_errors += repr(err) + "\n"

    return BronzeCproExportFacturX(
        id_cpro=id_cpro,
        xml_schema=f"Factur-X_{schema_version}_{schema_profile}",
        content=content,
        errors=str_errors,
    )


def filter_files(directory: str, ids_cpro: list[str] | None = None) -> list[tuple[str, str]]:
    """Renvoie la liste (id_cpro, path) des fichiers factur-x."""
    result = []
    facture_folders, _ = default_storage.listdir(directory)
    for facture_folder in tqdm(facture_folders, "Recherche des factur-x"):
        id_cpro = re.match(r".*facture_(\d+)", facture_folder).group(1)
        if ids_cpro is not None:
            if id_cpro not in ids_cpro:
                continue
        pivot_dir = os.path.join(directory, facture_folder, "pivot")
        _, files = default_storage.listdir(pivot_dir)
        for file in files:
            if file.endswith(".factur-x.xml"):
                filepath = os.path.join(pivot_dir, file)
                result.append((id_cpro, filepath))
    return result


def build_rows(
    files, n_workers: int | None = None
) -> tuple[list[BronzeCproExportFacturX], list[BronzeCproExportFacturXStatus]]:

    all_rows = []
    all_status = []

    if n_workers is None:
        if settings.STORAGE_BACKEND == "s3":
            n_workers = 10
        else:
            n_workers = 1

    schema = get_xsd_schema(DEFAULT_SCHEMA_PROFILE, DEFAULT_SCHEMA_VERSION)
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = {
            executor.submit(load_file, id_cpro, filepath, schema): (id_cpro, filepath) for id_cpro, filepath in files
        }

        for future in tqdm(as_completed(futures), total=len(files), desc="Chargement des facture-x"):
            id_cpro, filepath = futures[future]
            try:
                result = future.result()
                all_rows.append(result)
                all_status.append(
                    BronzeCproExportFacturXStatus(
                        id_cpro=id_cpro,
                        status="Ok",
                    )
                )
            except XMLSchemaException as e:
                id_cpro, filepath = futures[future]
                if isinstance(e, XMLSchemaValidationError):
                    status = "Validation error"
                    details = f"Path: {e.path} Reason: {e.reason}\n{e}"
                else:
                    status = str(e.__class__.__name__)
                    details = str(e)
                logger.warning("Validation Error for %s %s: %s", id_cpro, filepath, details)
                all_status.append(
                    BronzeCproExportFacturXStatus(
                        id_cpro=id_cpro,
                        status=status,
                        status_details=details,
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
    rows: list[BronzeCproExportFacturX],
    rows_status: list[BronzeCproExportFacturXStatus],
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

    logger.info(f"Found {len(files)} matching factur-x files")
    for id_cpro, filepath in files:
        logger.debug(f"  - {id_cpro} {os.path.basename(filepath)}")

    # Aggregate all CSV files
    rows, rows_status = build_rows(files, n_workers=n_workers)

    # Export to database
    export_to_database(rows, rows_status, table_name=table_name)

    logger.info("Operation completed successfully")
