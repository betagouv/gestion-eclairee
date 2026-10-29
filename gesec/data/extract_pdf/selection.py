"""Sélection des factures à extraire et résolution de leur dossier storage."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import text

from gesec.data.extract_pdf.paths import UNZIPPED_PREFIX
from gesec.data.pipeline.db import execute_sql
from gesec.storage import find_files

logger = logging.getLogger(__name__)

FOLDER_RE = re.compile(r"^facture_(\d+)(?:_.*)?$")


@dataclass(frozen=True)
class PdfCandidate:
    id_cpro: str
    folder: str | None


@dataclass
class PdfSelection:
    candidates: dict[str, PdfCandidate] = field(default_factory=dict)


def parse_folder_id(folder: str) -> str | None:
    match = FOLDER_RE.match(folder)
    if match is None:
        logger.warning("Nom de dossier inattendu, ignoré : %s", folder)
        return None
    return match.group(1)


def _eligible_ids() -> set[str]:
    """Factures CPRO sans aucune ligne gold, donc sans source d'éclatement."""
    rows = execute_sql(
        text(
            "SELECT f.identifiant_chorus_pro FROM gesec_facture f "
            "WHERE NOT EXISTS (SELECT 1 FROM gesec_facture_ligne l WHERE l.id_cpro = f.identifiant_chorus_pro)"
        )
    )
    return {row.identifiant_chorus_pro for row in rows}


def scan_inventory() -> PdfSelection:
    """Recense les factures éligibles à l'OCR et résout leur dossier storage.

    L'éligibilité vient du gold : toute facture de `gesec_facture` dépourvue de
    ligne dans `gesec_facture_ligne` mérite une extraction PDF, qu'un pivot XML
    ou un Factur-X soit présent ou non (les profils `minimum` n'ont pas de
    lignes). Le storage ne sert qu'à associer chaque facture à son dossier
    `facture_<id_cpro>` ; une facture éligible sans dossier devient candidate
    avec `folder=None`, traitée `no_pdf`.
    """
    id_folders: dict[str, str] = {}
    scan_pattern = re.compile(rf"^{re.escape(UNZIPPED_PREFIX)}/[^/]+/")
    for path in find_files(UNZIPPED_PREFIX, scan_pattern):
        parts = path.split("/")
        if len(parts) < 4:
            continue
        folder = parts[2]
        id_cpro = parse_folder_id(folder)
        if id_cpro is None:
            continue
        if id_cpro in id_folders:
            logger.warning("Plusieurs dossiers pour la facture %s, choix de %s", id_cpro, id_folders[id_cpro])
            continue
        id_folders[id_cpro] = folder

    eligible_ids = _eligible_ids()
    selection = PdfSelection()
    selection.candidates = {
        id_cpro: PdfCandidate(id_cpro=id_cpro, folder=id_folders.get(id_cpro)) for id_cpro in sorted(eligible_ids)
    }
    return selection
