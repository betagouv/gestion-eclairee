import csv
import io
import logging

from django.core.files.storage import default_storage

from gesec.data.pipeline.db import save_list_pydantic
from gesec.data.pipeline.layer_1_bronze.schemas import BronzeCproAnnuaireService

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "bronze_" + __name__.split(".")[-1]


def load_csv(filepath: str) -> list[BronzeCproAnnuaireService]:
    """Traite un fichier CSV et retourne ses lignes."""
    local_logger = logging.getLogger(__name__)
    local_logger.debug(f"Processing {filepath}")

    rows = []
    with default_storage.open(filepath, "rb") as f:
        text_f = io.TextIOWrapper(f, encoding='utf-8-sig')
        reader = csv.DictReader(text_f, delimiter=";")
        for idx, row in enumerate(reader):
            # Skip first line
            if idx == 0:
                continue
            try:
                parsed_row = BronzeCproAnnuaireService.model_validate(
                    {
                        **row,
                        "source": filepath,
                        "source_idx": idx,
                    }
                )
                rows.append(parsed_row)
            except Exception as e:
                local_logger.error(f"Error in {filepath} line {idx}: {e}")
                raise

    return rows


def process_csv_to_bronze(filepath: str, table_name: str = DEFAULT_TABLE_NAME) -> None:
    # Aggregate all CSV files
    rows = load_csv(filepath)
    logger.info(f"Processed {len(rows)} rows in {filepath}")

    # Export to database
    save_list_pydantic(rows, table_name=table_name, if_exists="replace")

    logger.info("Operation completed successfully")
