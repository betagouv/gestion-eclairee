import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from pydantic import ValidationError

from gesec.data.pipeline.db import (
    DEFAULT_BATCH_SIZE,
    TableWriter,
    iter_rows_from_table,
)

from ..layer_1_bronze.cpro_export_factures import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME
from ..layer_1_bronze.schemas import BronzeCproExportFacture
from .schemas import (
    CproExportFactureStatus,
    SilverCproExportFacture,
    SilverCproExportFactureProcessingStatus,
)

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]


@dataclass
class ParsedFacture:
    identifiant_chorus_pro: Optional[str]
    date_modification: Optional[date]
    source: str
    source_idx: int
    silver: Optional[SilverCproExportFacture]
    error: Optional[str]

    @property
    def order_key(self) -> tuple[date, str, int]:
        return (self.date_modification or date.min, self.source, self.source_idx)


def parse_facture(bronze: BronzeCproExportFacture) -> ParsedFacture:
    """Filtre le destinataire État (SIRET 11000201100044) et valide le schéma silver."""
    bronze_dict = bronze.model_dump()
    if (
        bronze.destinataire_type_d_identifiant != "Structure avec N° SIRET"
        or bronze.destinataire_identifiant != "11000201100044"
        or bronze.destinataire_designation != "SERVICES DE L'ETAT POUR LA FACTURATION ELECTRONIQUE"
    ):
        error = (
            f"Destinataire invalide: "
            f"type={bronze.destinataire_type_d_identifiant}, "
            f"id={bronze.destinataire_identifiant}, "
            f"designation={bronze.destinataire_designation}"
        )
        silver = None
    else:
        try:
            silver = SilverCproExportFacture.model_validate(bronze_dict)
        except ValidationError as e:
            silver = None
            error = str(e)
        else:
            error = None
    return ParsedFacture(
        identifiant_chorus_pro=bronze.identifiant_chorus_pro,
        date_modification=bronze.date_modification,
        source=bronze.source,
        source_idx=bronze.source_idx,
        silver=silver,
        error=error,
    )


def deduplicate(parsed: list[ParsedFacture]) -> int:
    """Élague en place les doublons, en gardant la facture validée la plus récente.

    Dédoublonne sur `identifiant_chorus_pro` ; à `date_modification` égale (ou
    nulle), l'ordre départage sur `source` puis `source_idx` décroissants. Règle
    déterministe et sans impact métier : seules `date_modification` diverge
    entre doublons. Les entrées évincées voient leur `silver` remis à `None` et
    reçoivent l'erreur `Duplicat`. Renvoie le nombre de doublons évincés.
    """
    kept: dict[str, ParsedFacture] = {}
    duplicates = 0
    for entry in parsed:
        if entry.silver is None:
            continue
        identifiant = entry.silver.identifiant_chorus_pro
        current = kept.get(identifiant)
        if current is None:
            kept[identifiant] = entry
        elif entry.order_key > current.order_key:
            current.silver = None
            current.error = "Duplicat"
            duplicates += 1
            kept[identifiant] = entry
        else:
            entry.silver = None
            entry.error = "Duplicat"
            duplicates += 1
    return duplicates


def process_bronze_to_silver(
    bronze_table_name: str = BRONZE_DEFAULT_TABLE_NAME,
    silver_table_name: str = DEFAULT_TABLE_NAME,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
    """Stream le bronze par pages, dédoublonne en Python, écrit la silver et ses statuts."""
    parsed: list[ParsedFacture] = []
    for bronze in iter_rows_from_table(bronze_table_name, BronzeCproExportFacture, batch_size=batch_size):
        parsed.append(parse_facture(bronze))

    duplicates = deduplicate(parsed)

    silver_factures = [entry.silver for entry in parsed if entry.silver is not None]
    silver_factures_status = [
        SilverCproExportFactureProcessingStatus(
            identifiant_chorus_pro=entry.identifiant_chorus_pro,
            status=_status(entry),
            status_details=entry.error,
        )
        for entry in parsed
    ]

    factures_writer = TableWriter(silver_table_name, SilverCproExportFacture, batch_size=batch_size)
    status_writer = TableWriter(
        silver_table_name + "_status",
        SilverCproExportFactureProcessingStatus,
        batch_size=batch_size,
    )
    with factures_writer, status_writer:
        factures_writer.add_all(silver_factures)
        status_writer.add_all(silver_factures_status)

    written = factures_writer.written

    if duplicates:
        logger.info(f"Évincé {duplicates} doublons sur identifiant_chorus_pro")
    logger.info(f"Saved {written} rows in {silver_table_name}")


def _status(entry: ParsedFacture) -> CproExportFactureStatus:
    if entry.silver is not None:
        return "Ok"
    return "Duplicat" if entry.error == "Duplicat" else "Validation error"
