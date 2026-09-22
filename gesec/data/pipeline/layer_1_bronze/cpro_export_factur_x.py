"""Insert factur-x in DB"""

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from time import perf_counter
from typing import Any, Literal, cast

from django.conf import settings

from tqdm import tqdm
from xmlschema import XMLSchema, XMLSchemaException, XMLSchemaValidationError

from gesec.data.pipeline.db import save_list_pydantic
from gesec.storage import find_files

from ..utils import LoadTimings, read_xml_file, resolve_n_workers
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


def load_file(
    id_cpro: str,
    file_path: str,
    schema: XMLSchema | None = None,
    timings: LoadTimings | None = None,
) -> BronzeCproExportFacturX:
    if schema is None:
        schema = get_xsd_schema(DEFAULT_SCHEMA_PROFILE, DEFAULT_SCHEMA_VERSION)

    xml = read_xml_file(file_path, timings=timings)

    start = perf_counter()
    schema_profile, schema_version = detect_schema_version(xml)
    if timings is not None:
        timings.record("version", perf_counter() - start)

    start = perf_counter()
    content, errors = cast("tuple[Any, list[XMLSchemaValidationError]]", schema.to_dict(xml, validation="lax"))
    str_errors = ""
    for err in errors:
        if isinstance(err, XMLSchemaValidationError):
            str_errors += f"Path: {err.path}, Reason: {err.reason}\n"
        else:
            str_errors += repr(err) + "\n"
    if timings is not None:
        timings.record("parse", perf_counter() - start)

    start = perf_counter()
    row = BronzeCproExportFacturX(
        id_cpro=id_cpro,
        xml_schema=f"Factur-X_{schema_version}_{schema_profile}",
        content=content or {},
        errors=str_errors,
    )
    if timings is not None:
        timings.record("build", perf_counter() - start)
    return row


def filter_files(directory: str, ids_cpro: list[str] | None = None) -> list[tuple[str, str]]:
    """Renvoie la liste (id_cpro, path) des fichiers factur-x.

    Recherche récursive via le storage, puis retient les dossiers `pivot` des
    dossiers `facture_<id_cpro>`.
    """
    result = []
    ids = None if ids_cpro is None else set(ids_cpro)
    for filepath in tqdm(find_files(directory, r"\.factur-x\.xml$"), "Recherche des factur-x"):
        dirpath = os.path.dirname(filepath)
        if os.path.basename(dirpath) != "pivot":
            continue
        facture_folder = os.path.basename(os.path.dirname(dirpath))
        match = re.match(r".*facture_(\d+)", facture_folder)
        if match is None:
            logger.warning("Dossier de facture au nom inattendu, ignoré : %s", dirpath)
            continue
        id_cpro = match.group(1)
        if ids is not None and id_cpro not in ids:
            continue
        result.append((id_cpro, filepath))
    return result


def build_rows(
    files, n_workers: int | None = None
) -> tuple[list[BronzeCproExportFacturX], list[BronzeCproExportFacturXStatus]]:

    all_rows = []
    all_status = []

    n_workers = resolve_n_workers(n_workers)
    schema = get_xsd_schema(DEFAULT_SCHEMA_PROFILE, DEFAULT_SCHEMA_VERSION)
    timings = LoadTimings()
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = {
            executor.submit(load_file, id_cpro, filepath, schema, timings): (id_cpro, filepath)
            for id_cpro, filepath in files
        }

        for i, future in enumerate(
            tqdm(as_completed(futures), total=len(files), desc="Chargement des facture-x"), start=1
        ):
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
            if i % 1000 == 0:
                timings.log(f"{i}/{len(files)}")

    timings.log("terminé")
    logger.info(f"Aggregated {len(files)} files with {len(all_rows)} total rows")
    return all_rows, all_status


def clean_decimals(obj: Any) -> Any:
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
