import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from gesec.cpro.db import create_engine


def get_all_tables() -> list[str]:
    """Récupère toutes les tables.

    Returns:
        Liste des noms de tables au format schema.table
    """
    engine = create_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text("""SELECT table_schema, table_name 
                  FROM information_schema.tables 
                  WHERE table_type = 'BASE TABLE'
                  ORDER BY table_name"""),
        )
        tables = [f"{row[0]}.{row[1]}" for row in result.fetchall()]
    return tables


def expand_table_patterns(patterns: list[str]) -> list[str]:
    """Étend les motifs de tables (ex: bronze_*) en liste complète de tables.

    Args:
        patterns: Liste de motifs de tables (ex: ['bronze_*', 'silver.factures'])

    Returns:
        Liste des noms de tables complets
    """
    expanded = []
    all_tables = get_all_tables()
    for pattern in patterns:
        if pattern.endswith("*"):
            table_pattern = pattern[:-1]  # Enlève *
            if "." not in table_pattern:
                table_pattern = "public." + table_pattern
            expanded.extend([table for table in all_tables if table.startswith(table_pattern)])
        else:
            expanded.append(pattern)
    return expanded


def load_table_to_dataframe(table_name: str) -> pd.DataFrame:
    """Charge le contenu d'une table de la BDD dans un DataFrame pandas.

    Args:
        table_name: Nom de la table (peut inclure le schéma, ex: bronze.table_name)

    Returns:
        DataFrame pandas contenant les données de la table
    """
    engine = create_engine()
    with engine.connect() as conn:
        df = pd.read_sql(f"SELECT * FROM {table_name}", conn)
    return df


def save_dataframe_to_csv(df: pd.DataFrame, output_path: Path) -> None:
    """Sauvegarde un DataFrame en fichier CSV.

    Args:
        df: DataFrame pandas à sauvegarder
        output_path: Chemin vers le fichier CSV de sortie
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Sauvegardé: {output_path} ({len(df)} lignes)")


def dump_table(table_name: str, output_dir: Path) -> None:
    """Dump une table de la BDD vers un fichier CSV.

    Args:
        table_name: Nom de la table
        output_dir: Dossier de sortie pour le fichier CSV
    """
    print(f"Dump de la table: {table_name}")
    df = load_table_to_dataframe(table_name)
    
    # Nettoyer le nom de la table pour le nom de fichier
    safe_table_name = table_name.replace(".", "_").replace(" ", "_")
    output_path = output_dir / f"{safe_table_name}.csv"
    
    save_dataframe_to_csv(df, output_path)


def main() -> None:
    """Point d'entrée principal.

    Usage:
        python dump.py bronze_* silver.factures --output-dir ./dumps
        python dump.py bronze_* silver_* gold_*
    """
    import os
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gesec.settings")
    django.setup()

    import argparse

    parser = argparse.ArgumentParser(
        description="Dump le contenu des tables de la BDD (bronze, silver, gold) en fichiers CSV"
    )
    parser.add_argument(
        "tables",
        nargs="+",
        help="Liste des tables à dumper (ex: bronze.factures silver_* gold_*)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("./dumps"),
        help="Dossier où sauvegarder les fichiers CSV (par défaut: ./dumps)",
    )

    args = parser.parse_args()
    
    # Étendre les motifs (ex: bronze_* -> liste de toutes les tables bronze)
    tables = expand_table_patterns(args.tables)
    
    if not tables:
        print("Aucune table à dumper (les motifs ne correspondent à aucune table)", file=sys.stderr)
        sys.exit(1)

    print(f"Dossier de sortie: {args.output_dir}")
    print(f"Tables à dumper: {tables}")

    for table in tables:
        try:
            dump_table(table, args.output_dir)
        except Exception as e:
            print(f"Erreur lors du dump de la table {table}: {e}", file=sys.stderr)
            continue

    print("Dump terminé!")


if __name__ == "__main__":
    main()
