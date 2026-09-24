import logging
import re
from typing import Optional

from gesec.data.pipeline.db import load_rows_from_table, save_list_pydantic
from gesec.data.pipeline.layer_2_silver.cpro_export_factur_x_ligne import (
    DEFAULT_TABLE_NAME as SILVER_FACTUR_X_LIGNE_DEFAULT_TABLE_NAME,
)
from gesec.data.pipeline.layer_2_silver.cpro_export_facture_xml_facture import (
    DEFAULT_TABLE_NAME as SILVER_FACTURE_XML_FACTURE_DEFAULT_TABLE_NAME,
)
from gesec.data.pipeline.layer_2_silver.cpro_export_facture_xml_ligne import (
    DEFAULT_TABLE_NAME as SILVER_FACTURE_XML_LIGNE_DEFAULT_TABLE_NAME,
)
from gesec.data.pipeline.layer_2_silver.cpro_export_factures import (
    DEFAULT_TABLE_NAME as SILVER_FACTURE_DEFAULT_TABLE_NAME,
)
from gesec.data.pipeline.layer_2_silver.schemas import (
    SilverCproExportFacture,
    SilverCproExportFactureXmlFacture,
    SilverCproExportFactureXmlLigne,
    SilverCproExportFacturXLigne,
    SilverUgapExportFacture,
)
from gesec.data.pipeline.layer_2_silver.ugap_export_factures import (
    DEFAULT_TABLE_NAME as SILVER_UGAP_DEFAULT_TABLE_NAME,
)
from gesec.data.pipeline.layer_3_gold.constants import UGAP_SIREN
from gesec.data.pipeline.layer_3_gold.schemas import GoldCproExportFactureLigne, GoldUgapLigne, UgapLigneStatus

logger = logging.getLogger(__name__)

TABLE_NAME = "gesec_facture_ligne"
UGAP_LIGNE_TABLE_NAME = "gesec_facture_ugap_ligne"

RE_IDENTIFIANT_LIVRAISON = re.compile(r"^(\d+)-\d+$")


def load_factur_x_rows(table_name: str) -> list[SilverCproExportFacturXLigne]:
    return load_rows_from_table(table_name, SilverCproExportFacturXLigne)


def load_facture_xml_rows(table_name: str) -> list[SilverCproExportFactureXmlLigne]:
    return load_rows_from_table(table_name, SilverCproExportFactureXmlLigne)


def load_silver_factures(table_name: str) -> list[SilverCproExportFacture]:
    return load_rows_from_table(table_name, SilverCproExportFacture)


def load_silver_facture_xml_factures(table_name: str) -> list[SilverCproExportFactureXmlFacture]:
    return load_rows_from_table(table_name, SilverCproExportFactureXmlFacture)


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


def extract_numero_commande_ugap(delivery_id: Optional[str]) -> Optional[str]:
    if delivery_id is None:
        return None
    match = RE_IDENTIFIANT_LIVRAISON.match(delivery_id)
    if match is None:
        logger.warning(f"Identifiant de livraison non conforme: {delivery_id!r}")
        return None
    return normalize_reference(match.group(1))


def resolve_fournisseur_in_fine(line: SilverUgapExportFacture) -> tuple[Optional[str], Optional[str]]:
    if line.titulaire_2_editeurs_multi_editeurs:
        return line.titulaire_2_editeurs_multi_editeurs, line.siren_titulaire_2 or None
    if line.constructeur_hardware_ajout_manuel:
        return line.constructeur_hardware_ajout_manuel, None
    return line.article_code_fourniseur or None, line.siren_titulaire or None


def build_ugap_ligne(
    ugap_line: SilverUgapExportFacture,
    status: UgapLigneStatus,
    id_cpro: Optional[str] = None,
    line_id: str = "",
    status_details: Optional[str] = None,
) -> GoldUgapLigne:
    return GoldUgapLigne(
        source=ugap_line.source,
        source_idx=ugap_line.source_idx,
        id_cpro=id_cpro,
        numero_commande_ugap=ugap_line.cde_client_numero,
        line_id=line_id,
        article_numero=ugap_line.article_numero,
        status=status,
        status_details=status_details,
    )


def match_ugap(
    factures: list[SilverCproExportFacture],
    xml_factures: list[SilverCproExportFactureXmlFacture],
    gold_lines: list[GoldCproExportFactureLigne],
    ugap_lines: list[SilverUgapExportFacture],
) -> tuple[list[GoldCproExportFactureLigne], list[GoldUgapLigne]]:
    """Rapproche les lignes UGAP des lignes gold par commande puis par article.

    La commande est lue dans les métadonnées XML des factures UGAP
    (`cac:Delivery/cbc:ID`, préfixe avant `-`) et comparée à `cde_client_numero`
    normalisé ; l'article est comparé à `item_reference` normalisé. Toutes les
    factures d'une commande sont parcourues : chaque correspondance produit une
    ligne de suivi `matched` et enrichit en une passe `fournisseur_in_fine_*`
    des lignes gold, dont l'ordre d'origine est conservé.
    """
    id_cpros_ugap = {
        facture.identifiant_chorus_pro for facture in factures if is_ugap_facture(facture.fournisseur_identifiant)
    }

    id_cpros_by_commande: dict[str, list[str]] = {}
    for xml_facture in xml_factures:
        if xml_facture.id_cpro not in id_cpros_ugap:
            continue
        commande = extract_numero_commande_ugap(xml_facture.delivery_id)
        if commande is None:
            continue
        id_cpros_by_commande.setdefault(commande, []).append(xml_facture.id_cpro)
    id_cpros_by_commande = {commande: sorted(set(id_cpros)) for commande, id_cpros in id_cpros_by_commande.items()}

    gold_lines_by_id_cpro: dict[str, list[GoldCproExportFactureLigne]] = {}
    for gold_line in gold_lines:
        gold_lines_by_id_cpro.setdefault(gold_line.id_cpro, []).append(gold_line)

    enrichment: dict[tuple[str, str], tuple[Optional[str], Optional[str]]] = {}
    suivi: list[GoldUgapLigne] = []

    for ugap_line in sorted(ugap_lines, key=lambda line: (line.source, line.source_idx)):
        commande = normalize_reference(ugap_line.cde_client_numero)
        article = normalize_reference(ugap_line.article_numero)
        id_cpros = id_cpros_by_commande.get(commande) if commande is not None else None
        if not id_cpros:
            suivi.append(build_ugap_ligne(ugap_line, "facture_inconnue"))
            continue

        found = False
        for id_cpro in id_cpros:
            for gold_line in gold_lines_by_id_cpro.get(id_cpro, []):
                if normalize_reference(gold_line.item_reference) != article:
                    continue
                found = True
                enrichment[(id_cpro, gold_line.line_id)] = resolve_fournisseur_in_fine(ugap_line)
                suivi.append(build_ugap_ligne(ugap_line, "matched", id_cpro=id_cpro, line_id=gold_line.line_id))
        if not found:
            suivi.append(
                build_ugap_ligne(
                    ugap_line,
                    "ligne_absente",
                    id_cpro=id_cpros[0],
                    status_details=f"article absent des {len(id_cpros)} factures de la commande",
                )
            )

    result = []
    for gold_line in gold_lines:
        values = enrichment.get((gold_line.id_cpro, gold_line.line_id))
        if values is None:
            result.append(gold_line)
            continue
        designation, siren = values
        result.append(
            gold_line.model_copy(
                update={
                    "fournisseur_in_fine_designation": designation,
                    "fournisseur_in_fine_siren": siren,
                }
            )
        )

    return result, suivi


def process_to_gold(
    silver_factur_x_table_name: str = SILVER_FACTUR_X_LIGNE_DEFAULT_TABLE_NAME,
    silver_facture_xml_table_name: str = SILVER_FACTURE_XML_LIGNE_DEFAULT_TABLE_NAME,
    silver_facture_table_name: str = SILVER_FACTURE_DEFAULT_TABLE_NAME,
    silver_ugap_table_name: str = SILVER_UGAP_DEFAULT_TABLE_NAME,
    silver_facture_xml_facture_table_name: str = SILVER_FACTURE_XML_FACTURE_DEFAULT_TABLE_NAME,
) -> None:
    factur_x_rows = load_factur_x_rows(silver_factur_x_table_name)
    facture_xml_rows = load_facture_xml_rows(silver_facture_xml_table_name)
    factures = load_silver_factures(silver_facture_table_name)
    xml_factures = load_silver_facture_xml_factures(silver_facture_xml_facture_table_name)
    ugap_rows = load_silver_ugap_rows(silver_ugap_table_name)

    gold_lines = transform_to_gold(factur_x_rows=factur_x_rows, facture_xml_rows=facture_xml_rows)
    logger.info(f"Transformé en {len(gold_lines)} lignes gold depuis les factures XML et Factur-X")

    gold_lines, ugap_lignes = match_ugap(factures, xml_factures, gold_lines, ugap_rows)
    logger.info(f"Rapprochement UGAP: {len(gold_lines)} lignes gold, {len(ugap_lignes)} lignes de suivi")

    if gold_lines:
        save_list_pydantic(gold_lines, TABLE_NAME, if_exists="replace")
    if ugap_lignes:
        save_list_pydantic(ugap_lignes, UGAP_LIGNE_TABLE_NAME, if_exists="replace")
