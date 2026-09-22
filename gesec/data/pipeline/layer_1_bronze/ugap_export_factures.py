import logging
import os
import re

from django.core.files.storage import default_storage

from gesec.data.pipeline.db import save_list_pydantic
from gesec.data.pipeline.utils import load_xlsx

from .schemas import BronzeUgapExportFacture
from .utils import clean_column_name

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "bronze_" + __name__.split(".")[-1]
DEFAULT_DIRECTORY = "ugap/exports"

DINUM_SHEET_PATTERN = re.compile(r"dinum", re.IGNORECASE)


def list_xlsx_files(directory: str = DEFAULT_DIRECTORY) -> list[str]:
    """List the xlsx files of a storage directory, tolerating a missing directory."""
    try:
        _folders, filenames = default_storage.listdir(directory)
    except FileNotFoundError:
        logger.warning(f"Directory {directory} does not exist, skipping UGAP exports")
        return []

    return sorted(os.path.join(directory, filename) for filename in filenames if filename.endswith(".xlsx"))


def process_files_to_bronze(directory: str = DEFAULT_DIRECTORY, table_name: str = DEFAULT_TABLE_NAME) -> None:
    rows = []
    for filepath in list_xlsx_files(directory):
        file_rows = load_xlsx(
            filepath,
            BronzeUgapExportFacture,
            DINUM_SHEET_PATTERN,
            source_key=clean_column_name,
        )
        logger.info(f"Processed {len(file_rows)} rows in {filepath}")
        rows.extend(file_rows)

    if not rows:
        logger.warning("No data to export, skipping database insertion")
        return

    save_list_pydantic(rows, table_name=table_name, if_exists="replace")
    logger.info("Operation completed successfully")
