import logging

from gesec.data.pipeline.db import TableWriter
from gesec.data.pipeline.layer_1_bronze.schemas import BronzeCproAnnuaireService
from gesec.data.pipeline.utils import load_csv

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "bronze_" + __name__.split(".")[-1]


def process_csv_to_bronze(filepath: str, table_name: str = DEFAULT_TABLE_NAME) -> None:
    # Aggregate all CSV files
    rows = load_csv(filepath, BronzeCproAnnuaireService, delimiter=";", encoding="utf-8-sig", skip_rows=1)
    logger.info(f"Processed {len(rows)} rows in {filepath}")

    # Export to database
    with TableWriter(table_name, BronzeCproAnnuaireService) as writer:
        writer.add_all(rows)

    logger.info("Operation completed successfully")
