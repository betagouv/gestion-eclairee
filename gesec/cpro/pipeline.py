from pydantic import ValidationError
from sqlalchemy import text

from gesec.cpro.db import create_engine, load_bronze_factures_cpro_export, save_list_pydantic
from gesec.cpro.dj_models import Facture
from gesec.cpro.schemas import BronzeCproExportFacture, SilverCproExportFacture, SilverCproExportFactureProcessingStatus


def transform_bronze_to_silver(
    bronze_factures: list[BronzeCproExportFacture],
) -> tuple[list[SilverCproExportFacture], list[SilverCproExportFactureProcessingStatus]]:
    """
    Transforme une liste de BronzeCproExportFacture en SilverCproExportFacture.
    - Filtre les lignes invalides (qui ne respectent pas le schema Silver)
    - Filtre les lignes où etat_courant != "Mise en paiement"
    - Dédoublonne sur identifiant_chorus_pro (garde la première occurrence)
    """
    silver_factures: list[SilverCproExportFacture] = []
    list_status: list[SilverCproExportFactureProcessingStatus] = []
    seen_ids: set = set()

    for bronze_facture in bronze_factures:
        bronze_facture_dict = bronze_facture.model_dump()

        # Vérifier que l'état est "Mise en paiement"
        if bronze_facture.etat_courant != "Mise en paiement":
            status = "Validation error"
            status_details = f"Etat courant invalide: {bronze_facture.etat_courant}"
        # Vérifier les champs destinataire
        elif (
            bronze_facture.destinataire_type_d_identifiant != "Structure avec N° SIRET"
            or bronze_facture.destinataire_identifiant != "11000201100044"
            or bronze_facture.destinataire_designation != "SERVICES DE L'ETAT POUR LA FACTURATION ELECTRONIQUE"
        ):
            status = "Validation error"
            status_details = (
                f"Destinataire invalide: "
                f"type={bronze_facture.destinataire_type_d_identifiant}, "
                f"id={bronze_facture.destinataire_identifiant}, "
                f"designation={bronze_facture.destinataire_designation}"
            )
        else:
            try:
                silver_facture = SilverCproExportFacture.model_validate(bronze_facture_dict)
            except ValidationError as e:
                status = "Validation error"
                status_details = str(e)
            else:
                if silver_facture.identifiant_chorus_pro in seen_ids:
                    status = "Duplicat"
                    status_details = None
                else:
                    seen_ids.add(silver_facture.identifiant_chorus_pro)
                    silver_factures.append(silver_facture)
                    status = "Ok"
                    status_details = None

        list_status.append(
            SilverCproExportFactureProcessingStatus(
                **bronze_facture_dict,
                status=status,
                status_details=status_details,
            )
        )

    return silver_factures, list_status


def process_bronze_to_silver(
    bronze_table_name: str, silver_table_name: str
) -> tuple[list[SilverCproExportFacture], list[SilverCproExportFactureProcessingStatus]]:
    """
    Pipeline complet :
    1. Charge les données Bronze
    2. Les transforme en Silver (filtre + dédoublonne)
    3. Sauvegarde dans la table Silver (drop + recrée)
    """
    bronze_factures = load_bronze_factures_cpro_export(bronze_table_name)
    silver_factures, silver_factures_status = transform_bronze_to_silver(bronze_factures)
    save_list_pydantic(silver_factures, silver_table_name, if_exists="replace")
    save_list_pydantic(silver_factures_status, silver_table_name + "_status", if_exists="replace")
    return silver_factures, silver_factures_status


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


def process_silver_to_gold(silver_table_name: str) -> None:
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
