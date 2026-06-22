from sqlalchemy import text

from gesec.data.dj_models import Facture
from gesec.data.pipeline.db import create_engine

from ..layer_2_silver.cpro_export_factures import DEFAULT_TABLE_NAME as SILVER_DEFAULT_TABLE_NAME
from ..layer_2_silver.schemas import SilverCproExportFacture


def load_silver_factures(silver_table_name: str) -> list[SilverCproExportFacture]:
    """Récupère toutes les lignes de la table Silver et les convertit en SilverCproExportFacture."""
    engine = create_engine()
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT * FROM {silver_table_name}"))
        rows = result.fetchall()
        return [SilverCproExportFacture(**dict(row._asdict())) for row in rows]


def transform_silver_to_gold(silver_factures: list[SilverCproExportFacture]) -> list[Facture]:
    """Transforme une liste de SilverCproExportFacture en liste de Facture (modèle Django)."""
    return [
        Facture(
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
        )
        for silver in silver_factures
    ]


def process_silver_to_gold(silver_table_name: str = SILVER_DEFAULT_TABLE_NAME) -> None:
    """
    Pipeline complet :
    1. Charge les données Silver
    2. Les transforme en Facture (modèle Django gold)
    3. Sauvegarde dans la table Facture avec bulk_create et update_conflicts
    """
    silver_factures = load_silver_factures(silver_table_name)
    gold_factures = transform_silver_to_gold(silver_factures)
    update_fields = [field.name for field in Facture._meta.get_fields() if field.name not in ("id", "created_at")]
    Facture.objects.bulk_create(
        gold_factures,
        update_conflicts=True,
        update_fields=update_fields,
        unique_fields=["identifiant_chorus_pro"],
    )
