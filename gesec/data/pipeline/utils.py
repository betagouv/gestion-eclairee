import csv
import io
import logging
import re
from typing import Any, Type, TypeVar

from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)


T = TypeVar("T")


def read_xml_file(file_path: str) -> str:
    """Read an XML file from default_storage, handling various encodings.

    Reads the entire file in binary mode, detects encoding from the XML declaration,
    and decodes the content accordingly. Falls back to UTF-8 then ISO-8859-1 if no encoding is specified.
    """
    # Pattern to match encoding in XML declaration
    encoding_pattern = re.compile(rb'encoding\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)

    with default_storage.open(file_path, "rb") as f:
        content = f.read()

    # Try to detect encoding from XML declaration (search only in first 200 bytes)
    encoding = None
    match = encoding_pattern.search(content[:200])
    if match:
        encoding = match.group(1).decode("ascii", errors="ignore")
        logger.debug(f"Detected encoding {encoding} from XML declaration in {file_path}")

    # Try to decode with detected encoding
    if encoding:
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError) as e:
            logger.warning(f"Failed to decode {file_path} with encoding {encoding}: {e}")

    # Fall back to trying UTF-8, then ISO-8859-1
    for fallback_encoding in ["utf-8", "iso-8859-1"]:
        try:
            return content.decode(fallback_encoding)
        except UnicodeDecodeError:
            continue

    raise ValueError(f"Failed to decode {file_path} with any encoding")


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
