import logging

from sqlalchemy import text

from ..db import create_engine, save_list_dict
from ..layer_1_bronze.oda_export_row import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]


def process_bronze_to_silver(
        bronze_table_name: str = BRONZE_DEFAULT_TABLE_NAME,
        silver_table_name: str = DEFAULT_TABLE_NAME,
):
    engine = create_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text(f"""SELECT DISTINCT 
                        domaine,
                        domaine_libelle,
                        segment,
                        libelle_du_segment,
                        groupe_de_marchandises_p_cle,
                        gdm_libelle, 
                        numero_ej_reference_facture
                    FROM {bronze_table_name}
                    WHERE numero_ej_reference_facture != '#'
                 """),
        )
        rows = result.fetchall()

    save_list_dict([
        row._asdict()
        for row in rows
    ], silver_table_name, if_exists="replace")
