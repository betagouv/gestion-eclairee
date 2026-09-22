import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from pydantic import ValidationError

from gesec.data.pipeline.db import load_rows_from_table, save_list_pydantic
from gesec.data.pipeline.layer_1_bronze.schemas import BronzeUgapExportFacture
from gesec.data.pipeline.layer_1_bronze.ugap_export_factures import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME

from .schemas import SilverUgapExportFacture, SilverUgapExportFactureStatus

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]

SENTINELS = {"", "-", "#"}

META_COLUMNS = {"source", "source_idx", "onglet"}

DATE_COLUMNS = {"cde_client_jour_de_creation", "cde_client_date_paiement_client"}
AMOUNT_COLUMNS = {"ce_ht", "tva_collectee", "ce_ttc", "qte_commandees", "montant_facture_ht"}
EMPTY_TEXT_COLUMNS = {
    "cde_client_ndeg_cde_chez_le_client",
    "part_nom_2_organ",
    "sae_niveau_3",
    "sae_niveau_4",
    "ac_se_bp_operateur_etat",
    "type_d_offre_logiciels",
    "boa_tete_de_groupe_mondiale_pays",
    "constructeur_hardware_ajout_manuel",
    "titulaire_2_editeurs_multi_editeurs",
    "siren_titulaire_2",
    "pays_du_titualire_2",
    "type_ent_titulaire_2",
    "sous_traitant_sur_marches_presta",
    "siren_ss_traitant",
    "pays_ss_traitant",
    "type_ent_ss_traitant",
    "texte_adv_ligne_1",
    "texte_adv_ligne_2",
    "texte_adv_ligne_3",
    "texte_adv_ligne_4",
}


def to_text(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if text in SENTINELS:
        return None
    return text


def to_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if text in SENTINELS:
        return None
    try:
        return datetime.strptime(text, "%d/%m/%Y").date()
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text).date()
    except ValueError as error:
        raise ValueError(f"Cannot parse {value!r} as date (expected dd/mm/yyyy): {error}")


def to_decimal(value) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError(f"Cannot parse {value!r} as Decimal")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip()
    if text in SENTINELS:
        return None
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation as error:
        raise ValueError(f"Cannot parse {value!r} as Decimal: {error}")


def transform_bronze_row(bronze: BronzeUgapExportFacture) -> SilverUgapExportFacture:
    values = {}
    for column, value in bronze.model_dump().items():
        if column in META_COLUMNS:
            continue
        if column in DATE_COLUMNS:
            values[column] = to_date(value)
        elif column in AMOUNT_COLUMNS:
            values[column] = to_decimal(value)
        elif column in EMPTY_TEXT_COLUMNS:
            values[column] = to_text(value) or ""
        else:
            values[column] = to_text(value)
    return SilverUgapExportFacture(
        source=bronze.source,
        source_idx=bronze.source_idx,
        onglet=bronze.onglet,
        line_id=0,
        **values,
    )


def recency_key(row: SilverUgapExportFacture) -> tuple[date, date]:
    return (
        row.cde_client_date_paiement_client or date.min,
        row.cde_client_jour_de_creation or date.min,
    )


def deduplicate(
    rows: list[SilverUgapExportFacture],
) -> tuple[list[SilverUgapExportFacture], set[tuple[str, str]]]:
    """Dédoublonne sur (cde_client_ndeg, article_ndeg) en gardant la ligne la plus récente.

    Le tie-break se fait sur l'ordre d'ingestion : à dates égales, la dernière
    ligne rencontrée l'emporte.
    """
    kept: dict[tuple[str, str], SilverUgapExportFacture] = {}
    duplicates: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.cde_client_ndeg, row.article_ndeg)
        current = kept.get(key)
        if current is None:
            kept[key] = row
            continue
        if recency_key(row) >= recency_key(current):
            duplicates.add((current.source, current.source_idx))
            kept[key] = row
        else:
            duplicates.add((row.source, row.source_idx))
    return list(kept.values()), duplicates


def assign_line_ids(rows: list[SilverUgapExportFacture]) -> None:
    counters: dict[str, int] = {}
    for row in rows:
        counters[row.cde_client_ndeg] = counters.get(row.cde_client_ndeg, 0) + 1
        row.line_id = counters[row.cde_client_ndeg]


def build_status(
    bronze: BronzeUgapExportFacture,
    status: str,
    status_details: Optional[str] = None,
) -> SilverUgapExportFactureStatus:
    return SilverUgapExportFactureStatus(
        **bronze.model_dump(),
        status=status,
        status_details=status_details,
    )


def transform_bronze_to_silver(
    bronze_rows: list[BronzeUgapExportFacture],
) -> tuple[list[SilverUgapExportFacture], list[SilverUgapExportFactureStatus]]:
    parsed: list[tuple[BronzeUgapExportFacture, Optional[SilverUgapExportFacture], Optional[Exception]]] = []
    for bronze in bronze_rows:
        try:
            silver = transform_bronze_row(bronze)
        except (ValueError, ValidationError) as error:
            parsed.append((bronze, None, error))
        else:
            parsed.append((bronze, silver, None))

    valid_rows = [silver for _bronze, silver, error in parsed if error is None and silver is not None]
    kept_rows, duplicates = deduplicate(valid_rows)
    assign_line_ids(kept_rows)

    statuses = []
    for bronze, _silver, error in parsed:
        if error is not None:
            statuses.append(build_status(bronze, "Validation error", str(error)))
        elif (bronze.source, bronze.source_idx) in duplicates:
            statuses.append(build_status(bronze, "Duplicat", "Doublon sur (cde_client_ndeg, article_ndeg)"))
        else:
            statuses.append(build_status(bronze, "Ok"))
    return kept_rows, statuses


def process_bronze_to_silver(
    bronze_table_name: str = BRONZE_DEFAULT_TABLE_NAME,
    silver_table_name: str = DEFAULT_TABLE_NAME,
) -> tuple[list[SilverUgapExportFacture], list[SilverUgapExportFactureStatus]]:
    bronze_rows = load_rows_from_table(bronze_table_name, BronzeUgapExportFacture)
    logger.info(f"Chargé {len(bronze_rows)} items depuis la table bronze {bronze_table_name}")

    silver_rows, statuses = transform_bronze_to_silver(bronze_rows)
    logger.info(f"Transformé en {len(silver_rows)} lignes silver après validation et dédoublonnage")

    if silver_rows:
        save_list_pydantic(silver_rows, silver_table_name, if_exists="replace")
    if statuses:
        save_list_pydantic(statuses, silver_table_name + "_status", if_exists="replace")
    logger.info("Process bronze_to_silver terminé avec succès")
    return silver_rows, statuses
