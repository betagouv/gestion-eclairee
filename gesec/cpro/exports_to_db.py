import csv
import glob
import logging
import optparse
import os
import re
import sys
from datetime import date, datetime
from decimal import Decimal

from dotenv import load_dotenv
from sqlalchemy import create_engine
from tqdm import tqdm
from unidecode import unidecode

import pandas as pd

logger = logging.getLogger(__name__)

# Regex pattern for CSV files: <num_ej(10 alphanum)>_<service?(alphanum)>_<start(8 digits)>_<end(8 digits)>.csv
CSV_FILE_PATTERN = re.compile(
    r"^(?P<ej>[a-zA-Z0-9]{10})_((?P<service>[a-zA-Z0-9]+)_)?(?P<start>\d{8})_(?P<end>\d{8})\.csv$"
)

# Columns that should be parsed as dates (French format: dd/mm/yyyy)
DATE_COLUMNS = [
    "Date Fournisseur",
    "Date de création",
    "Date de dépôt",
    "Date état courant",
    "Date échéance paiement",
    "Valideur 1 (date de validation)",
    "Valideur 2 (date de validation)",
    "Date modification",
]

# Columns that should be parsed as Decimal (amounts)
AMOUNT_COLUMNS = [
    "Mt HT",
    "Mt TTC",
    "Montant à payer",
    "Montant TTC avant remise",
    "Montant remise globale TTC",
    "Montant TVA",
]


EXPECTED_COLUMNS = {
    'Identifiant Chorus Pro',
    'Numéro',
    'État courant',
    'Instructeur',
    'Motif de rejet',
    "Commentaire de l'état",
    'Type de demande de paiement',
    'Type facture',
    'Type de facture de travaux',
    'Cadre de facturation',
    'Date Fournisseur',
    'Date de création',
    'Date de dépôt',
    'Date état courant',
    'Date échéance paiement',
    'Valideur 1 (date de validation)',
    'Valideur 2 (date de validation)',
    "Fournisseur (type d'identifiant)",
    'Fournisseur (identifiant)',
    'Fournisseur (désignation)',
    'Fournisseur (TVA intracommunautaire)',
    'Fournisseur (code service)',
    'Fournisseur (service)',
    "Destinataire (type d'identifiant)",
    'Destinataire (identifiant)',
    'Destinataire (désignation)',
    'Destinataire (TVA intracommunautaire)',
    'Destinataire (code service)',
    'Destinataire (service)',
    'Mode de dépôt',
    'Mt HT',
    'Mt TTC',
    'Montant à payer',
    'Montant TTC avant remise',
    'Montant remise globale TTC',
    'Motif',
    'Montant TVA',
    'Devise de la facture',
    'Type de TVA',
    "Motif d'éxoneration",
    'Certificat de dépôt n°',
    'Identifiant numérisation',
    "Numéro de la facture d'origine",
    'Numéro DP mandat',
    'Numéro du bon de commande',
    'Numéro de marché',
    'Coordonnées bancaires',
    'BIC ou Swift',
    'Mode de règlement',
    'Document précédent (numéro)',
    'Document précédent (type de pièce)',
    'Document suivant (numéro)',
    'Document suivant (type de pièce)',
    'Dossier de facturation',
    'Commentaire',
    'Numéro de lot transmis',
    'Date modification',
    'Telechargée',
    "Emetteur (type d'identifiant)",
    'Emetteur (identifiant)',
    'Emetteur (désignation)',
    "Affactureur (type d'identifiant)",
    'Affactureur (identifiant)',
    'Affactureur (désignation)',
    "Maîtrise d’oeuvre (type d'identifiant)",
    'Maîtrise d’oeuvre (identifiant)',
    'Maîtrise d’oeuvre (désignation)',
    'Maîtrise d’oeuvre (TVA intracommunautaire)',
    "Maîtrise d'oeuvre (code service)",
    'Maîtrise d’oeuvre (service)',
    "Maîtrise d’ouvrage (type d'identifiant)",
    'Maîtrise d’ouvrage (identifiant)',
    'Maîtrise d’ouvrage (désignation)',
    'Maîtrise d’ouvrage (TVA intracommunautaire)',
    'Maîtrise d’ouvrage (code service)',
    'Maîtrise d’ouvrage (service)',
    "Valideur 1 (type d'identifiant)",
    'Valideur 1 (identifiant)',
    'Valideur 1 (désignation)',
    "Valideur 2 (type d'identifiant)",
    'Valideur 2 (identifiant)',
    'Valideur 2 (désignation)',
}

EXPECTED_CLEANED_COLUMNS = {
    'identifiant_chorus_pro', 'numero', 'etat_courant', 'instructeur',
    'motif_de_rejet', 'commentaire_de_l_etat',
    'type_de_demande_de_paiement', 'type_facture',
    'type_de_facture_de_travaux', 'cadre_de_facturation',
    'date_fournisseur', 'date_de_creation', 'date_de_depot',
    'date_etat_courant', 'date_echeance_paiement',
    'valideur_1_date_de_validation', 'valideur_2_date_de_validation',
    'fournisseur_type_d_identifiant', 'fournisseur_identifiant',
    'fournisseur_designation', 'fournisseur_tva_intracommunautaire',
    'fournisseur_code_service', 'fournisseur_service',
    'destinataire_type_d_identifiant', 'destinataire_identifiant',
    'destinataire_designation', 'destinataire_tva_intracommunautaire',
    'destinataire_code_service', 'destinataire_service', 'mode_de_depot',
    'mt_ht', 'mt_ttc', 'montant_a_payer', 'montant_ttc_avant_remise',
    'montant_remise_globale_ttc', 'motif', 'montant_tva',
    'devise_de_la_facture', 'type_de_tva', 'motif_d_exoneration',
    'certificat_de_depot_ndeg', 'identifiant_numerisation',
    'numero_de_la_facture_d_origine', 'numero_dp_mandat',
    'numero_du_bon_de_commande', 'numero_de_marche',
    'coordonnees_bancaires', 'bic_ou_swift', 'mode_de_reglement',
    'document_precedent_numero', 'document_precedent_type_de_piece',
    'document_suivant_numero', 'document_suivant_type_de_piece',
    'dossier_de_facturation', 'commentaire', 'numero_de_lot_transmis',
    'date_modification', 'telechargee', 'emetteur_type_d_identifiant',
    'emetteur_identifiant', 'emetteur_designation',
    'affactureur_type_d_identifiant', 'affactureur_identifiant',
    'affactureur_designation', 'maitrise_d_oeuvre_type_d_identifiant',
    'maitrise_d_oeuvre_identifiant', 'maitrise_d_oeuvre_designation',
    'maitrise_d_oeuvre_tva_intracommunautaire',
    'maitrise_d_oeuvre_code_service', 'maitrise_d_oeuvre_service',
    'maitrise_d_ouvrage_type_d_identifiant',
    'maitrise_d_ouvrage_identifiant', 'maitrise_d_ouvrage_designation',
    'maitrise_d_ouvrage_tva_intracommunautaire',
    'maitrise_d_ouvrage_code_service', 'maitrise_d_ouvrage_service',
    'valideur_1_type_d_identifiant', 'valideur_1_identifiant',
    'valideur_1_designation', 'valideur_2_type_d_identifiant',
    'valideur_2_identifiant', 'valideur_2_designation'
}


def filter_csv_files(directory: str) -> list[str]:
    """Filter CSV files matching the patterns.

     Patterns:
        - <num_ej>_<service>_<start>_<end>.csv
        - <num_ej>_<start>_<end>.csv

    The pattern requires:
    - num_ej: exactly 10 alphanumeric characters
    - service: alphanumeric (any length)
    - start: 8 digits (yyyymmdd format)
    - end: 8 digits (yyyymmdd format)

    Args:
        directory: Path to the directory containing CSV files

    Returns:
        Sorted list of file paths matching the pattern
    """
    csv_files = []

    for filepath in glob.iglob(os.path.join(directory, "*.csv")):
        filename = os.path.basename(filepath)
        if CSV_FILE_PATTERN.match(filename):
            csv_files.append(filepath)

    return sorted(csv_files)


def clean_column_name(col: str) -> str:
    """Clean a column name to be SQL-compatible.

    First converts accented characters to ASCII using unidecode,
    then replaces special characters with underscores, removes multiple/leading/trailing
    underscores, and converts to lowercase.

    Args:
        col: Original column name

    Returns:
        SQL-compatible column name
    """
    # Convert accented characters to ASCII first (e.g., é -> e, ç -> c)
    col = unidecode(col)
    # Replace any non-alphanumeric/underscore character with underscore
    col = re.sub(r"[^a-zA-Z0-9_]", "_", col)
    # Remove multiple consecutive underscores
    col = re.sub(r"_+", "_", col)
    # Remove leading and trailing underscores
    col = col.strip("_")
    # Convert to lowercase
    col = col.lower()
    return col


def clean_dataframe_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Clean all column names in a DataFrame to be SQL-compatible.

    Args:
        df: DataFrame with original column names

    Returns:
        DataFrame with cleaned column names
    """
    df.columns = [clean_column_name(col) for col in df.columns]
    return df


def extract_source_info(filename: str) -> tuple[str, str]:
    """Extract num_ej and service from a CSV filename.

    The filename is expected to match the pattern: <num_ej>_<service>_<start>_<end>.csv
    Uses the same CSV_FILE_PATTERN regex for consistency.

    Args:
        filename: The CSV filename (without path)

    Returns:
        Tuple of (num_ej, service)

    Raises:
        ValueError: If the filename doesn't match the expected pattern
    """
    match = CSV_FILE_PATTERN.match(filename)

    if not match:
        raise ValueError(f"Filename '{filename}' doesn't match expected pattern")

    # Extract num_ej (first 10 characters before first underscore)
    num_ej = match.group("ej")
    service = match.group("service") or ""

    return num_ej, service


def _parse_row(row: dict[str, str]) -> dict[str, str | date | Decimal]:
    """Parse a single CSV row, converting date and amount columns to proper types.

    Args:
        row: Dictionary of row values (all strings)

    Returns:
        Dictionary with typed values

    Raises:
        ValueError: If date or amount parsing fails
    """

    empty_value = row.pop("")
    assert empty_value == "", f"Value is not empty {empty_value!r}"

    row_columns = set(row.keys())
    assert row_columns == EXPECTED_COLUMNS, f"Invalid columns missings={EXPECTED_COLUMNS - row_columns} unknowns={row_columns - EXPECTED_COLUMNS}"

    # Parse date columns
    for date_col in DATE_COLUMNS:
        if date_col in row and row[date_col].strip():
            try:
                row[date_col] = datetime.strptime(row[date_col], "%d/%m/%Y").date()
            except ValueError as e:
                raise ValueError(f"Cannot parse '{date_col}' as date (expected dd/mm/yyyy): {e}")

    # Parse amount columns
    for amount_col in AMOUNT_COLUMNS:
        if amount_col in row and row[amount_col].strip():
            try:
                # Replace French decimal separator (comma with dot)
                row[amount_col] = Decimal(row[amount_col].replace(",", "."))
            except (ValueError, TypeError) as e:
                raise ValueError(f"Cannot parse '{amount_col}' as Decimal: {e}")

    return row


def aggregate_csv_files(csv_files: list[str]) -> pd.DataFrame:
    """Aggregate multiple CSV files into a single DataFrame.

    Uses csv.DictReader for optimal performance with many small files.
    - All columns are kept as string by default
    - Date columns are parsed as date (French format: dd/mm/yyyy)
    - Amount columns are converted to Decimal (from string values)
    - Shows progress with tqdm
    - Creates a single DataFrame at the end for efficiency

    Args:
        csv_files: List of CSV file paths to aggregate

    Returns:
        DataFrame containing all data from the CSV files with source columns

    Raises:
        ValueError: If a date or amount column cannot be parsed
    """
    all_rows = []

    for filepath in tqdm(csv_files, desc="Aggregating CSV files"):
        logger.debug(f"Reading {filepath}")
        filename = os.path.basename(filepath)

        num_ej, service = extract_source_info(filename)
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                parsed_row = _parse_row(row)
                assert not service or parsed_row["Destinataire (code service)"] == service, (
                    f"Invalid service {service!r} {parsed_row!r}"
                )
                assert parsed_row["Numéro du bon de commande"] == num_ej, f"Invalid num_ej {num_ej!r} {parsed_row!r}"
                all_rows.append(parsed_row)

    if not all_rows:
        logger.warning("No data rows found in CSV files")
        return pd.DataFrame()

    # Create DataFrame once at the end
    df = pd.DataFrame(all_rows)

    # Clean column names for SQL compatibility
    df = clean_dataframe_columns(df)

    df_columns = set(df.columns)
    assert df_columns == EXPECTED_CLEANED_COLUMNS, f"Invalid columns missings={EXPECTED_CLEANED_COLUMNS - df_columns} unknowns={df_columns - EXPECTED_CLEANED_COLUMNS}"

    # Make sure there is no duplicate
    rows_count = df.shape[0]
    dedup_rows_count = df.drop_duplicates("identifiant_chorus_pro").shape[0]
    assert rows_count == dedup_rows_count, f"Duplicates: {rows_count - dedup_rows_count}"

    logger.info(f"Aggregated {len(csv_files)} files with {len(df)} total rows")
    return df


def create_indexes(conn, table_name: str) -> None:
    """Create indexes on specified columns after data export.

    Creates indexes on:
    - numero_du_bon_de_commande
    - date_etat_courant

    Args:
        conn: SQLAlchemy connection
        table_name: Name of the table to index

    Raises:
        Exception: If index creation fails
    """
    # Get raw DBAPI connection from SQLAlchemy connection
    raw_conn = conn.connection
    cursor = raw_conn.cursor()

    # Index on numero_du_bon_de_commande
    index_name_1 = f"idx_{table_name}_numero_du_bon_de_commande"
    try:
        cursor.execute(f"CREATE INDEX IF NOT EXISTS {index_name_1} ON {table_name} (numero_du_bon_de_commande)")
        logger.info(f"Created index {index_name_1} on numero_du_bon_de_commande")
    except Exception as e:
        logger.warning(f"Could not create index {index_name_1}: {e}")

    # Index on date_etat_courant
    index_name_2 = f"idx_{table_name}_date_etat_courant"
    try:
        cursor.execute(f"CREATE INDEX IF NOT EXISTS {index_name_2} ON {table_name} (date_etat_courant)")
        logger.info(f"Created index {index_name_2} on date_etat_courant")
    except Exception as e:
        logger.warning(f"Could not create index {index_name_2}: {e}")

    raw_conn.commit()


def export_to_database(df: pd.DataFrame, table_name: str, db_url: str) -> None:
    """Export a DataFrame to a database table using SQLAlchemy.

    Note: Column names should already be cleaned for SQL compatibility.
    Creates indexes on numero_du_bon_de_commande and date_etat_courant.

    Args:
        df: DataFrame to export (with cleaned column names)
        table_name: Name of the target table
        db_url: Database connection URL (postgres:// or postgresql://)

    Raises:
        Exception: If database export fails
    """
    if df.empty:
        logger.warning("No data to export, skipping database insertion")
        return

    logger.info(f"Exporting {len(df)} rows to table '{table_name}'")

    try:
        # Create SQLAlchemy engine
        engine = create_engine(db_url)

        # Export data
        df.to_sql(name=table_name, con=engine, if_exists="replace", index=False)
        logger.info(f"Successfully exported to table '{table_name}'")

        # Create indexes on key columns using raw psycopg connection
        with engine.connect() as conn:
            create_indexes(conn, table_name)

    except Exception as e:
        logger.error(f"Error exporting to database: {e}")
        raise


def parse_args():
    """Parse command line arguments."""
    parser = optparse.OptionParser(
        usage="%prog [options] DIRECTORY",
        description="Export CSV files matching pattern <num_ej>_<service>_<start>_<end>.csv to a database table. "
        "DIRECTORY is required and should contain the CSV files to process. "
        "DATABASE_URL is loaded from .env file or environment variable.",
    )
    parser.add_option(
        "--table-name",
        dest="table_name",
        help="Name of the target table in database (required)",
    )
    options, args = parser.parse_args()
    return options, args


def main():
    """Main entry point for the script."""
    # Load environment variables from .env file
    load_dotenv()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    options, args = parse_args()

    # Validate required arguments
    if not args:
        logger.error("Error: Directory path is required")
        sys.exit(1)

    directory = args[0]
    if not os.path.isdir(directory):
        logger.error(f"Error: '{directory}' is not a valid directory")
        sys.exit(1)

    # Validate table name
    if not options.table_name:
        logger.error("Error: --table-name is required")
        sys.exit(1)

    # Get database URL from environment variable (loaded from .env or system env)
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("Error: DATABASE_URL is required (from .env file or environment variable)")
        sys.exit(1)
    db_url = db_url.replace("postgres:", "postgresql+psycopg:")

    # Filter CSV files matching the pattern
    csv_files = filter_csv_files(directory)
    if not csv_files:
        logger.warning(f"No CSV files matching the pattern found in {directory}")
        sys.exit(0)

    logger.info(f"Found {len(csv_files)} matching CSV files")
    for filepath in csv_files:
        logger.debug(f"  - {os.path.basename(filepath)}")

    # Aggregate all CSV files
    df = aggregate_csv_files(csv_files)

    if df.empty:
        logger.warning("No data to export")
        sys.exit(0)

    # Export to database
    export_to_database(df, options.table_name, db_url)

    logger.info("Operation completed successfully")
    sys.exit(0)


if __name__ == "__main__":
    main()
