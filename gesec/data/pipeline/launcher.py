from gesec.data.pipeline import layer_1_bronze as bronze
from gesec.data.pipeline import layer_2_silver as silver
from gesec.data.pipeline import layer_3_gold as gold


def launch_pipeline():
    exports_folder = "gesec/exports"
    oda_filepath = "gesec/oda/ODA_2025_Complet.csv"

    # Bronze
    bronze.cpro_export_factures.process_csvs_to_bronze(exports_folder)
    bronze.oda_export_row.process_csvs_to_bronze(oda_filepath)

    # Silver
    silver.services.process_bronze_to_silver()
    silver.cpro_export_factures.process_bronze_to_silver()
    silver.oda_export_ej_gm_mapping.process_bronze_to_silver()

    # Gold
    gold.factures.process_silver_to_gold()
