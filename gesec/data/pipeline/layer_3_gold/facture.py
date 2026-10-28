import logging
from collections.abc import Iterator

from sqlalchemy import inspect, text

from gesec.data.pipeline.db import TableWriter, create_engine, iter_rows_from_table

from ..layer_2_silver.cpro_export_factures import DEFAULT_TABLE_NAME as SILVER_DEFAULT_TABLE_NAME
from ..layer_2_silver.extract_pdf_facture import DEFAULT_TABLE_NAME as SILVER_PDF_FACTURE_TABLE_NAME
from ..layer_2_silver.oda_export_ej_gm_mapping import DEFAULT_TABLE_NAME as SILVER_EJ_GM_MAPPING_DEFAULT_TABLE_NAME
from ..layer_2_silver.schemas import SilverCproExportFacture, SilverService
from ..layer_2_silver.services import DEFAULT_TABLE_NAME as SILVER_SERVICES_DEFAULT_TABLE_NAME
from .schemas import GoldFacture

logger = logging.getLogger(__name__)

TABLE_NAME = "gesec_facture"


def load_silver_ej_to_gm_mapping(silver_table_name: str) -> dict[str, list[str]]:
    engine = create_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text(f"""
            SELECT numero_ej_reference_facture, segment 
            FROM {silver_table_name}""")
        )
        rows = result.fetchall()
    mapping: dict[str, set[str]] = {}
    for ej, gm in rows:
        mapping.setdefault(ej, set()).add(gm)
    return {ej: sorted(gm_list) for ej, gm_list in mapping.items()}


def load_silver_services(table_name: str) -> list[SilverService]:
    engine = create_engine()
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT code, name, ministere FROM {table_name}"))
        rows = result.fetchall()
    return [SilverService(**row._asdict()) for row in rows]


def load_silver_pdf_objects(table_name: str) -> dict[str, str]:
    engine = create_engine()
    if not inspect(engine).has_table(table_name):
        return {}
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT id_cpro, objet_facture FROM {table_name} "
                "WHERE objet_facture IS NOT NULL AND btrim(objet_facture) <> ''"
            )
        ).fetchall()
    return {row.id_cpro: row.objet_facture for row in rows}


def transform_silver_to_gold(
    silver_factures: Iterator[SilverCproExportFacture],
    silver_ej_to_gm_mapping: dict[str, list[str]],
    silver_services: list[SilverService],
    pdf_objects: dict[str, str] | None = None,
) -> Iterator[GoldFacture]:
    """Transforme les SilverCproExportFacture en GoldFacture, dans l'ordre de lecture."""
    service_by_code: dict[str, SilverService] = {service.code: service for service in silver_services}
    pdf_objects = pdf_objects or {}
    for idx, silver in enumerate(silver_factures, start=1):
        gm_list = silver_ej_to_gm_mapping.get(silver.numero_du_bon_de_commande)
        service = service_by_code.get(silver.destinataire_code_service)
        yield GoldFacture(
            id=idx,
            source=silver.source,
            source_idx=silver.source_idx,
            identifiant_chorus_pro=silver.identifiant_chorus_pro,
            numero=silver.numero,
            objet_facture=pdf_objects.get(silver.identifiant_chorus_pro),
            date_etat_courant=silver.date_etat_courant,
            date_modification=silver.date_modification,
            mt_ht=silver.mt_ht,
            mt_ttc=silver.mt_ttc,
            montant_tva=silver.montant_tva or 0,
            montant_a_payer=silver.montant_a_payer,
            montant_ttc_avant_remise=silver.montant_ttc_avant_remise,
            montant_remise_globale_ttc=silver.montant_remise_globale_ttc,
            fournisseur_type_d_identifiant=silver.fournisseur_type_d_identifiant,
            fournisseur_identifiant=silver.fournisseur_identifiant,
            fournisseur_designation=silver.fournisseur_designation,
            destinataire_code_service=silver.destinataire_code_service,
            destinataire_service=silver.destinataire_service,
            devise_de_la_facture=silver.devise_de_la_facture,
            numero_du_bon_de_commande=silver.numero_du_bon_de_commande,
            numero_de_marche=silver.numero_de_marche,
            # GM
            gm=gm_list[0] if gm_list else None,
            gm_list=gm_list if gm_list else None,
            gm_multi=(len(gm_list) > 1) if gm_list else None,
            # Ministere
            ministere=service.ministere or "INCONNU" if service else "INCONNU",
        )


def process_silver_to_gold(
    silver_table_name: str = SILVER_DEFAULT_TABLE_NAME,
    silver_ej_gm_mapping_table_name: str = SILVER_EJ_GM_MAPPING_DEFAULT_TABLE_NAME,
    silver_services_table_name: str = SILVER_SERVICES_DEFAULT_TABLE_NAME,
    silver_pdf_facture_table_name: str = SILVER_PDF_FACTURE_TABLE_NAME,
) -> None:
    """
    Pipeline complet :
    1. Charge les données Silver
    2. Les transforme en GoldFacture
    3. Sauvegarde dans la table gesec_facture
    """
    silver_ej_to_gm_mapping = load_silver_ej_to_gm_mapping(silver_ej_gm_mapping_table_name)
    logger.info(f"Chargé {len(silver_ej_to_gm_mapping)} items depuis la table silver {silver_ej_gm_mapping_table_name}")
    silver_services = load_silver_services(silver_services_table_name)
    logger.info(f"Chargé {len(silver_services)} items depuis la table silver {silver_services_table_name}")
    pdf_objects = load_silver_pdf_objects(silver_pdf_facture_table_name)
    logger.info(f"Chargé {len(pdf_objects)} objets PDF depuis {silver_pdf_facture_table_name}")

    silver_factures = iter_rows_from_table(silver_table_name, SilverCproExportFacture)

    with TableWriter(TABLE_NAME, GoldFacture) as writer:
        writer.add_all(transform_silver_to_gold(silver_factures, silver_ej_to_gm_mapping, silver_services, pdf_objects))

    logger.info(f"Process silver_to_gold terminé avec succès : {writer.written} lignes dans {TABLE_NAME}")
