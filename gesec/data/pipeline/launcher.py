from gesec.data.pipeline import layer_1_bronze as bronze
from gesec.data.pipeline import layer_2_silver as silver
from gesec.data.pipeline import layer_3_gold as gold


def launch_pipeline():
    exports_folder = "cpro/exports"
    oda_filepath = "oda/ODA_2025_Complet.csv"
    unzipped_folder = "cpro/factures_unzipped"

    # Bronze
    bronze.cpro_export_facture_xml.process_files_to_bronze(unzipped_folder)
    bronze.cpro_export_factures.process_csvs_to_bronze(exports_folder)
    bronze.oda_export_row.process_csvs_to_bronze(oda_filepath)

    # Silver
    silver.services.process_bronze_to_silver()
    silver.cpro_export_factures.process_bronze_to_silver()
    silver.oda_export_ej_gm_mapping.process_bronze_to_silver()

    # Gold
    gold.facture.process_silver_to_gold()
    gold.facture_ligne.process_to_gold()
