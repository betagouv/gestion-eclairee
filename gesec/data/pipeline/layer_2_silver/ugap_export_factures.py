import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from pydantic import ValidationError

from gesec.data.pipeline.db import (
    DEFAULT_BATCH_SIZE,
    TableWriter,
    iter_rows_from_table,
)
from gesec.data.pipeline.layer_1_bronze.schemas import BronzeUgapExportFacture
from gesec.data.pipeline.layer_1_bronze.ugap_export_factures import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME

from .schemas import SilverUgapExportFacture, SilverUgapExportFactureStatus, UgapExportFactureStatus

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]

SENTINELS = {"", "-", "#", "#N/A", "N/A"}

META_COLUMNS = {"source", "source_idx", "onglet"}

DATE_COLUMNS = {"jour_creation_commande_ugap", "jour_paiement_commande_ugap"}
AMOUNT_COLUMNS = {"ce_ht", "tva", "ce_ttc", "qte_article_commandee", "montant_facture_ht"}
ZERO_AS_EMPTY_COLUMNS = {"constructeur_article"}
EMPTY_TEXT_COLUMNS = {
    "numero_commande_chez_le_client",
    "numero_facture",
    "part_nom_2_organ",
    "sae_niveau_3",
    "sae_niveau_4",
    "ac_se_bp_operateur_etat",
    "type_offre_logicielle",
    "pays_titulaire_1",
    "constructeur_article",
    "titulaire_rang_2",
    "siren_titulaire_2",
    "pays_titulaire_2",
    "type_ent_titulaire_2",
    "sous_traitant",
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
    values: dict[str, Any] = {}
    for column, value in bronze.model_dump().items():
        if column in META_COLUMNS:
            continue
        if column in DATE_COLUMNS:
            values[column] = to_date(value)
        elif column in AMOUNT_COLUMNS:
            values[column] = to_decimal(value)
        elif column in EMPTY_TEXT_COLUMNS:
            text = to_text(value)
            if column in ZERO_AS_EMPTY_COLUMNS and text == "0":
                text = None
            values[column] = text or ""
        else:
            values[column] = to_text(value)
    return SilverUgapExportFacture(
        source=bronze.source,
        source_idx=bronze.source_idx,
        onglet=bronze.onglet,
        **values,
    )


@dataclass
class ParsedUgapRow:
    source: str
    source_idx: str
    silver: Optional[SilverUgapExportFacture]
    error: Optional[str]

    @property
    def dedup_key(self) -> tuple[str, str, Optional[date], Optional[Decimal]]:
        row = self.silver
        if row is None:
            return ("", "", None, None)
        return (
            row.numero_commande_ugap,
            row.code_article_ugap,
            row.jour_paiement_commande_ugap,
            row.montant_facture_ht,
        )

    @property
    def order_key(self) -> tuple[str, str]:
        return (self.source, self.source_idx)


def parse_bronze_row(bronze: BronzeUgapExportFacture) -> ParsedUgapRow:
    try:
        silver = transform_bronze_row(bronze)
    except (ValueError, ValidationError) as error:
        return ParsedUgapRow(source=bronze.source, source_idx=bronze.source_idx, silver=None, error=str(error))
    return ParsedUgapRow(source=bronze.source, source_idx=bronze.source_idx, silver=silver, error=None)


def deduplicate(parsed: list[ParsedUgapRow]) -> int:
    """Élague en place les doublons, en gardant la dernière ligne triée.

    Dédoublonne sur (commande, article, date de paiement, montant HT). Les lignes
    sont considérées dans l'ordre (source, source_idx) ; à clé égale, la dernière
    l'emporte. Les entrées évincées voient leur `silver` remis à `None` et
    reçoivent l'erreur `Duplicat`. Renvoie le nombre de doublons évincés.
    """
    kept: dict[tuple[str, str, Optional[date], Optional[Decimal]], ParsedUgapRow] = {}
    duplicates = 0
    for entry in sorted(parsed, key=lambda entry: entry.order_key):
        if entry.silver is None:
            continue
        current = kept.get(entry.dedup_key)
        if current is not None:
            current.silver = None
            current.error = "Duplicat"
            duplicates += 1
        kept[entry.dedup_key] = entry
    return duplicates


def process_bronze_to_silver(
    bronze_table_name: str = BRONZE_DEFAULT_TABLE_NAME,
    silver_table_name: str = DEFAULT_TABLE_NAME,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
    """Stream le bronze par pages, dédoublonne en Python, écrit la silver et ses statuts."""
    parsed: list[ParsedUgapRow] = []
    for bronze in iter_rows_from_table(bronze_table_name, BronzeUgapExportFacture, batch_size=batch_size):
        parsed.append(parse_bronze_row(bronze))

    duplicates = deduplicate(parsed)

    silver_rows = [entry.silver for entry in parsed if entry.silver is not None]
    statuses = [
        SilverUgapExportFactureStatus(
            source=entry.source,
            source_idx=entry.source_idx,
            status=_status(entry),
            status_details=entry.error,
        )
        for entry in parsed
    ]

    rows_writer = TableWriter(silver_table_name, SilverUgapExportFacture, batch_size=batch_size)
    status_writer = TableWriter(silver_table_name + "_status", SilverUgapExportFactureStatus, batch_size=batch_size)
    with rows_writer, status_writer:
        rows_writer.add_all(silver_rows)
        status_writer.add_all(statuses)

    written = rows_writer.written

    if duplicates:
        logger.info(f"Évincé {duplicates} doublons UGAP")
    logger.info(f"Saved {written} rows in {silver_table_name}")


def _status(entry: ParsedUgapRow) -> UgapExportFactureStatus:
    if entry.silver is not None:
        return "Ok"
    return "Duplicat" if entry.error == "Duplicat" else "Validation error"
