import logging

from gesec.data.pipeline.db import save_list_pydantic
from gesec.data.pipeline.layer_1_bronze.schemas import BronzeODAExportRow
from gesec.data.pipeline.utils import load_csv

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "bronze_" + __name__.split(".")[-1]


def process_csvs_to_bronze(filepath: str, table_name: str = DEFAULT_TABLE_NAME) -> None:
    # Aggregate all CSV files
    rows = load_csv(filepath, BronzeODAExportRow, delimiter=",", encoding="utf-8", clean_rows_empty_fields=True)
    logger.info(f"Processed {len(rows)} rows in {filepath}")

    # Export to database
    save_list_pydantic(rows, table_name=table_name, if_exists="replace")

    logger.info("Operation completed successfully")
