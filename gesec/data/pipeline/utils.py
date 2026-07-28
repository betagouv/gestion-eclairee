import csv
import io
import logging
from typing import Any, Type, TypeVar

from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)


T = TypeVar("T")


def rget(d: dict[str, Any], key: str) -> Any:
    """Reccursive get for dictionnaries using dotted key."""
    if "." in key:
        prefix, tail = key.split(".", 1)
    else:
        prefix, tail = key, ""
    v = d.get(prefix)
    if tail:
        if isinstance(v, dict):
            return rget(v, tail)
        else:
            return None
    else:
        return v


def xml_value(xml):
    """Extract value from xml object.

    Ex : {"total": "value"} or {"total": {"@currencyID": "EUR", "$": "value"}}
    should return "value"
    """
    if isinstance(xml, dict):
        return xml["$"]
    else:
        return xml


def force_string(value: str | list[str], sep: str = " ") -> str:
    if isinstance(value, str):
        return value
    else:
        return sep.join(x for x in value if x)


def load_csv(
    filepath: str,
    row_model: Type[T],
    delimiter: str,
    encoding: str,
    skip_rows: int | None = None,
    clean_rows_empty_fields: bool = False,
) -> list[T]:
    """Load csv file into list of rows.

    Args:
        filepath: Path to the CSV file to be loaded.
        row_model: Class type used to instantiate each row of the CSV.
        delimiter: Delimiter character used in the CSV file.
        encoding: Encoding of the CSV file.
        skip_rows: Number of rows to skip at the beginning of the file. If None, no rows are skipped.
        clean_rows_empty_fields: If True, removes keys with empty values from each row before processing.

    Returns:
        A list of instances of row_model populated with data from the CSV file.
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Processing {filepath}")

    rows = []
    with default_storage.open(filepath, "rb") as f:
        text_f = io.TextIOWrapper(f, encoding=encoding)
        reader = csv.DictReader(text_f, delimiter=delimiter)
        for idx, row in enumerate(reader):
            # Skip if needed
            if skip_rows and idx < skip_rows:
                continue
            # Clean (remove keys with empty values)
            if clean_rows_empty_fields:
                row = {k: v for k, v in row.items() if v}
            try:
                parsed_row = row_model(
                    **row,
                    source=filepath,
                    source_idx=idx,
                )
                rows.append(parsed_row)
            except Exception as e:
                logger.error(f"Error in {filepath} line {idx}: {e}")
                raise

    return rows
