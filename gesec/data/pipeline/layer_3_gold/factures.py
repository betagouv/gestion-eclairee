import logging
from sqlalchemy import text

from gesec.data.dj_models import Facture
from gesec.data.pipeline.db import create_engine

logger = logging.getLogger(__name__)

from ..layer_2_silver.cpro_export_factures import DEFAULT_TABLE_NAME as SILVER_DEFAULT_TABLE_NAME
from ..layer_2_silver.oda_export_ej_gm_mapping import DEFAULT_TABLE_NAME as SILVER_EJ_GM_MAPPING_DEFAULT_TABLE_NAME
from ..layer_2_silver.services import DEFAULT_TABLE_NAME as SILVER_SERVICES_DEFAULT_TABLE_NAME
from ..layer_2_silver.schemas import SilverCproExportFacture, SilverService


def load_silver_factures(silver_table_name: str) -> list[SilverCproExportFacture]:
    """Récupère toutes les lignes de la table Silver et les convertit en SilverCproExportFacture."""
    engine = create_engine()
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT * FROM {silver_table_name}"))
        rows = result.fetchall()
        return [SilverCproExportFacture(**dict(row._asdict())) for row in rows]


def load_silver_oda_ej_to_gm_mapping(silver_table_name: str) -> dict[str, list[str]]:
    engine = create_engine()
    with engine.connect() as conn:
        result = conn.execute(text(f"""
            SELECT numero_ej_reference_facture, segment 
            FROM {silver_table_name}""")
        )
        rows = result.fetchall()
    mapping = {}
    for ej, gm in rows:
        mapping.setdefault(ej, set()).add(gm)
    for ej, gm_list in mapping.items():
        mapping[ej] = sorted(gm_list)
    return mapping


def load_silver_services(table_name: str) -> list[SilverService]:
    engine = create_engine()
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT code, name, ministere FROM {table_name}"))
        rows = result.fetchall()
    return [SilverService(**row._asdict()) for row in rows]


def transform_silver_to_gold(
        silver_factures: list[SilverCproExportFacture],
        silver_ej_to_gm_mapping: dict[str, list[str]],
        silver_services: list[SilverService],
) -> list[Facture]:
    """Transforme une liste de SilverCproExportFacture en liste de Facture (modèle Django)."""
    result = []
    service_by_code: dict[str, SilverService] = {
        service.code: service
        for service in silver_services
    }
    for silver in silver_factures:
        gm_list = silver_ej_to_gm_mapping.get(silver.numero_du_bon_de_commande)
        service = service_by_code.get(silver.destinataire_code_service)
        fac = Facture(
            source=silver.source,
            source_idx=silver.source_idx,
            identifiant_chorus_pro=silver.identifiant_chorus_pro,
            numero=silver.numero,
            date_etat_courant=silver.date_etat_courant,
            date_modification=silver.date_modification,
            montant_a_payer=silver.montant_a_payer,
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
            ministere=service.ministere if service else "INCONNU",
        )
        result.append(fac)
    return result


def process_silver_to_gold(
        silver_table_name: str = SILVER_DEFAULT_TABLE_NAME,
        silver_ej_gm_mapping_table_name: str = SILVER_EJ_GM_MAPPING_DEFAULT_TABLE_NAME,
        silver_services_table_name: str = SILVER_SERVICES_DEFAULT_TABLE_NAME,
) -> None:
    """
    Pipeline complet :
    1. Charge les données Silver
    2. Les transforme en Facture (modèle Django gold)
    3. Sauvegarde dans la table Facture avec bulk_create et update_conflicts
    """
    silver_factures = load_silver_factures(silver_table_name)
    logger.info(f"Chargé {len(silver_factures)} items depuis la table silver {silver_table_name}")
    silver_ej_to_gm_mapping = load_silver_oda_ej_to_gm_mapping(silver_ej_gm_mapping_table_name)
    logger.info(f"Chargé {len(silver_ej_to_gm_mapping)} items depuis la table silver {silver_ej_gm_mapping_table_name}")
    silver_services = load_silver_services(silver_services_table_name)
    logger.info(f"Chargé {len(silver_services)} items depuis la table silver {silver_services_table_name}")

    gold_factures = transform_silver_to_gold(silver_factures, silver_ej_to_gm_mapping, silver_services)
    logger.info(f"Transformé en {len(gold_factures)} lignes gold après transformation")

    update_fields = [field.name for field in Facture._meta.get_fields() if field.name not in ("id", "created_at")]
    Facture.objects.bulk_create(
        gold_factures,
        update_conflicts=True,
        update_fields=update_fields,
        unique_fields=["identifiant_chorus_pro"],
    )
    logger.info("Process silver_to_gold terminé avec succès")
