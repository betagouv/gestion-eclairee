import logging
import re
from collections.abc import Iterable, Iterator, Sequence
from typing import Optional

from sqlalchemy import text

from gesec.data.pipeline.db import (
    DEFAULT_BATCH_SIZE,
    TableWriter,
    execute_sql,
    iter_rows_from_table,
    load_rows_from_table,
)
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
from gesec.data.pipeline.layer_3_gold import extract_pdf_fallback
from gesec.data.pipeline.layer_3_gold.constants import UGAP_SIREN
from gesec.data.pipeline.layer_3_gold.schemas import (
    GoldCproExportFactureLigne,
    GoldFournisseurInFine,
    GoldUgapLigne,
    UgapLigneStatus,
)

logger = logging.getLogger(__name__)

TABLE_NAME = "gesec_facture_ligne"
UGAP_LIGNE_TABLE_NAME = "gesec_facture_ugap_ligne"
FOURNISSEUR_IN_FINE_TABLE_NAME = "gesec_facture_ligne_fournisseur_in_fine"

RE_IDENTIFIANT_LIVRAISON = re.compile(r"^(\d+)-\d+$")


def load_xml_id_cpros(table_name: str) -> set[str]:
    rows = execute_sql(text(f"SELECT DISTINCT id_cpro FROM {table_name}"))
    return {row[0] for row in rows}


def transform_to_gold(
    factur_x_table_name: str = SILVER_FACTUR_X_LIGNE_DEFAULT_TABLE_NAME,
    facture_xml_table_name: str = SILVER_FACTURE_XML_LIGNE_DEFAULT_TABLE_NAME,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Iterator[GoldCproExportFactureLigne]:
    """Prend en priorité les lignes de facture XML, puis celles de factur-x.

    Itère les lignes silver une à une, sans charger les tables entières. Le set
    des `id_cpro` couverts par le XML est conservé en mémoire pour exclure les
    factures déjà traitées côté Factur-X.
    """

    xml_id_cpros = load_xml_id_cpros(facture_xml_table_name)
    covered_ids = set(xml_id_cpros)

    for line in iter_rows_from_table(facture_xml_table_name, SilverCproExportFactureXmlLigne, batch_size=batch_size):
        yield GoldCproExportFactureLigne(**line.model_dump(), source="facture-xml")

    for line in iter_rows_from_table(factur_x_table_name, SilverCproExportFacturXLigne, batch_size=batch_size):
        if line.id_cpro not in xml_id_cpros:
            covered_ids.add(line.id_cpro)
            yield GoldCproExportFactureLigne(**line.model_dump(), source="factur-x")

    yield from extract_pdf_fallback.transform_to_gold(covered_ids=covered_ids, batch_size=batch_size)


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
    if line.titulaire_rang_2:
        return line.titulaire_rang_2, line.siren_titulaire_2 or None
    if line.constructeur_article:
        return line.constructeur_article, None
    return line.designation_titulaire_marche or None, line.siren_titulaire_1 or None


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
        numero_commande_ugap=ugap_line.numero_commande_ugap,
        line_id=line_id,
        article_numero=ugap_line.code_article_ugap,
        status=status,
        status_details=status_details,
    )


def match_ugap(
    factures: Iterable[SilverCproExportFacture],
    xml_factures: Iterable[SilverCproExportFactureXmlFacture],
    ugap_lines: Sequence[SilverUgapExportFacture],
    gold_lines: Iterable[GoldCproExportFactureLigne],
) -> tuple[list[GoldUgapLigne], list[GoldFournisseurInFine]]:
    """Rapproche les lignes UGAP des lignes gold par commande puis par article.

    La commande est lue dans les métadonnées XML des factures UGAP
    (`cac:Delivery/cbc:ID`, préfixe avant `-`) et comparée à `numero_commande_ugap`
    normalisé ; l'article est comparé à `item_reference` normalisé. Toutes les
    factures d'une commande sont parcourues : chaque correspondance produit une
    ligne de suivi `matched` et une ligne d'enrichissement `fournisseur_in_fine`.

    `gold_lines` est consommé une seule fois : seules les lignes des factures
    UGAP sont conservées en mémoire, le reste est ignoré au fil du flux.
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
        if gold_line.id_cpro not in id_cpros_ugap:
            continue
        gold_lines_by_id_cpro.setdefault(gold_line.id_cpro, []).append(gold_line)

    enrichment: dict[tuple[str, str], tuple[Optional[str], Optional[str]]] = {}
    suivi: list[GoldUgapLigne] = []

    for ugap_line in sorted(ugap_lines, key=lambda line: (line.source, line.source_idx)):
        commande = normalize_reference(ugap_line.numero_commande_ugap)
        article = normalize_reference(ugap_line.code_article_ugap)
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

    enrichment_rows = [
        GoldFournisseurInFine(
            id_cpro=id_cpro,
            line_id=line_id,
            fournisseur_in_fine_designation=designation,
            fournisseur_in_fine_siren=siren,
        )
        for (id_cpro, line_id), (designation, siren) in enrichment.items()
        if designation is not None or siren is not None
    ]

    return suivi, enrichment_rows


def process_to_gold(
    silver_factur_x_table_name: str = SILVER_FACTUR_X_LIGNE_DEFAULT_TABLE_NAME,
    silver_facture_xml_table_name: str = SILVER_FACTURE_XML_LIGNE_DEFAULT_TABLE_NAME,
    silver_facture_table_name: str = SILVER_FACTURE_DEFAULT_TABLE_NAME,
    silver_ugap_table_name: str = SILVER_UGAP_DEFAULT_TABLE_NAME,
    silver_facture_xml_facture_table_name: str = SILVER_FACTURE_XML_FACTURE_DEFAULT_TABLE_NAME,
) -> None:
    with TableWriter(TABLE_NAME, GoldCproExportFactureLigne) as gold_writer:
        gold_writer.add_all(
            transform_to_gold(
                factur_x_table_name=silver_factur_x_table_name, facture_xml_table_name=silver_facture_xml_table_name
            )
        )
    logger.info(f"Saved {gold_writer.written} rows in {TABLE_NAME}")

    factures = iter_rows_from_table(silver_facture_table_name, SilverCproExportFacture)
    xml_factures = iter_rows_from_table(silver_facture_xml_facture_table_name, SilverCproExportFactureXmlFacture)
    ugap_rows = load_rows_from_table(silver_ugap_table_name, SilverUgapExportFacture)

    suivi, enrichment = match_ugap(
        factures,
        xml_factures,
        ugap_rows,
        iter_rows_from_table(TABLE_NAME, GoldCproExportFactureLigne),
    )
    logger.info(f"Rapprochement UGAP: {len(suivi)} lignes de suivi, {len(enrichment)} lignes d'enrichissement")

    with TableWriter(UGAP_LIGNE_TABLE_NAME, GoldUgapLigne) as suivi_writer:
        suivi_writer.add_all(suivi)
    logger.info(f"Saved {len(suivi)} rows in {UGAP_LIGNE_TABLE_NAME}")

    with TableWriter(FOURNISSEUR_IN_FINE_TABLE_NAME, GoldFournisseurInFine) as enrichment_writer:
        enrichment_writer.add_all(enrichment)
    logger.info(f"Saved {len(enrichment)} rows in {FOURNISSEUR_IN_FINE_TABLE_NAME}")
