"""Insert facture xml in DB"""

import logging
import os
import re
from collections.abc import Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from decimal import Decimal
from time import perf_counter
from typing import Any, cast

from django.conf import settings

from tqdm import tqdm
from xmlschema import XMLSchema, XMLSchemaValidationError

from gesec.data.pipeline.db import DEFAULT_BATCH_SIZE, create_empty_table, save_pages
from gesec.storage import find_files

from ..utils import LoadTimings, read_xml_file, resolve_n_workers
from .schemas import BronzeCproExportFactureXml, BronzeCproExportFactureXmlStatus
from .utils import get_ids_cpro_for_ministere

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


def load_file(
    id_cpro: str,
    file_path: str,
    schema: XMLSchema | None = None,
    timings: LoadTimings | None = None,
) -> BronzeCproExportFactureXml:
    if schema is None:
        schema = get_xsd_schema("2.4")

    xml = read_xml_file(file_path, timings=timings)

    start = perf_counter()
    schema_version = detect_schema_version(xml)
    if timings is not None:
        timings.record("version", perf_counter() - start)
    if schema_version is None:
        raise ValueError(f"Cannot determine schema version for {id_cpro} {file_path}")

    # Nettoyage des tags vides
    xml = xml.replace('<cbc:AllowanceTotalAmount currencyID="EUR"/>', "")
    xml = xml.replace('<cbc:Amount currencyID="EUR"/>', '<cbc:Amount currencyID="EUR">0.0</cbc:Amount>')

    start = perf_counter()
    content = cast("dict | None", schema.to_dict(xml)) or {}
    if timings is not None:
        timings.record("parse", perf_counter() - start)

    start = perf_counter()
    row = BronzeCproExportFactureXml(
        id_cpro=id_cpro,
        xml_schema=f"UBL-Invoice-{schema_version}",
        content=content,
    )
    if timings is not None:
        timings.record("build", perf_counter() - start)
    return row


def filter_files(directory: str, ids_cpro: list[str] | None = None) -> list[tuple[str, str]]:
    """Renvoie la liste (id_cpro, path) des fichiers factures xml.

    Recherche récursive via le storage, puis retient les dossiers `pivot` des
    dossiers `facture_<id_cpro>`.
    """
    result = []
    ids = None if ids_cpro is None else set(ids_cpro)
    for filepath in tqdm(find_files(directory, r"\.xml$"), "Recherche des factures XML"):
        if filepath.endswith(".factur-x.xml"):
            continue
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


def iter_row_pages(
    files: list[tuple[str, str]],
    n_workers: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Iterator[tuple[list[BronzeCproExportFactureXml], list[BronzeCproExportFactureXmlStatus]]]:
    """Charge les fichiers XML par lots bornés, sans tout garder en mémoire.

    Maintient au plus `n_workers` tâches en vol et émet une page dès que
    `batch_size` lignes sont prêtes.
    """
    n_workers = resolve_n_workers(n_workers)
    schema = get_xsd_schema("2.4")
    timings = LoadTimings()
    rows: list[BronzeCproExportFactureXml] = []
    status: list[BronzeCproExportFactureXmlStatus] = []
    futures: dict[Future[BronzeCproExportFactureXml], tuple[str, str]] = {}
    files_iter = iter(files)

    def submit_next(executor: ThreadPoolExecutor) -> bool:
        try:
            id_cpro, filepath = next(files_iter)
        except StopIteration:
            return False
        futures[executor.submit(load_file, id_cpro, filepath, schema, timings)] = (id_cpro, filepath)
        return True

    with (
        ThreadPoolExecutor(max_workers=n_workers) as executor,
        tqdm(total=len(files), desc="Chargement des factures XML") as progress,
    ):
        for _ in range(n_workers):
            submit_next(executor)

        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                id_cpro, filepath = futures.pop(future)
                progress.update(1)
                try:
                    rows.append(future.result())
                    status.append(BronzeCproExportFactureXmlStatus(id_cpro=id_cpro, status="Ok"))
                except XMLSchemaValidationError as e:
                    logger.warning("Validation Error for %s %s: %s", id_cpro, filepath, (e.reason, e.path))
                    status.append(
                        BronzeCproExportFactureXmlStatus(
                            id_cpro=id_cpro,
                            status="Validation error",
                            status_details=f"Path: {e.path}\nReason: {e.reason}\n{e}",
                        )
                    )
                except Exception as e:
                    logger.exception(f"Failed to process {id_cpro} {filepath}: {e}")
                    status.append(
                        BronzeCproExportFactureXmlStatus(
                            id_cpro=id_cpro,
                            status="Unexpected error",
                            status_details=f"{id_cpro} {filepath}\n{e!r}",
                        )
                    )
                submit_next(executor)

                if len(rows) >= batch_size:
                    yield rows, status
                    rows, status = [], []

    timings.log("terminé")
    if rows or status:
        yield rows, status


def clean_decimals(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    elif isinstance(obj, dict):
        return {k: clean_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple, set)):
        return type(obj)(clean_decimals(item) for item in obj)
    return obj


def export_to_database(
    pages: Iterator[tuple[list[BronzeCproExportFactureXml], list[BronzeCproExportFactureXmlStatus]]],
    table_name: str = DEFAULT_TABLE_NAME,
) -> None:
    """Écrit les pages bronze et leurs statuts au fil de l'eau."""
    rows_first = True
    status_first = True
    written = 0
    for rows, status in pages:
        for row in rows:
            row.content = clean_decimals(row.content)
        if save_pages([rows], table_name, if_exists="replace" if rows_first else "append"):
            rows_first = False
            written += len(rows)
        if save_pages([status], table_name + "_status", if_exists="replace" if status_first else "append"):
            status_first = False
    if rows_first:
        create_empty_table(table_name, BronzeCproExportFactureXml)
    if status_first:
        create_empty_table(table_name + "_status", BronzeCproExportFactureXmlStatus)
    if written == 0:
        logger.warning("No data to export, skipping database insertion")
    else:
        logger.info(f"Saved {written} rows in {table_name}")


def process_files_to_bronze(
    directory: str,
    table_name: str = DEFAULT_TABLE_NAME,
    n_workers: int | None = None,
    ids_cpro: list[str] | None = None,
    ministere: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
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

    export_to_database(iter_row_pages(files, n_workers=n_workers, batch_size=batch_size), table_name=table_name)

    logger.info("Operation completed successfully")
