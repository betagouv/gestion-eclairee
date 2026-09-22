import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from gesec.data.pipeline.db import load_rows_from_table, save_list_pydantic
from gesec.data.pipeline.layer_2_silver.cpro_export_factur_x_ligne import (
    DEFAULT_TABLE_NAME as SILVER_FACTUR_X_LIGNE_DEFAULT_TABLE_NAME,
)
from gesec.data.pipeline.layer_2_silver.cpro_export_facture_xml_ligne import (
    DEFAULT_TABLE_NAME as SILVER_FACTURE_XML_LIGNE_DEFAULT_TABLE_NAME,
)
from gesec.data.pipeline.layer_2_silver.cpro_export_factures import (
    DEFAULT_TABLE_NAME as SILVER_FACTURE_DEFAULT_TABLE_NAME,
)
from gesec.data.pipeline.layer_2_silver.schemas import (
    SilverCproExportFacture,
    SilverCproExportFactureXmlLigne,
    SilverCproExportFacturXLigne,
    SilverUgapExportFacture,
)
from gesec.data.pipeline.layer_2_silver.ugap_export_factures import (
    DEFAULT_TABLE_NAME as SILVER_UGAP_DEFAULT_TABLE_NAME,
)
from gesec.data.pipeline.layer_3_gold.constants import UGAP_SIREN
from gesec.data.pipeline.layer_3_gold.schemas import GoldCproExportFactureLigne, GoldUgapLigne

logger = logging.getLogger(__name__)

TABLE_NAME = "gesec_facture_ligne"
UGAP_LIGNE_TABLE_NAME = "gesec_facture_ugap_ligne"


def load_factur_x_rows(table_name: str) -> list[SilverCproExportFacturXLigne]:
    return load_rows_from_table(table_name, SilverCproExportFacturXLigne)


def load_facture_xml_rows(table_name: str) -> list[SilverCproExportFactureXmlLigne]:
    return load_rows_from_table(table_name, SilverCproExportFactureXmlLigne)


def load_silver_factures(table_name: str) -> list[SilverCproExportFacture]:
    return load_rows_from_table(table_name, SilverCproExportFacture)


def load_silver_ugap_rows(table_name: str) -> list[SilverUgapExportFacture]:
    return load_rows_from_table(table_name, SilverUgapExportFacture)


def transform_to_gold(
    factur_x_rows: list[SilverCproExportFacturXLigne], facture_xml_rows: list[SilverCproExportFactureXmlLigne]
) -> list[GoldCproExportFactureLigne]:
    """Prend en priorité les lignes de facture XML, puis celles de factur-x."""

    # Groupe les lignes par id_cpro
    factur_x_by_id_cpro = {}
    for fac in factur_x_rows:
        factur_x_by_id_cpro.setdefault(fac.id_cpro, []).append(fac)
    facture_xml_by_id_cpro = {}
    for fac in facture_xml_rows:
        facture_xml_by_id_cpro.setdefault(fac.id_cpro, []).append(fac)

    # Merge les lignes
    result = []
    processed_ids = set()
    for id_cpro, fac_lignes in facture_xml_by_id_cpro.items():
        for fac_ligne in fac_lignes:
            result.append(
                GoldCproExportFactureLigne(
                    **fac_ligne.model_dump(),
                    source="facture-xml",
                )
            )
        processed_ids.add(id_cpro)
    for id_cpro, fac_lignes in factur_x_by_id_cpro.items():
        if id_cpro in processed_ids:
            continue
        for fac_ligne in fac_lignes:
            result.append(
                GoldCproExportFactureLigne(
                    **fac_ligne.model_dump(),
                    source="factur-x",
                )
            )
        processed_ids.add(id_cpro)

    return result


def is_ugap_facture(fournisseur_identifiant: Optional[str]) -> bool:
    return bool(fournisseur_identifiant) and fournisseur_identifiant.startswith(UGAP_SIREN)


def normalize_reference(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        value = value.lstrip("0") or "0"
    return value


def resolve_fournisseur_in_fine(line: SilverUgapExportFacture) -> tuple[Optional[str], Optional[str]]:
    designation = (
        line.titulaire_2_editeurs_multi_editeurs
        or line.constructeur_hardware_ajout_manuel
        or line.article_code_fourniseur
        or None
    )
    siren = line.siren_titulaire_2 or line.siren_titulaire or None
    return designation, siren


def compute_tva_ratio(
    ce_ht: Optional[Decimal],
    tva_collectee: Optional[Decimal],
    ce_ttc: Optional[Decimal],
) -> Decimal:
    if ce_ht is None or ce_ht == 0:
        raise ValueError("Cannot compute TVA ratio: missing or zero CE HT")
    if tva_collectee is not None:
        return tva_collectee / ce_ht
    if ce_ttc is not None:
        return (ce_ttc - ce_ht) / ce_ht
    raise ValueError("Cannot compute TVA ratio: missing TVA Collectée and CE TTC")


def build_ugap_lines(id_cpro: str, ugap_lines: list[SilverUgapExportFacture]) -> list[GoldCproExportFactureLigne]:
    result = []
    for line in ugap_lines:
        if not line.article_ndeg_vue_adv:
            raise ValueError(f"Missing ADV name for {id_cpro} line {line.line_id}")
        if line.montant_facture_ht is None:
            raise ValueError(f"Missing billed amount for {id_cpro} line {line.line_id}")

        ratio = compute_tva_ratio(line.ce_ht, line.tva_collectee, line.ce_ttc)
        line_amount_excl_tax = line.montant_facture_ht
        line_amount_vat = line_amount_excl_tax * ratio
        line_amount_incl_tax = (line_amount_excl_tax + line_amount_vat).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        quantity = line.qte_commandees
        unit_price = line_amount_excl_tax / quantity if quantity is not None and quantity > 0 else None
        designation, siren = resolve_fournisseur_in_fine(line)
        item_description = "\n".join(
            value
            for value in (
                line.texte_adv_ligne_1,
                line.texte_adv_ligne_2,
                line.texte_adv_ligne_3,
                line.texte_adv_ligne_4,
                line.article_code_lot,
                line.designation_du_lot,
            )
            if value
        )
        result.append(
            GoldCproExportFactureLigne(
                id_cpro=id_cpro,
                source="ugap",
                xml_schema=None,
                line_id=str(line.line_id),
                item_name=line.article_ndeg_vue_adv,
                item_description=item_description,
                item_reference=line.article_ndeg,
                quantity=quantity,
                quantity_unit_code="",
                unit_price=unit_price,
                line_amount_excl_tax=line_amount_excl_tax,
                line_amount_vat=line_amount_vat,
                line_amount_incl_tax=line_amount_incl_tax,
                currency="EUR",
                fournisseur_in_fine_designation=designation,
                fournisseur_in_fine_siren=siren,
            )
        )
    return result


def build_ugap_ligne(
    ugap_line: SilverUgapExportFacture,
    status: str,
    id_cpro: Optional[str] = None,
    line_id: str = "",
    status_details: Optional[str] = None,
) -> GoldUgapLigne:
    return GoldUgapLigne(
        source=ugap_line.source,
        source_idx=ugap_line.source_idx,
        id_cpro=id_cpro,
        numero_ugap=ugap_line.cde_client_ndeg,
        line_id=line_id,
        article_ndeg=ugap_line.article_ndeg,
        status=status,
        status_details=status_details,
    )


def enrich_existing_lines(
    gold_lines: list[GoldCproExportFactureLigne],
    ugap_lines: list[SilverUgapExportFacture],
) -> tuple[list[GoldCproExportFactureLigne], dict[tuple[str, str], str]]:
    """Enrichit les lignes gold existantes et retourne les lignes UGAP consommées."""
    by_reference = {normalize_reference(line.article_ndeg): line for line in ugap_lines}
    enriched_lines = []
    consumed: dict[tuple[str, str], str] = {}
    for gold_line in gold_lines:
        ugap_line = by_reference.get(normalize_reference(gold_line.item_reference))
        if ugap_line is None:
            enriched_lines.append(gold_line)
            continue
        designation, siren = resolve_fournisseur_in_fine(ugap_line)
        enriched_lines.append(
            gold_line.model_copy(
                update={
                    "fournisseur_in_fine_designation": designation,
                    "fournisseur_in_fine_siren": siren,
                }
            )
        )
        consumed[(ugap_line.source, ugap_line.source_idx)] = gold_line.line_id
    return enriched_lines, consumed


def match_ugap(
    factures: list[SilverCproExportFacture],
    gold_lines: list[GoldCproExportFactureLigne],
    ugap_lines: list[SilverUgapExportFacture],
) -> tuple[list[GoldCproExportFactureLigne], list[GoldUgapLigne]]:
    """Rapproche les lignes UGAP des factures et lignes gold.

    La facture est rapprochée par `numero == cde_client_ndeg`, dans le périmètre
    des factures dont le fournisseur est l'UGAP, puis la ligne par
    `item_reference == article_ndeg`. Chaque ligne UGAP est suivie dans une
    ligne de suivi unique. En cas de re-dépôt (plusieurs `id_cpro` pour un même
    numero), le premier traité l'emporte.
    """
    numero_to_id_cpros: dict[str, list[str]] = {}
    for facture in factures:
        if is_ugap_facture(facture.fournisseur_identifiant):
            numero_to_id_cpros.setdefault(facture.numero, []).append(facture.identifiant_chorus_pro)

    ugap_lines_by_numero: dict[str, list[SilverUgapExportFacture]] = {}
    for ugap_line in ugap_lines:
        ugap_lines_by_numero.setdefault(ugap_line.cde_client_ndeg, []).append(ugap_line)

    gold_lines_by_id_cpro: dict[str, list[GoldCproExportFactureLigne]] = {}
    for gold_line in gold_lines:
        gold_lines_by_id_cpro.setdefault(gold_line.id_cpro, []).append(gold_line)

    suivi = {
        (ugap_line.source, ugap_line.source_idx): build_ugap_ligne(ugap_line, "facture_inconnue")
        for ugap_line in ugap_lines
    }
    replacements: dict[str, list[GoldCproExportFactureLigne]] = {}
    created_lines: list[GoldCproExportFactureLigne] = []

    for numero, id_cpros in numero_to_id_cpros.items():
        export_lines = ugap_lines_by_numero.get(numero, [])
        if not export_lines:
            continue
        for id_cpro in id_cpros:
            existing_lines = gold_lines_by_id_cpro.get(id_cpro, [])
            if existing_lines:
                enriched_lines, consumed = enrich_existing_lines(existing_lines, export_lines)
                replacements[id_cpro] = enriched_lines
                for ugap_line in export_lines:
                    key = (ugap_line.source, ugap_line.source_idx)
                    if key in consumed:
                        resolved = build_ugap_ligne(ugap_line, "matched", id_cpro=id_cpro, line_id=consumed[key])
                    else:
                        resolved = build_ugap_ligne(ugap_line, "ligne_absente", id_cpro=id_cpro)
                    if suivi[key].status == "facture_inconnue":
                        suivi[key] = resolved
            else:
                lines = build_ugap_lines(id_cpro, export_lines)
                created_lines.extend(lines)
                for ugap_line, gold_line in zip(export_lines, lines):
                    key = (ugap_line.source, ugap_line.source_idx)
                    if suivi[key].status == "facture_inconnue":
                        suivi[key] = build_ugap_ligne(ugap_line, "created", id_cpro=id_cpro, line_id=gold_line.line_id)

    result = []
    replaced_ids = set()
    for gold_line in gold_lines:
        replacement = replacements.get(gold_line.id_cpro)
        if replacement is None:
            result.append(gold_line)
        elif gold_line.id_cpro not in replaced_ids:
            result.extend(replacement)
            replaced_ids.add(gold_line.id_cpro)
    result.extend(created_lines)

    return result, list(suivi.values())


def process_to_gold(
    silver_factur_x_table_name: str = SILVER_FACTUR_X_LIGNE_DEFAULT_TABLE_NAME,
    silver_facture_xml_table_name: str = SILVER_FACTURE_XML_LIGNE_DEFAULT_TABLE_NAME,
    silver_facture_table_name: str = SILVER_FACTURE_DEFAULT_TABLE_NAME,
    silver_ugap_table_name: str = SILVER_UGAP_DEFAULT_TABLE_NAME,
) -> None:
    factur_x_rows = load_factur_x_rows(silver_factur_x_table_name)
    facture_xml_rows = load_facture_xml_rows(silver_facture_xml_table_name)
    factures = load_silver_factures(silver_facture_table_name)
    ugap_rows = load_silver_ugap_rows(silver_ugap_table_name)

    gold_lines = transform_to_gold(factur_x_rows=factur_x_rows, facture_xml_rows=facture_xml_rows)
    logger.info(f"Transformé en {len(gold_lines)} lignes gold depuis les factures XML et Factur-X")

    gold_lines, ugap_lignes = match_ugap(factures, gold_lines, ugap_rows)
    logger.info(f"Rapprochement UGAP: {len(gold_lines)} lignes gold, {len(ugap_lignes)} lignes de suivi")

    if gold_lines:
        save_list_pydantic(gold_lines, TABLE_NAME, if_exists="replace")
    if ugap_lignes:
        save_list_pydantic(ugap_lignes, UGAP_LIGNE_TABLE_NAME, if_exists="replace")
