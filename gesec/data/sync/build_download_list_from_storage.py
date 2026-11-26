"""Construit la liste de téléchargement (EJ, SERVICES) depuis l'augdt du storage.

Repère le `budat/export_augdt_*.csv` le plus récent dans le storage, en extrait
les couples (EJ, SEDP) uniques et les trie par date de paiement minimale (colonne `DATE_PY`),
puis par EJ et service, pour un traitement des plus anciennes factures d'abord.
Le fichier de sortie est déterministe : tant que l'augdt n'est pas modifié, la
liste produite est identique.

Usage :
    uv run python -m gesec.data.sync.build_download_list_from_storage \\
        [--output liste_telechargement.csv]
"""

import argparse
import io
import logging
import os
import re
import sys
from collections.abc import Sequence

from django.core.files.storage import default_storage

import pandas as pd

from gesec.storage import find_files

logger = logging.getLogger(__name__)

AUGDT_PREFIX = "budat"
AUGDT_PATTERN = re.compile(r"^budat/export_augdt_[^/]*\.csv$")
OUTPUT_DEFAULT = "liste_telechargement.csv"


def latest_augdt_key() -> str:
    """Renvoie la clé storage de l'export augdt le plus récent (tri lexicographique)."""
    keys = sorted(find_files(AUGDT_PREFIX, AUGDT_PATTERN))
    if not keys:
        raise FileNotFoundError(f"Aucun export augdt trouvé sous {AUGDT_PREFIX}/")
    return keys[-1]


def build_download_list(output: str = OUTPUT_DEFAULT) -> str:
    """Lit l'augdt depuis le storage et écrit la liste (EJ, SERVICES) triée par date."""
    key = latest_augdt_key()
    logger.info("Augdt utilisé : %s", key)

    with default_storage.open(key, "rb") as f:
        content = f.read().decode("iso-8859-3")
    df = pd.read_csv(io.StringIO(content), delimiter=";", dtype="str")

    df = df.dropna(subset=["EJ", "SEDP"])
    df["DATE_MIN"] = pd.to_datetime(df["DATE_PY"], format="%Y%m%d", errors="coerce")
    couples = df.groupby(["EJ", "SEDP"])["DATE_MIN"].min().reset_index().rename(columns={"SEDP": "SERVICES"})
    couples = couples.sort_values(["DATE_MIN", "EJ", "SERVICES"]).reset_index(drop=True)

    couples[["EJ", "SERVICES"]].to_csv(output, index=False, header=True)
    logger.info("%d couples (EJ, SERVICES) écrits dans %s", len(couples), output)
    return output


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=OUTPUT_DEFAULT, help="Fichier de sortie de la liste")
    options = parser.parse_args(argv)

    build_download_list(output=options.output)
    return 0


if __name__ == "__main__":
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gesec.settings")
    django.setup()

    raise SystemExit(main())
