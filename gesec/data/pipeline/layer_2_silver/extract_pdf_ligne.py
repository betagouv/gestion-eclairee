"""Transformation des lignes PDF extraites en silver.

Le silver ne dépend pas de `gesec_facture` (gold) : il se contente de décoder ce
que le LLM a renvoyé et de reconstruire localement les trois montants quand deux
d'entre eux sont présents. La complétion via les taux d'en-tête et le contrôle
des totaux facture sont du ressort du gold.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from gesec.data.extract_pdf.schemas import ExtractedFacture, ExtractedLigne
from gesec.data.pipeline.layer_2_silver.schemas import SilverExtractPdfLigne

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]

LINE_TOLERANCE = Decimal("0.02")


def derive_amounts(ligne: ExtractedLigne) -> tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal]]:
    """Reconstruit HT/TVA/TTC à partir des seuls montants renvoyés par le LLM."""
    ht = ligne.line_amount_excl_tax
    ttc = ligne.line_amount_incl_tax
    tva = ligne.line_amount_vat

    if ht is None and ttc is not None and tva is not None:
        ht = ttc - tva
    if tva is None and ht is not None and ttc is not None:
        tva = ttc - ht
    if ttc is None and ht is not None and tva is not None:
        ttc = ht + tva

    return ht, ttc, tva


def transform_to_silver(
    facture: ExtractedFacture,
    *,
    id_cpro: str,
    pdf_filename: str,
) -> tuple[list[SilverExtractPdfLigne], str | None]:
    seen_line_ids: set[str] = set()
    lignes: list[SilverExtractPdfLigne] = []

    for ligne in facture.lignes:
        if ligne.line_id in seen_line_ids:
            return [], f"line_id dupliqué : {ligne.line_id!r}"
        seen_line_ids.add(ligne.line_id)

        ht, ttc, tva = derive_amounts(ligne)
        if ht is not None and ttc is not None and tva is not None and abs(ht + tva - ttc) > LINE_TOLERANCE:
            return [], f"HT + TVA != TTC ligne {ligne.line_id!r}: {ht} + {tva} != {ttc}"

        lignes.append(
            SilverExtractPdfLigne(
                id_cpro=id_cpro,
                pdf_filename=pdf_filename,
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

    return lignes, None
