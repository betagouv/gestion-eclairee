import csv
import io
import logging
import re
from datetime import date, datetime, time
from typing import Any, Type, TypeVar

from django.conf import settings
from django.core.files.storage import default_storage

import openpyxl
from pydantic import BaseModel

logger = logging.getLogger(__name__)


T = TypeVar("T")
ModelT = TypeVar("ModelT", bound=BaseModel)


def resolve_n_workers(n_workers: int | None = None) -> int:
    """Number of threads used to read files from the storage.

    An explicit value wins. Otherwise S3 defaults to 10 threads (network-bound
    reads) and the filesystem to 1.
    """
    if n_workers is not None:
        return n_workers
    return 10 if settings.STORAGE_BACKEND == "s3" else 1


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


def cell_to_text(value) -> str:
    """Convert an xlsx cell value to text, the way a CSV reader would."""
    if value is None:
        return ""
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


def model_headers(row_model: Type[ModelT]) -> list[str]:
    """Source headers a row model expects, in field order.

    The headers are the string `validation_alias` of each field; fields without
    alias (source tracking) are not source headers.
    """
    return [
        field.validation_alias for field in row_model.model_fields.values() if isinstance(field.validation_alias, str)
    ]


def load_xlsx(
    filepath: str,
    row_model: Type[ModelT],
    sheet_pattern: re.Pattern,
    skip_rows: int = 1,
    source_key=None,
) -> list[ModelT]:
    """Load sheets matching a pattern from an xlsx file into rows.

    Only the sheets whose title matches `sheet_pattern` are read. The first
    `skip_rows` rows of each sheet are skipped, the next one is validated
    against the headers expected by `row_model` (see `model_headers`), and each
    following non-empty row is instantiated as:

        row_model(
            **{header: cell_to_text(value)},
            onglet=<sheet title>,
            source=filepath,
            source_idx=f"{source_key(sheet)}_{row_index}",
        )

    `source_key` optionally normalizes the sheet title used as `source_idx`
    prefix (identity by default).

    Raises:
        ValueError: If no sheet matches `sheet_pattern`, or if a sheet headers
            do not match the expected ones.
    """
    expected_headers = model_headers(row_model)

    with default_storage.open(filepath, "rb") as f:
        workbook = openpyxl.load_workbook(f, data_only=True, read_only=True)

        matching_sheets = [name for name in workbook.sheetnames if sheet_pattern.search(name)]
        if not matching_sheets:
            raise ValueError(f"No sheet matching {sheet_pattern.pattern!r} in {filepath}")

        rows = []
        for sheet_name in matching_sheets:
            sheet_key = source_key(sheet_name) if source_key else sheet_name
            values = workbook[sheet_name].iter_rows(values_only=True)
            for _ in range(skip_rows):
                next(values, None)
            headers = list(next(values, ()))
            if headers != expected_headers:
                missing = [header for header in expected_headers if header not in headers]
                unknown = [header for header in headers if header not in expected_headers]
                raise ValueError(
                    f"Unexpected headers in {filepath} sheet {sheet_name!r}: missing={missing}, unknown={unknown}"
                )
            for idx, row_values in enumerate(values):
                if all(value is None for value in row_values):
                    continue
                rows.append(
                    row_model(
                        **{header: cell_to_text(value) for header, value in zip(headers, row_values)},
                        onglet=sheet_name,
                        source=filepath,
                        source_idx=f"{sheet_key}_{idx}",
                    )
                )

        workbook.close()

    return rows
