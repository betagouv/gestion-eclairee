"""Construit la liste de téléchargement des factures absentes du storage.

Part du CSV de référence (EJ, SEDP), le croise avec le gold (`gesec_facture`)
pour obtenir l'`id_cpro` de chaque facture attendue. Une facture est considérée
manquante si aucune archive `cpro/factures/facture_<id_cpro>.zip` n'existe dans
le storage.

Le périmètre est global : aucun filtrage par ministère ni par service. Les
manquantes sont écrites au même format que les listes de travail (`EJ`,
`SERVICES`), dans `liste_telechargement_missing.csv`.

Usage :
    uv run python -m gesec.data.sync.build_missing_ej_download_list \\
        <export_csv> [--output <fichier>]
"""

import argparse
import logging
import os
import re
import sys
from collections.abc import Sequence

from sqlalchemy import text

import pandas as pd

from gesec.data.pipeline import db
from gesec.storage import find_files

logger = logging.getLogger(__name__)

CHORUS_FILE_DEFAULT = "export_augdt_20260814.csv"
OUTPUT_DEFAULT = "liste_telechargement_missing.csv"
FACTURES_PREFIX = "cpro/factures"
ZIP_ID_PATTERN = re.compile(r"^(?:.*/)?facture_(\d+)(?:_[A-Za-z0-9]+)?\.zip$")


def load_reference_list(filepath: str) -> pd.DataFrame:
    """Charge le CSV de référence et renvoie les couples (EJ, SERVICES) uniques."""
    df = pd.read_csv(filepath, encoding="iso-8859-3", delimiter=";", dtype="str")
    df = df[["EJ", "SEDP"]].drop_duplicates().rename(columns={"SEDP": "SERVICES"})
    return df.sort_values(by=["EJ", "SERVICES"])


def load_factures() -> pd.DataFrame:
    """Renvoie (identifiant_chorus_pro, numero_du_bon_de_commande, destinataire_code_service)."""
    engine = db.create_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                select identifiant_chorus_pro, numero_du_bon_de_commande, destinataire_code_service
                from gesec_facture
            """),
        ).fetchall()
    return pd.DataFrame(rows, columns=["id_cpro", "EJ", "SERVICES"])


def load_downloaded_ids(prefix: str = FACTURES_PREFIX) -> set[str]:
    ids = set()
    for path in find_files(prefix, re.compile(r"^.*/facture_\d+(?:_[A-Za-z0-9]+)?\.zip$")):
        match = ZIP_ID_PATTERN.match(path)
        if match is not None:
            ids.add(match.group(1))
    return ids


def build_missing_ej_download_list(
    reference_filepath: str,
    output: str = OUTPUT_DEFAULT,
) -> str | None:
    df_reference = load_reference_list(reference_filepath)
    logger.info("%d couples (EJ, SERVICES) dans la référence", len(df_reference))

    df_factures = load_factures()
    df_expected = df_factures.merge(df_reference, on=["EJ", "SERVICES"], how="inner")
    logger.info("%d factures attendues (gold x référence)", len(df_expected))

    downloaded = load_downloaded_ids()
    df_missing = df_expected[~df_expected["id_cpro"].isin(downloaded)]
    logger.info("%d factures manquantes dans le storage", len(df_missing))

    if df_missing.empty:
        _log_summary(
            expected=len(df_expected),
            downloaded=len(df_expected),
            missing=0,
            output=None,
        )
        return None

    df_missing[["EJ", "SERVICES"]].drop_duplicates().sort_values(by=["EJ", "SERVICES"]).to_csv(
        output, index=False, header=True
    )
    _log_summary(
        expected=len(df_expected),
        downloaded=len(df_expected) - len(df_missing),
        missing=len(df_missing),
        output=output,
    )
    return output


def _log_summary(
    expected: int,
    downloaded: int,
    missing: int,
    output: str | None,
) -> None:
    logger.info(
        "Récapitulatif : %d facture(s) attendue(s), %d déjà présente(s), %d manquante(s).",
        expected,
        downloaded,
        missing,
    )
    if output is None:
        logger.info("Aucune facture manquante : aucune liste écrite.")
    else:
        logger.info("Liste écrite : %s (%d facture(s)).", output, missing)


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", nargs="?", default=CHORUS_FILE_DEFAULT, help="CSV de référence (EJ, SEDP)")
    parser.add_argument("--output", default=OUTPUT_DEFAULT, help="Fichier de sortie de la liste")
    options = parser.parse_args(argv)

    build_missing_ej_download_list(
        reference_filepath=options.reference,
        output=options.output,
    )
    return 0


if __name__ == "__main__":
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gesec.settings")
    django.setup()

    raise SystemExit(main())
