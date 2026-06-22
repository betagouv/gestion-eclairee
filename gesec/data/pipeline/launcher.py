from gesec.data.pipeline import layer_1_bronze as bronze
from gesec.data.pipeline import layer_2_silver as silver
from gesec.data.pipeline import layer_3_gold as gold


def launch_pipeline():
    exports_folder = "exports"
    bronze.cpro_export_factures.process_csvs_to_silver(exports_folder)
    silver.cpro_export_factures.process_bronze_to_silver()
    gold.factures.process_silver_to_gold()
