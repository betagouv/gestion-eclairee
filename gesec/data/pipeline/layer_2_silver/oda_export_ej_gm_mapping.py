import logging

from ..db import DEFAULT_BATCH_SIZE, TableWriter, iter_rows_from_table
from ..layer_1_bronze.oda_export_row import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME
from .schemas import SilverOdaExportEjGmMapping

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]

DISTINCT_COLUMNS = (
    "domaine",
    "domaine_libelle",
    "segment",
    "libelle_du_segment",
    "groupe_de_marchandises_p_cle",
    "gdm_libelle",
    "numero_ej_reference_facture",
)


def build_query(bronze_table_name: str) -> str:
    columns = ", ".join(DISTINCT_COLUMNS)
    return f"""
        SELECT DISTINCT {columns}
        FROM {bronze_table_name}
        WHERE numero_ej_reference_facture != '#'
    """


def process_bronze_to_silver(
    bronze_table_name: str = BRONZE_DEFAULT_TABLE_NAME,
    silver_table_name: str = DEFAULT_TABLE_NAME,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
    rows = iter_rows_from_table(
        bronze_table_name,
        SilverOdaExportEjGmMapping,
        batch_size=batch_size,
        query=build_query(bronze_table_name),
    )
    with TableWriter(silver_table_name, SilverOdaExportEjGmMapping, batch_size=batch_size) as writer:
        writer.add_all(rows)
