"""Supprime les archives et dossiers de facture en double issus du non-écrasement du storage.

Avant le passage à `file_overwrite` / `allow_overwrite` = `True` (ADR 0005),
un `save()` sur un nom existant produisait `facture_<id_cpro>_<slug>.zip`. Ce
script repère ces variantes dans les archives (`cpro/factures/`) et dans les
dossiers extraits (`cpro/factures_unzipped/`), où le dossier hérite du même
mauvais nom `facture_<id_cpro>_<slug>`, et les supprime lorsque l'élément
canonique `facture_<id_cpro>` est présent.

Par défaut le script est en dry-run : il n'imprime que les actions. Passer
`--apply` pour supprimer réellement. Les variantes sans élément canonique ne
sont jamais supprimées : elles sont signalées, la donnée serait perdue.

Usage :
    uv run python -m gesec.data.sync.clean_facture_zips_duplicates [--apply] [--prefix cpro]
"""

import argparse
import logging
import os
import re
import sys

from django.core.files.storage import default_storage

from gesec.storage import S3Storage, find_files

logger = logging.getLogger(__name__)

DEFAULT_PREFIX = "cpro"
ZIPS_PREFIX = "cpro/factures"
UNZIPPED_PREFIX = "cpro/factures_unzipped"
ZIP_DOUBLON_PATTERN = re.compile(r"^(?P<dir>.*/)?facture_(?P<id_cpro>\d+)_(?P<slug>[A-Za-z0-9]+)\.zip$")
FOLDER_CANONICAL_PATTERN = re.compile(r"^(?:.*/)?facture_\d+$")
FOLDER_DOUBLON_PATTERN = re.compile(r"^(?:.*/)?facture_(?P<id_cpro>\d+)_(?P<slug>[A-Za-z0-9]+)$")


def find_zip_duplicates(prefix: str = ZIPS_PREFIX) -> list[tuple[str, str]]:
    """Renvoie les couples (chemin_doublon, chemin_canonique) des archives en double.

    Un `id_cpro` dont l'archive canonique `facture_<id_cpro>.zip` est absente
    est journalisé comme orphelin et n'est pas retourné : rien à supprimer sans
    perdre l'archive.
    """
    canonical: set[str] = set()
    variants: list[tuple[str, str, str]] = []
    for path in find_files(prefix, r"^.*/facture_\d+(?:_[A-Za-z0-9]+)?\.zip$"):
        match = ZIP_DOUBLON_PATTERN.match(path)
        if match is None:
            canonical.add(path)
        else:
            directory = match.group("dir") or ""
            canonical_path = f"{directory}facture_{match.group('id_cpro')}.zip"
            variants.append((path, canonical_path, match.group("id_cpro")))

    duplicates = []
    for path, canonical_path, id_cpro in variants:
        if canonical_path in canonical:
            duplicates.append((path, canonical_path))
        else:
            logger.warning(
                "Archive orpheline sans canonique, conservée : %s (id_cpro=%s, attendu %s)",
                path,
                id_cpro,
                canonical_path,
            )
    return sorted(duplicates)


def list_toplevel_folders(prefix: str) -> list[str]:
    """Renvoie les dossiers de premier niveau sous `prefix` (chemins complets)."""
    directories, _files = default_storage.listdir(prefix)
    return [f"{prefix}/{name}" for name in directories]


def find_folder_duplicates(prefix: str = UNZIPPED_PREFIX) -> list[tuple[str, str]]:
    """Renvoie les couples (dossier_doublon, dossier_canonique) sous `prefix`.

    Un dossier hérite du nom du zip extrait : un zip en double
    `facture_<id_cpro>_<slug>.zip` produit un dossier `facture_<id_cpro>_<slug>`
    dont l'id_cpro reste correct mais le nom porte le slug. Le dossier n'est
    retourné que si le dossier canonique `facture_<id_cpro>` existe aussi.
    """
    folders = list_toplevel_folders(prefix)
    canonical = {folder for folder in folders if FOLDER_CANONICAL_PATTERN.match(folder)}

    duplicates = []
    for folder in folders:
        match = FOLDER_DOUBLON_PATTERN.match(folder)
        if match is None:
            continue
        canonical_path = f"{prefix}/facture_{match.group('id_cpro')}"
        if canonical_path in canonical:
            duplicates.append((folder, canonical_path))
        else:
            logger.warning(
                "Dossier orphelin sans canonique, conservé : %s (id_cpro=%s, attendu %s)",
                folder,
                match.group("id_cpro"),
                canonical_path,
            )
    return sorted(duplicates)


def remove_dir(path: str) -> None:
    directories, files = default_storage.listdir(path)
    for filename in files:
        default_storage.delete(f"{path}/{filename}")
    for directory in directories:
        remove_dir(f"{path}/{directory}")


def clean_duplicates(prefix: str = DEFAULT_PREFIX, apply: bool = False) -> dict[str, int]:
    """Nettoie les doublons sous `prefix` et renvoie un récapitulatif chiffré.

    Clés : `zip_duplicates`, `folder_duplicates`, `removed`.
    """
    storage = default_storage
    if apply and not isinstance(storage, S3Storage):
        raise RuntimeError("--apply exige STORAGE_BACKEND=s3 : le nettoyage vise les doublons S3.")

    zip_duplicates = find_zip_duplicates(f"{prefix}/factures")
    folder_duplicates = find_folder_duplicates(f"{prefix}/factures_unzipped")
    stats = {
        "zip_duplicates": len(zip_duplicates),
        "folder_duplicates": len(folder_duplicates),
        "removed": 0,
    }

    if not zip_duplicates and not folder_duplicates:
        logger.info("Aucun doublon trouvé sous %s", prefix)
        _log_summary(stats, apply)
        return stats

    for path, canonical_path in zip_duplicates:
        logger.info("%s %s (canonique: %s)", "supprime" if apply else "supprimerait", path, canonical_path)
        if apply:
            storage.delete(path)
            stats["removed"] += 1
    for path, canonical_path in folder_duplicates:
        logger.info("%s %s (canonique: %s)", "supprime" if apply else "supprimerait", path, canonical_path)
        if apply:
            remove_dir(path)
            storage.delete(path)
            stats["removed"] += 1

    _log_summary(stats, apply)
    return stats


def _log_summary(stats: dict[str, int], apply: bool) -> None:
    logger.info(
        "Récapitulatif : %d archive(s) en double, %d dossier(s) en double, %d élément(s) %s.",
        stats["zip_duplicates"],
        stats["folder_duplicates"],
        stats["removed"] if apply else stats["zip_duplicates"] + stats["folder_duplicates"],
        "supprimé(s)" if apply else "à supprimer (dry-run)",
    )
    if not apply and stats["zip_duplicates"] + stats["folder_duplicates"] > 0:
        logger.info("Mode dry-run : aucune suppression effectuée. Rejouer avec --apply.")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Supprime réellement les doublons (défaut: dry-run)")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help=f"Préfixe à parcourir (défaut: {DEFAULT_PREFIX})")
    options = parser.parse_args(argv)

    clean_duplicates(prefix=options.prefix, apply=options.apply)
    return 0


if __name__ == "__main__":
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gesec.settings")
    django.setup()

    raise SystemExit(main())
