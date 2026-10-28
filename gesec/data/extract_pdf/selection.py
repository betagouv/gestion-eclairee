"""Inventaire S3 des factures sans XML et sélection du PDF à extraire."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

from django.core.files.storage import default_storage

from sqlalchemy import text

from gesec.data.extract_pdf.paths import UNZIPPED_PREFIX
from gesec.data.pipeline.db import execute_sql
from gesec.data.pipeline.utils import read_xml_file
from gesec.data.processors.cpro.models.pivots_xml import CategoriePJ
from gesec.data.processors.cpro.pivots_xml import parse_xml_to_obj
from gesec.storage import find_files

logger = logging.getLogger(__name__)

FOLDER_RE = re.compile(r"^facture_(\d+)(?:_.*)?$")


@dataclass(frozen=True)
class PdfCandidate:
    id_cpro: str
    folder: str
    pdf_path: str
    pdf_filename: str


@dataclass
class PdfSelection:
    candidates: dict[str, PdfCandidate] = field(default_factory=dict)
    header_missing: list[str] = field(default_factory=list)
    no_pdf: list[str] = field(default_factory=list)
    parse_errors: dict[str, str] = field(default_factory=dict)
    xml_ids: set[str] = field(default_factory=set)
    all_ids: set[str] = field(default_factory=set)


def parse_folder_id(folder: str) -> str | None:
    match = FOLDER_RE.match(folder)
    if match is None:
        logger.warning("Nom de dossier inattendu, ignoré : %s", folder)
        return None
    return match.group(1)


def _existing_headers(ids: list[str]) -> set[str]:
    if not ids:
        return set()
    rows = execute_sql(
        text("SELECT identifiant_chorus_pro FROM gesec_facture WHERE identifiant_chorus_pro = ANY(:ids)"),
        {"ids": ids},
    )
    return {row.identifiant_chorus_pro for row in rows}


def _select_pdf(folder: str, id_cpro: str) -> str | None:
    pivot_path = f"{UNZIPPED_PREFIX}/{folder}/PivotS.xml"
    if not default_storage.exists(pivot_path):
        raise ValueError(f"PivotS.xml absent pour {folder}")

    pivot = parse_xml_to_obj(read_xml_file(pivot_path))
    factures = pivot.CPPFactures.CPPFacturePivotUnitaire
    facture = next((item for item in factures if item.DonneesFacture.IdCPRO == id_cpro), None)
    if facture is None:
        if len(factures) != 1:
            raise ValueError(f"Facture {id_cpro} absente de PivotS.xml ({len(factures)} factures)")
        facture = factures[0]

    names: set[str] = set()
    factures_pdf: list[tuple[int, int, str]] = []
    for position, pj in enumerate(facture.PJ, 1):
        suffix = f".{position}" if pj.NomPJ in names else ""
        names.add(pj.NomPJ)
        if pj.CategoriePJ != CategoriePJ.FACTURE_PDF:
            continue
        stem, extension = os.path.splitext(pj.NomPJ)
        factures_pdf.append((pj.NumOrdre, position, f"{stem}{suffix}{extension}"))

    if not factures_pdf:
        return None
    return min(factures_pdf, key=lambda item: (item[0], item[1]))[2]


def scan_inventory() -> PdfSelection:
    """Parcourt le storage une fois et classe les factures sans XML."""
    folder_files: dict[str, list[str]] = {}
    scan_pattern = re.compile(rf"^{re.escape(UNZIPPED_PREFIX)}/[^/]+/")
    for path in find_files(UNZIPPED_PREFIX, scan_pattern):
        parts = path.split("/")
        if len(parts) < 4:
            continue
        folder_files.setdefault(parts[2], []).append(path)

    folder_has_xml: set[str] = set()
    all_ids: set[str] = set()
    id_folders: dict[str, list[str]] = {}

    for folder in sorted(folder_files):
        id_cpro = parse_folder_id(folder)
        if id_cpro is None:
            continue
        all_ids.add(id_cpro)
        id_folders.setdefault(id_cpro, []).append(folder)
        for path in folder_files[folder]:
            parts = path.split("/")
            if len(parts) >= 5 and parts[3] == "pivot" and parts[-1].endswith(".xml"):
                folder_has_xml.add(folder)

    xml_ids: set[str] = set()
    for folder in folder_has_xml:
        folder_id = parse_folder_id(folder)
        if folder_id is not None:
            xml_ids.add(folder_id)
    extractible_ids = sorted(all_ids - xml_ids)
    headers = _existing_headers(extractible_ids)

    selection = PdfSelection(xml_ids=xml_ids, all_ids=all_ids)
    for id_cpro in extractible_ids:
        if id_cpro not in headers:
            selection.header_missing.append(id_cpro)
            continue

        folders = id_folders.get(id_cpro, [])
        if len(folders) > 1:
            logger.warning("Plusieurs dossiers pour la facture %s, choix de %s", id_cpro, folders[0])
        folder = folders[0]
        try:
            pdf_filename = _select_pdf(folder, id_cpro)
        except Exception as e:
            logger.warning("PivotS.xml illisible pour %s : %s", id_cpro, e)
            selection.parse_errors[id_cpro] = repr(e)
            continue
        if pdf_filename is None:
            selection.no_pdf.append(id_cpro)
            continue
        selection.candidates[id_cpro] = PdfCandidate(
            id_cpro=id_cpro,
            folder=folder,
            pdf_path=f"{UNZIPPED_PREFIX}/{folder}/pivot/{pdf_filename}",
            pdf_filename=pdf_filename,
        )

    return selection
