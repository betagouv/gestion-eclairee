from gesec.data.pipeline import layer_1_bronze as bronze
from gesec.data.pipeline import layer_2_silver as silver
from gesec.data.pipeline import layer_3_gold as gold


def launch_pipeline(ministere: str | None = None):
    exports_folder = "cpro/exports"
    cpro_annuaire_filepath = "cpro/annuaire/annuaire_services_20260720.csv"
    oda_filepath = "oda/ODA_2025_Complet.csv"
    augdt_filepath = "budat/export_augdt_20260814.csv"
    unzipped_folder = "cpro/factures_unzipped"

    # Bronze
    bronze.cpro_annuaire.process_csv_to_bronze(cpro_annuaire_filepath)
    bronze.oda_export_row.process_csvs_to_bronze(oda_filepath)
    bronze.budat_export_augdt.process_to_bronze(augdt_filepath)
    bronze.cpro_export_facture_xml.process_files_to_bronze(unzipped_folder, ministere=ministere)
    bronze.cpro_export_factur_x.process_files_to_bronze(unzipped_folder, ministere=ministere)
    bronze.cpro_export_factures.process_csvs_to_bronze(exports_folder)

    ## Silver
    silver.services.process_bronze_to_silver()
    silver.cpro_export_factures.process_bronze_to_silver()
    silver.cpro_export_factur_x_ligne.process_to_silver()
    silver.cpro_export_facture_xml_ligne.process_to_silver()
    silver.oda_export_ej_gm_mapping.process_bronze_to_silver()

    ## Gold
    gold.facture.process_silver_to_gold()
    gold.facture_ligne.process_to_gold()
