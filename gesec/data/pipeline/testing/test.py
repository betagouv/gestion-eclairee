import csv
import sys
from pathlib import Path

from tqdm import tqdm

EXCLUDED_COLUMNS = {"id", "created_at", "updated_at"}
KEY_COLUMN = "identifiant_chorus_pro"


def load_csv_to_dict(filepath: Path) -> dict:
    """Charge un CSV dans un dict {identifiant_chorus_pro: row_dict}."""
    result = {}
    with open(filepath, "r", newline="", encoding="utf-8") as f:
        print(f"Lecture {filepath}")
        reader = csv.DictReader(f)
        for row in reader:
            # Nettoyer la ligne : supprimer les colonnes exclues
            clean_row = {k: v for k, v in row.items() if k not in EXCLUDED_COLUMNS}
            key = clean_row.get(KEY_COLUMN)
            if key is not None:
                result[key] = clean_row
    return result


def compare_dicts(dict_expected: dict, dict_actual: dict) -> dict:
    """Compare deux dicts indexés par identifiant_chorus_pro.

    Returns:
        dict avec les différences
    """
    keys_expected = set(dict_expected.keys())
    keys_actual = set(dict_actual.keys())

    # Lignes manquantes (dans expected mais pas dans actual)
    missing_keys = keys_expected - keys_actual
    missing = {k: dict_expected[k] for k in missing_keys}

    # Lignes en trop (dans actual mais pas dans expected)
    extra_keys = keys_actual - keys_expected
    extra = {k: dict_actual[k] for k in extra_keys}

    # Lignes communes
    common_keys = keys_expected & keys_actual

    # Lignes différentes (même clé mais contenu différent)
    different = {}
    for key in tqdm(common_keys, desc="Comparaison lignes"):
        row_exp = dict_expected[key]
        row_act = dict_actual[key]

        # Comparer toutes les colonnes (sauf KEY_COLUMN qui est la clé)
        diff_cols = []
        for col in row_exp:
            if col != KEY_COLUMN and row_exp[col] != row_act.get(col):
                diff_cols.append({"col": col, "expected": row_exp[col], "actual": row_act.get(col, "MISSING")})

        if diff_cols:
            different[key] = {KEY_COLUMN: key, "diff_columns": diff_cols}

    return {
        "equals": len(missing) == 0 and len(extra) == 0 and len(different) == 0,
        "count_expected": len(dict_expected),
        "count_actual": len(dict_actual),
        "missing_count": len(missing),
        "extra_count": len(extra),
        "different_count": len(different),
        "missing_sample": list(missing.items())[:10],
        "extra_sample": list(extra.items())[:10],
        "different_sample": list(different.items())[:10],
    }


def compare_csv_files(expected_path: Path, actual_path: Path) -> dict:
    """Compare deux fichiers CSV."""
    dict_expected = load_csv_to_dict(expected_path)
    dict_actual = load_csv_to_dict(actual_path)

    # Vérifier que la colonne clé existe dans les deux fichiers
    # (si un dict est vide, c'est que la colonne n'existe pas ou qu'il n'y a pas de données)
    if not dict_expected and not dict_actual:
        # Les deux fichiers sont vides ou n'ont pas la colonne clé
        return {"equals": True, "count_expected": 0, "count_actual": 0}

    if not dict_expected or not dict_actual:
        # Un fichier a des données, l'autre non
        return {
            "equals": False,
            "count_expected": len(dict_expected),
            "count_actual": len(dict_actual),
            "missing_count": len(dict_expected),
            "extra_count": len(dict_actual),
            "different_count": 0,
            "missing_sample": list(dict_expected.items())[:10],
            "extra_sample": list(dict_actual.items())[:10],
            "different_sample": [],
        }

    return compare_dicts(dict_expected, dict_actual)


def compare_directories(expected_dir: Path, actual_dir: Path) -> dict:
    """Compare tous les CSV de deux dossiers."""
    expected_dir = Path(expected_dir)
    actual_dir = Path(actual_dir)

    # Lister les fichiers CSV
    expected_files = {f.name: f for f in expected_dir.glob("*.csv") if f.is_file()}
    actual_files = {f.name: f for f in actual_dir.glob("*.csv") if f.is_file()}

    all_files = set(expected_files.keys()) | set(actual_files.keys())

    results = {}
    for i, filename in enumerate(sorted(all_files), start=1):
        print(f"Comparaison fichier {filename} {i}/{len(all_files)}")
        expected_path = expected_files.get(filename)
        actual_path = actual_files.get(filename)

        if expected_path is None:
            results[filename] = {"status": "MISSING_IN_EXPECTED", "file": str(actual_path)}
        elif actual_path is None:
            results[filename] = {"status": "MISSING_IN_ACTUAL", "file": str(expected_path)}
        else:
            results[filename] = compare_csv_files(expected_path, actual_path)

    return results


def print_results(results: dict) -> None:
    """Affiche les résultats de la comparaison."""
    has_differences = False

    for filename, result in results.items():
        if isinstance(result, dict):
            if "status" in result:
                has_differences = True
                print(f"\n{filename}: {result['status']}")
                if "file" in result:
                    print(f"  File: {result['file']}")
            elif result.get("equals"):
                count = result.get("count_expected", "?")
                print(f"✓ {filename}: OK ({count} lignes)")
            else:
                has_differences = True
                print(f"\n✗ {filename}: DIFFÉRENCES")
                count_exp = result.get("count_expected", 0)
                count_act = result.get("count_actual", 0)
                print(f"  Expected: {count_exp} lignes, Actual: {count_act} lignes")

                missing_count = result.get("missing_count", 0)
                extra_count = result.get("extra_count", 0)
                different_count = result.get("different_count", 0)

                if missing_count > 0:
                    print(f"  -{missing_count} lignes manquantes")
                    sample = result.get("missing_sample", [])
                    if sample:
                        print("  Sample manquantes (max 10):")
                        for key, row in sample[:10]:
                            print(f"    - {KEY_COLUMN}={key}")

                if extra_count > 0:
                    print(f"  +{extra_count} lignes en trop")
                    sample = result.get("extra_sample", [])
                    if sample:
                        print("  Sample en trop (max 10):")
                        for key, row in sample[:10]:
                            print(f"    + {KEY_COLUMN}={key}")

                if different_count > 0:
                    print(f"  ~{different_count} lignes différentes")
                    sample = result.get("different_sample", [])
                    if sample:
                        print("  Sample différentes (max 10):")
                        for key, item in sample[:10]:
                            print(f"    ~ {KEY_COLUMN}={key}:")
                            for diff in item.get("diff_columns", []):
                                print(f"      {diff['col']}: {diff['expected']} -> {diff['actual']}")

    if not has_differences:
        print("\n✓ Tous les fichiers sont identiques !")


def main() -> None:
    """Point d'entrée principal."""
    import argparse

    parser = argparse.ArgumentParser(description="Compare les CSV de deux dossiers (exclut id, created_at, updated_at)")
    parser.add_argument(
        "expected",
        type=Path,
        help="Dossier contenant les CSV attendus",
    )
    parser.add_argument(
        "actual",
        type=Path,
        help="Dossier contenant les CSV à tester",
    )

    args = parser.parse_args()

    if not args.expected.exists():
        print(f"Erreur: le dossier '{args.expected}' n'existe pas", file=sys.stderr)
        sys.exit(1)

    if not args.actual.exists():
        print(f"Erreur: le dossier '{args.actual}' n'existe pas", file=sys.stderr)
        sys.exit(1)

    results = compare_directories(args.expected, args.actual)
    print_results(results)


if __name__ == "__main__":
    main()
