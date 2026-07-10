
from gesec.data.pipeline.db import save_list_pydantic, load_rows_from_table
from gesec.data.pipeline.layer_2_silver.schemas import SilverCproExportFacturXLigne, SilverCproExportFactureXmlLigne
from gesec.data.pipeline.layer_2_silver.cpro_export_factur_x_ligne import DEFAULT_TABLE_NAME as SILVER_FACTUR_X_LIGNE_DEFAULT_TABLE_NAME
from gesec.data.pipeline.layer_2_silver.cpro_export_facture_xml_ligne import DEFAULT_TABLE_NAME as SILVER_FACTUR_XML_LIGNE_DEFAULT_TABLE_NAME
from gesec.data.pipeline.layer_3_gold.schemas import GoldCproExportFactureLigne

TABLE_NAME = "gesec_facture_ligne"


def load_factur_x_rows(table_name: str) -> list[SilverCproExportFacturXLigne]:
    return load_rows_from_table(table_name, SilverCproExportFacturXLigne)


def load_facture_xml_rows(table_name: str) -> list[SilverCproExportFactureXmlLigne]:
    return load_rows_from_table(table_name, SilverCproExportFactureXmlLigne)


def transform_to_gold(factur_x_rows: list[SilverCproExportFacturXLigne], facture_xml_rows: list[SilverCproExportFactureXmlLigne]) -> list[GoldCproExportFactureLigne]:
    """Prend en priorité les lignes de facture XML, puis celles de factur-x."""

    # Groupe les lignes par id_cpro
    factur_x_by_id_cpro = {}
    for fac in factur_x_rows:
        factur_x_by_id_cpro.setdefault(fac.id_cpro, []).append(fac)
    facture_xml_by_id_cpro = {}
    for fac in facture_xml_rows:
        facture_xml_by_id_cpro.setdefault(fac.id_cpro, []).append(fac)

    # Merge les lignes
    result = []
    processed_ids = set()
    for id_cpro, fac_lignes in facture_xml_by_id_cpro.items():
        for fac_ligne in fac_lignes:
            result.append(GoldCproExportFactureLigne(
                **fac_ligne.model_dump(),
                source="facture-xml",
            ))
        processed_ids.add(id_cpro)
    for id_cpro, fac_lignes in factur_x_by_id_cpro.items():
        if id_cpro in processed_ids:
            continue
        for fac_ligne in fac_lignes:
            result.append(GoldCproExportFactureLigne(
                **fac_ligne.model_dump(),
                source="factur-x",
            ))
        processed_ids.add(id_cpro)

    return result


def process_to_gold(
    silver_factur_x_table_name: str = SILVER_FACTUR_X_LIGNE_DEFAULT_TABLE_NAME,
    silver_facture_xml_table_name: str = SILVER_FACTUR_XML_LIGNE_DEFAULT_TABLE_NAME,
) -> None:
    factur_x_rows = load_factur_x_rows(silver_factur_x_table_name)
    facture_xml_rows = load_facture_xml_rows(silver_facture_xml_table_name)
    gold_lines = transform_to_gold(factur_x_rows=factur_x_rows, facture_xml_rows=facture_xml_rows)
    save_list_pydantic(gold_lines, TABLE_NAME, if_exists="replace")
