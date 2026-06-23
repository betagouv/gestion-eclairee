from pydantic import ValidationError
from sqlalchemy import text

from gesec.data.pipeline.db import create_engine, save_list_pydantic

from ..layer_1_bronze.cpro_export_factures import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME
from .schemas import (
    BronzeCproExportFacture,
    SilverCproExportFacture,
    SilverCproExportFactureProcessingStatus,
)

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]


def load_bronze_factures_cpro_export(table_name: str) -> list[BronzeCproExportFacture]:
    """Récupère toutes les lignes d'une table et les convertit en BronzeCproExportFacture."""
    engine = create_engine()
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT * FROM {table_name}"))
        rows = result.fetchall()
        return [BronzeCproExportFacture(**dict(row._asdict())) for row in rows]


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
    bronze_table_name: str = BRONZE_DEFAULT_TABLE_NAME,
    silver_table_name: str = DEFAULT_TABLE_NAME,
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
