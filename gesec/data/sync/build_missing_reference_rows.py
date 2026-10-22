"""Construit une version réduite de l'export BUDAT/AUGDT ne gardant que les
lignes de factures absentes du gold.

Contrairement à `build_missing_reference_download_list.py`, qui n'écrit que les
références distinctes au format attendu par `download_cpro.py`, ce script
conserve le fichier source tel quel : mêmes colonnes, mêmes valeurs, mais
uniquement les lignes dont la `REF_FAC` n'a aucune facture connue dans
`gesec_facture`. Le rapprochement reprend la même logique (suffixe + filtrage
des artefacts) afin d'être cohérent avec le reste du pipeline.

Usage :
    uv run python -m gesec.data.sync.build_missing_reference_rows \\
        <export_csv> [--output <fichier>]
"""

import argparse
import logging
import os
import sys
from collections.abc import Sequence

import pandas as pd

from gesec.data.sync.build_missing_reference_download_list import (
    REFERENCE_COLUMN,
    build_suffix_index,
    is_noise_reference,
    load_numeros,
)

logger = logging.getLogger(__name__)

CHORUS_FILE_DEFAULT = "export_augdt_20260814.csv"
OUTPUT_DEFAULT = "export_missing.csv"
ENCODING = "iso-8859-3"
DELIMITER = ";"


def load_export(filepath: str) -> pd.DataFrame:
    """Charge l'export brut, toutes colonnes conservées en chaînes."""
    return pd.read_csv(filepath, encoding=ENCODING, delimiter=DELIMITER, dtype="str", keep_default_na=False)


def build_missing_reference_rows(
    reference_filepath: str,
    output: str = OUTPUT_DEFAULT,
) -> str | None:
    df = load_export(reference_filepath)
    logger.info("%d ligne(s) dans la source", len(df))

    refs = df[REFERENCE_COLUMN].fillna("").str.strip()
    is_noise = refs.map(is_noise_reference) | (refs == "")

    numeros = load_numeros()
    logger.info("%d numéros de facture dans gesec_facture", len(numeros))

    max_length = int(refs[~is_noise].str.len().max()) if (~is_noise).any() else 0
    suffixes = build_suffix_index(numeros, max_length) if max_length else set()
    logger.info("%d suffixes indexés", len(suffixes))

    missing_mask = is_noise | ~refs.isin(suffixes)
    df_missing = df[missing_mask]
    logger.info("%d ligne(s) manquante(s) dans gesec_facture", len(df_missing))

    if df_missing.empty:
        logger.info("Aucune ligne manquante : aucun fichier écrit.")
        return None

    df_missing.to_csv(output, index=False, header=True, sep=DELIMITER, encoding=ENCODING)
    logger.info("Fichier écrit : %s (%d ligne(s)).", output, len(df_missing))
    return output


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", nargs="?", default=CHORUS_FILE_DEFAULT, help="Export BUDAT/AUGDT (REF_FAC)")
    parser.add_argument("--output", default=OUTPUT_DEFAULT, help="Fichier de sortie")
    options = parser.parse_args(argv)

    build_missing_reference_rows(
        reference_filepath=options.reference,
        output=options.output,
    )
    return 0


if __name__ == "__main__":
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gesec.settings")
    django.setup()

    raise SystemExit(main())
