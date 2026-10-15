"""Construit la liste de téléchargement des factures absentes de la base.

Part du CSV de référence (colonne `REF_FAC`) et le croise avec le gold
(`gesec_facture`) pour déterminer quelles références facture n'ont pas de
facture connue. La `REF_FAC` de BUDAT est tronquée : seuls les derniers
caractères du `numero` entier sont conservés (les préfixes fournisseur et les
zéros de tête sont perdus). Une référence est donc considérée présente dès
qu'elle est un suffixe d'un `numero` de `gesec_facture`.

Les références absentes sont écrites dans `liste_telechargement_missing.csv`,
au format attendu par `download_cpro.py` (`FACTURE_NUM` et `FACTURE_MONTANT`).
Le numéro passé est la `REF_FAC` brute, telle qu'elle apparaît dans l'export :
le script de téléchargement cherche par `Numéro de facture` sans EJ ni service.

Le montant (`MNT_FAC`, déjà au format français) est joint quand il est unique
pour la référence, ce qui permet à `download_cpro.py` de filtrer en plus sur le
TTC exact. En cas de montants distincts pour une même référence, la valeur est
laissée vide pour éviter un filtre hasardeux.

Les artefacts de la colonne `REF_FAC` (erreurs de tableur, montants négatifs ou
décimaux) sont écartés : ils ne désignent aucune facture téléchargeable.

Usage :
    uv run python -m gesec.data.sync.build_missing_reference_download_list \\
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

logger = logging.getLogger(__name__)

CHORUS_FILE_DEFAULT = "export_augdt_20260814.csv"
OUTPUT_DEFAULT = "liste_telechargement_missing.csv"
REFERENCE_COLUMN = "REF_FAC"
MONTANT_COLUMN = "MNT_FAC"

# Erreurs de tableur recopiées dans `REF_FAC` (`#NOM?`, `#VALEUR!`...) : elles
# ne désignent aucune facture.
EXCEL_ERROR_PATTERN = re.compile(r"^#")

# Artefacts recopiés dans `REF_FAC` : valeur signée (`-117049582`,
# `-A F-202509-118`) ou nombre entier à virgule ou en notation scientifique
# (`-1,27444142864846`, `4,7020560922E+22`). Un entier positif sans séparateur
# reste un numéro de facture plausible et n'est donc pas filtré.
NOISE_PATTERN = re.compile(r"^[+-]|[0-9]+[.,][0-9]+|^[0-9]+[eE][+-]?[0-9]+$")


def is_noise_reference(reference: str) -> bool:
    """Détermine si une `REF_FAC` est un artefact et non un numéro de facture."""
    return bool(EXCEL_ERROR_PATTERN.match(reference) or NOISE_PATTERN.search(reference))


def _unique_montant(values: pd.Series) -> str:
    distinct = set(values)
    return distinct.pop() if len(distinct) == 1 else ""


def load_reference_list(filepath: str) -> pd.DataFrame:
    """Charge le CSV de référence et renvoie les `REF_FAC` uniques, non bruitées.

    Chaque référence est accompagnée de son montant (`MNT_FAC`) quand il est
    unique ; sinon `FACTURE_MONTANT` reste vide.
    """
    df = pd.read_csv(filepath, encoding="iso-8859-3", delimiter=";", dtype="str")
    df["FACTURE_NUM"] = df[REFERENCE_COLUMN].fillna("").str.strip()
    df["FACTURE_MONTANT"] = df[MONTANT_COLUMN].fillna("").str.strip()
    df = df[df["FACTURE_NUM"] != ""]
    df = df.drop_duplicates(subset=["FACTURE_NUM", "FACTURE_MONTANT"])

    noise_mask = df["FACTURE_NUM"].map(is_noise_reference)
    noise_count = int(df.loc[noise_mask, "FACTURE_NUM"].nunique())
    if noise_count:
        logger.info("%d référence(s) bruitée(s) retirée(s)", noise_count)
    df = df[~noise_mask]

    montants = df.groupby("FACTURE_NUM")["FACTURE_MONTANT"].agg(_unique_montant)
    result = montants.rename("FACTURE_MONTANT").reset_index()
    return result.sort_values(by="FACTURE_NUM").reset_index(drop=True)


def load_numeros() -> list[str]:
    """Renvoie l'ensemble des `numero` non vides de `gesec_facture` (une seule requête)."""
    engine = db.create_engine()
    with engine.connect() as conn:
        rows = conn.execute(text("select numero from gesec_facture where numero <> ''")).fetchall()
    return [row[0] for row in rows]


def build_suffix_index(numeros: Sequence[str], max_length: int) -> set[str]:
    """Indexe tous les suffixes (bornés à `max_length`) des numéros fournis.

    Permet de tester l'appartenance d'une `REF_FAC` tronquée en temps constant,
    sans requête par référence.
    """
    suffixes: set[str] = set()
    for numero in numeros:
        for start in range(len(numero)):
            if len(numero) - start <= max_length:
                suffixes.add(numero[start:])
    return suffixes


def build_missing_reference_download_list(
    reference_filepath: str,
    output: str = OUTPUT_DEFAULT,
) -> str | None:
    df_reference = load_reference_list(reference_filepath)
    logger.info("%d références facture dans la source", len(df_reference))

    if df_reference.empty:
        logger.info("Aucune référence dans la source : aucune liste écrite.")
        return None

    numeros = load_numeros()
    logger.info("%d numéros de facture dans gesec_facture", len(numeros))

    max_length = int(df_reference["FACTURE_NUM"].str.len().max())
    suffixes = build_suffix_index(numeros, max_length)
    logger.info("%d suffixes indexés", len(suffixes))

    df_missing = df_reference[~df_reference["FACTURE_NUM"].isin(suffixes)]
    logger.info("%d références absentes de gesec_facture", len(df_missing))

    if df_missing.empty:
        logger.info("Aucune facture manquante : aucune liste écrite.")
        return None

    df_missing.to_csv(output, index=False, header=True)
    logger.info("Liste écrite : %s (%d facture(s)).", output, len(df_missing))
    return output


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", nargs="?", default=CHORUS_FILE_DEFAULT, help="CSV de référence (REF_FAC)")
    parser.add_argument("--output", default=OUTPUT_DEFAULT, help="Fichier de sortie de la liste")
    options = parser.parse_args(argv)

    build_missing_reference_download_list(
        reference_filepath=options.reference,
        output=options.output,
    )
    return 0


if __name__ == "__main__":
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gesec.settings")
    django.setup()

    raise SystemExit(main())
