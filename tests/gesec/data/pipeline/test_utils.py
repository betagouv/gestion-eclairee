"""Tests for pipeline utils module."""

import re
from datetime import datetime
from unittest.mock import patch

from django.core.files.storage import FileSystemStorage
from django.test import override_settings

import pytest
from pydantic import BaseModel, ConfigDict, Field

from gesec.data.pipeline.utils import load_xlsx, model_headers, read_xml_file, resolve_n_workers
from tests.gesec.data.pipeline.ugap_helpers import build_xlsx


class XlsxRow(BaseModel):
    model_config = ConfigDict(validate_by_alias=True, validate_by_name=True)

    source: str
    source_idx: str
    onglet: str
    a: str = Field(default="", validation_alias="A")
    b: str = Field(default="", validation_alias="B")


def put_xlsx(s3_client, key: str, sheets: dict[str, list[list]], banner: bool = True) -> None:
    s3_client.Bucket("test-depec").put_object(Key=key, Body=build_xlsx(sheets, banner=banner))


def test_load_xlsx_selects_matching_sheets(s3_client):
    put_xlsx(
        s3_client,
        "ugap/test.xlsx",
        {
            "11 2025 - Dinum": [["A", "B"], [1, "a"], [2, "b"]],
            "11 2025 - DAE": [["A", "B"], [3, "c"]],
        },
    )

    rows = load_xlsx("ugap/test.xlsx", XlsxRow, re.compile("dinum", re.IGNORECASE))

    assert len(rows) == 2
    assert {row.onglet for row in rows} == {"11 2025 - Dinum"}
    assert [(row.a, row.b) for row in rows] == [("1", "a"), ("2", "b")]
    assert [row.source_idx for row in rows] == ["11 2025 - Dinum_0", "11 2025 - Dinum_1"]
    assert all(row.source == "ugap/test.xlsx" for row in rows)


def test_load_xlsx_converts_cells_to_text(s3_client):
    put_xlsx(
        s3_client,
        "ugap/text.xlsx",
        {"Dinum": [["A", "B"], [1.0, datetime(2025, 4, 10)], [0.27, "-"], [None, "x"]]},
    )

    rows = load_xlsx("ugap/text.xlsx", XlsxRow, re.compile("dinum", re.IGNORECASE))

    assert rows[0].a == "1"
    assert rows[0].b == "2025-04-10T00:00:00"
    assert rows[1].a == "0.27"
    assert rows[1].b == "-"
    assert rows[2].a == ""
    assert rows[2].b == "x"


def test_load_xlsx_reads_after_storage_handle_is_closed(tmp_path):
    storage = FileSystemStorage(location=str(tmp_path))
    (tmp_path / "test.xlsx").write_bytes(build_xlsx({"Dinum": [["A", "B"], [1, "a"]]}))

    with patch("gesec.data.pipeline.utils.default_storage", storage):
        rows = load_xlsx("test.xlsx", XlsxRow, re.compile("dinum", re.IGNORECASE))

    assert [(row.a, row.b) for row in rows] == [("1", "a")]


def test_load_xlsx_applies_source_key(s3_client):
    put_xlsx(s3_client, "ugap/test.xlsx", {"11 2025 - Dinum": [["A", "B"], [1, None]]})

    rows = load_xlsx(
        "ugap/test.xlsx",
        XlsxRow,
        re.compile("dinum", re.IGNORECASE),
        source_key=lambda sheet: "cle",
    )

    assert [row.source_idx for row in rows] == ["cle_0"]


def test_load_xlsx_source_idx_is_unique_across_sheets(s3_client):
    put_xlsx(
        s3_client,
        "ugap/test.xlsx",
        {
            "Dinum 1": [["A", "B"], [1, None]],
            "Dinum 2": [["A", "B"], [2, None]],
        },
    )

    rows = load_xlsx("ugap/test.xlsx", XlsxRow, re.compile("dinum", re.IGNORECASE))

    assert [row.source_idx for row in rows] == ["Dinum 1_0", "Dinum 2_0"]


def test_load_xlsx_raises_without_matching_sheet(s3_client):
    put_xlsx(s3_client, "ugap/test.xlsx", {"11 2025 - DAE": [["A"], [1]]})

    with pytest.raises(ValueError, match="No sheet matching"):
        load_xlsx("ugap/test.xlsx", XlsxRow, re.compile("dinum", re.IGNORECASE))


def test_load_xlsx_raises_on_unexpected_headers(s3_client):
    put_xlsx(s3_client, "ugap/test.xlsx", {"Dinum": [["A", "C"], [1, 2]]})

    with pytest.raises(ValueError, match="Unexpected headers"):
        load_xlsx("ugap/test.xlsx", XlsxRow, re.compile("dinum", re.IGNORECASE))


def test_model_headers_uses_validation_aliases():
    assert model_headers(XlsxRow) == ["A", "B"]


@pytest.mark.parametrize(
    "xml_content, encoding, key",
    [
        ('<?xml version="1.0" encoding="UTF-8"?><root><test>café</test></root>', "utf-8", "test_decl_utf8.xml"),
        (
            '<?xml version="1.0" encoding="ISO-8859-1"?><root><test>café</test></root>',
            "iso-8859-1",
            "test_decl_iso.xml",
        ),
        (
            "<?xml version='1.0' encoding='ISO-8859-1'?><root><test>café</test></root>",
            "iso-8859-1",
            "test_decl_single_quotes.xml",
        ),
        (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><root><test>café</test></root>',
            "utf-8",
            "test_decl_complex.xml",
        ),
    ],
)
def test_read_xml_file_with_encoding_declaration(s3_client, xml_content, encoding, key):
    """Test reading XML with various encoding declarations."""
    bucket = s3_client.Bucket("test-depec")
    bucket.put_object(Key=key, Body=xml_content.encode(encoding))

    result = read_xml_file(key)
    assert result == xml_content


@pytest.mark.parametrize(
    "xml_content, encoding, key",
    [
        ('<?xml version="1.0"?><root><test>café</test></root>', "utf-8", "test_no_decl_utf8.xml"),
        ("<root><test>café</test></root>", "iso-8859-1", "test_no_decl_iso.xml"),
    ],
)
def test_read_xml_file_without_encoding_declaration(s3_client, xml_content, encoding, key):
    """Test reading XML without encoding declaration, relying on fallback."""
    bucket = s3_client.Bucket("test-depec")
    bucket.put_object(Key=key, Body=xml_content.encode(encoding))

    result = read_xml_file(key)
    assert result == xml_content


def test_read_xml_file_large_file(s3_client):
    """Test reading a larger XML file where encoding is beyond first 1024 bytes."""
    prefix = "<!-- comment --> " * 500  # About 1000 bytes of comments
    xml_content = f'{prefix}<?xml version="1.0" encoding="UTF-8"?><root><test>data</test></root>'

    bucket = s3_client.Bucket("test-depec")
    bucket.put_object(Key="test_large.xml", Body=xml_content.encode("utf-8"))

    result = read_xml_file("test_large.xml")
    assert result == xml_content


def test_resolve_n_workers_explicit_value_wins():
    assert resolve_n_workers(3) == 3


def test_resolve_n_workers_defaults_to_ten_on_s3():
    with override_settings(STORAGE_BACKEND="s3"):
        assert resolve_n_workers() == 10


def test_resolve_n_workers_defaults_to_one_on_fs():
    with override_settings(STORAGE_BACKEND="fs"):
        assert resolve_n_workers() == 1
