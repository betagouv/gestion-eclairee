"""Fallback gold des lignes extraites depuis les PDF non DEMAT.

Le silver ne porte que les montants décodés par le LLM. C'est ici, où
`gesec_facture` est disponible, que les montants manquants sont complétés via
les taux de l'en-tête puis que la facture est validée avant insertion.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text

from gesec.data.pipeline.db import DEFAULT_BATCH_SIZE, execute_sql, iter_rows_from_table
from gesec.data.pipeline.layer_2_silver.extract_pdf_ligne import DEFAULT_TABLE_NAME as SILVER_PDF_LIGNE_TABLE_NAME
from gesec.data.pipeline.layer_2_silver.schemas import SilverExtractPdfLigne
from gesec.data.pipeline.layer_3_gold.schemas import GoldCproExportFactureLigne

logger = logging.getLogger(__name__)

FACTURE_TABLE_NAME = "gesec_facture"

LINE_TOLERANCE = Decimal("0.02")
TOTAL_TOLERANCE = Decimal("0.005")


@dataclass(frozen=True)
class FactureTotals:
    mt_ht: Decimal
    mt_ttc: Decimal
    montant_tva: Decimal


def load_facture_totals(ids: Sequence[str]) -> dict[str, FactureTotals]:
    if not ids:
        return {}
    rows = execute_sql(
        text(
            "SELECT identifiant_chorus_pro, mt_ht, mt_ttc, montant_tva "
            "FROM gesec_facture WHERE identifiant_chorus_pro = ANY(:ids)"
        ),
        {"ids": list(ids)},
    )
    return {
        row.identifiant_chorus_pro: FactureTotals(
            mt_ht=row.mt_ht,
            mt_ttc=row.mt_ttc,
            montant_tva=row.montant_tva,
        )
        for row in rows
    }


def _derive_amounts(ligne: SilverExtractPdfLigne, totals: FactureTotals) -> tuple[Decimal, Decimal, Decimal] | None:
    ht = ligne.line_amount_excl_tax
    ttc = ligne.line_amount_incl_tax
    tva = ligne.line_amount_vat

    tva_rate = totals.montant_tva / totals.mt_ht if totals.mt_ht else None
    ttc_rate = totals.mt_ttc / totals.mt_ht if totals.mt_ht else None

    if tva is None and ht is not None and tva_rate is not None:
        tva = ht * tva_rate
        if ttc is None:
            ttc = ht + tva
    if ttc is None and ht is not None and ttc_rate is not None:
        ttc = ht * ttc_rate
        if tva is None:
            tva = ttc - ht

    if ht is None or ttc is None or tva is None:
        return None
    return ht, ttc, tva


def _within_tolerance(total: Decimal, expected: Decimal) -> bool:
    return abs(total - expected) <= abs(expected) * TOTAL_TOLERANCE


def _translate_invoice(
    id_cpro: str,
    lignes: list[SilverExtractPdfLigne],
    totals: FactureTotals,
) -> list[GoldCproExportFactureLigne]:
    translated: list[GoldCproExportFactureLigne] = []
    for ligne in lignes:
        amounts = _derive_amounts(ligne, totals)
        if amounts is None:
            logger.warning("Montants incomplets pour %s ligne %s, facture rejetée", id_cpro, ligne.line_id)
            return []
        ht, ttc, tva = amounts
        if abs(ht + tva - ttc) > LINE_TOLERANCE:
            logger.warning("HT + TVA != TTC pour %s ligne %s, facture rejetée", id_cpro, ligne.line_id)
            return []
        translated.append(
            GoldCproExportFactureLigne(
                id_cpro=id_cpro,
                source=f"extract_pdf:{ligne.pdf_filename}",
                xml_schema=None,
                line_id=ligne.line_id,
                item_name=ligne.item_name,
                item_description=ligne.item_description,
                item_reference=ligne.item_reference,
                quantity=ligne.quantity,
                quantity_unit_code=ligne.quantity_unit_code,
                unit_price=ligne.unit_price,
                line_amount_excl_tax=ht,
                line_amount_incl_tax=ttc,
                line_amount_vat=tva,
                currency=ligne.currency,
            )
        )

    total_ht = sum((ligne.line_amount_excl_tax for ligne in translated), Decimal("0"))
    total_ttc = sum((ligne.line_amount_incl_tax for ligne in translated), Decimal("0"))
    if not _within_tolerance(total_ht, totals.mt_ht) or not _within_tolerance(total_ttc, totals.mt_ttc):
        logger.warning("Totaux PDF hors tolérance pour %s, facture rejetée", id_cpro)
        return []
    return translated


def transform_to_gold(
    *,
    covered_ids: set[str],
    silver_table_name: str = SILVER_PDF_LIGNE_TABLE_NAME,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Iterator[GoldCproExportFactureLigne]:
    """Produit les lignes PDF des factures sans aucune ligne XML/Factur-X.

    `covered_ids` porte les factures déjà couvertes par les lignes gold XML ou
    Factur-X : leurs PDF sont ignorés. Les factures sans en-tête `gesec_facture`
    ou dont les montants ne se réconcilient pas sont écartées.

    Les lignes silver sont lues triées par `id_cpro`, regroupées facture par
    facture, puis les totaux d'en-tête sont chargés par fenêtre bornée de
    factures : jamais l'ensemble du périmètre d'un coup.
    """
    query = f"SELECT * FROM {silver_table_name} ORDER BY id_cpro"
    rows = iter_rows_from_table(silver_table_name, SilverExtractPdfLigne, batch_size=batch_size, query=query)

    windows: list[list[SilverExtractPdfLigne]] = []
    grouped: list[SilverExtractPdfLigne] = []
    previous_id: str | None = None

    def translate_windows() -> Iterator[GoldCproExportFactureLigne]:
        ids = [facture[0].id_cpro for facture in windows]
        totals = load_facture_totals(ids)
        for facture in windows:
            id_cpro = facture[0].id_cpro
            facture_totals = totals.get(id_cpro)
            if facture_totals is None:
                logger.warning("En-tête absent de gesec_facture pour %s, PDF ignoré", id_cpro)
                continue
            yield from _translate_invoice(id_cpro, facture, facture_totals)

    for ligne in rows:
        if ligne.id_cpro in covered_ids:
            continue
        if previous_id is not None and ligne.id_cpro != previous_id:
            windows.append(grouped)
            grouped = []
            if len(windows) >= batch_size:
                yield from translate_windows()
                windows = []
        previous_id = ligne.id_cpro
        grouped.append(ligne)

    if grouped:
        windows.append(grouped)
    yield from translate_windows()
