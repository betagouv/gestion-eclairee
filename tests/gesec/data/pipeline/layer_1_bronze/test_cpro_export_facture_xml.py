"""Tests for the facture XML bronze layer."""

from pathlib import Path

import pytest

from gesec.data.pipeline.layer_1_bronze.cpro_export_facture_xml import filter_files, load_file
from gesec.data.pipeline.utils import LOAD_PHASES, LoadTimings
from gesec.storage import FileSystemStorage

MINIMAL_UBL_INVOICE = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:UBLVersionID>2.4</cbc:UBLVersionID>
  <cbc:ID>F001</cbc:ID>
  <cbc:IssueDate>2024-01-01</cbc:IssueDate>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>Fournisseur</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount>
    <cbc:PayableAmount currencyID="EUR">120.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Prestation</cbc:Name></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">100.00</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
</Invoice>
"""


@pytest.fixture
def prefix(request):
    return f"test-facture-xml/{request.node.name}"


def put_objects(s3_client, keys: list[str], body: bytes = b"x") -> None:
    bucket = s3_client.Bucket("test-depec")
    for key in keys:
        bucket.put_object(Key=key, Body=body)


def write_files(root: Path, paths: list[str]) -> None:
    for path in paths:
        filepath = root / path
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text("")


def test_filter_files_selects_xml_and_keeps_every_pivot_file(prefix, s3_client):
    put_objects(
        s3_client,
        [
            f"{prefix}/facture_111111111/44444444444_5555555555/PJ00XFAC444444444445555555555.pdf",
            f"{prefix}/facture_111111111/pivot/FAC444444444445555555555.xml",
            f"{prefix}/facture_111111111/pivot/PJ00XFAC444444444445555555555.pdf",
            f"{prefix}/facture_111111111/pivot/PJ00XFAC444444444445555555555.pdf.factur-x.xml",
            f"{prefix}/facture_111111111/pivot/annexe.xml",
            f"{prefix}/facture_111111111/PivotS.xml",
        ],
    )

    assert sorted(filter_files(prefix)) == sorted(
        [
            ("111111111", f"{prefix}/facture_111111111/pivot/FAC444444444445555555555.xml"),
            ("111111111", f"{prefix}/facture_111111111/pivot/annexe.xml"),
        ]
    )


def test_filter_files_selects_xml_on_filesystem_storage(tmp_path, monkeypatch):
    write_files(
        tmp_path,
        [
            "cpro/factures_unzipped/facture_111111111/44444444444_5555555555/PJ00XFAC444444444445555555555.pdf",
            "cpro/factures_unzipped/facture_111111111/pivot/FAC444444444445555555555.xml",
            "cpro/factures_unzipped/facture_111111111/pivot/PJ00XFAC444444444445555555555.pdf",
            "cpro/factures_unzipped/facture_111111111/pivot/PJ00XFAC444444444445555555555.pdf.factur-x.xml",
            "cpro/factures_unzipped/facture_111111111/PivotS.xml",
        ],
    )
    storage = FileSystemStorage(location=str(tmp_path))
    monkeypatch.setattr("gesec.storage.default_storage", storage)

    assert filter_files("cpro/factures_unzipped") == [
        (
            "111111111",
            "cpro/factures_unzipped/facture_111111111/pivot/FAC444444444445555555555.xml",
        )
    ]


def test_filter_files_filters_ids_cpro(prefix, s3_client):
    put_objects(
        s3_client,
        [
            f"{prefix}/facture_1/pivot/a.xml",
            f"{prefix}/facture_2/pivot/b.xml",
        ],
    )

    assert filter_files(prefix, ["2"]) == [("2", f"{prefix}/facture_2/pivot/b.xml")]


def test_filter_files_logs_and_skips_unexpected_facture_folder(prefix, s3_client, caplog):
    put_objects(s3_client, [f"{prefix}/not_a_facture/pivot/a.xml"])

    with caplog.at_level("WARNING"):
        assert filter_files(prefix) == []

    assert "Dossier de facture au nom inattendu" in caplog.text


def test_filter_files_handles_missing_or_empty_pivot(prefix, s3_client):
    put_objects(s3_client, [f"{prefix}/facture_1/metadata.json", f"{prefix}/facture_2/pivot/"])

    assert filter_files(prefix) == []


def test_load_file_records_timings(prefix, s3_client):
    key = f"{prefix}/facture_123/pivot/facture.xml"
    content = MINIMAL_UBL_INVOICE.encode()
    put_objects(s3_client, [key], body=content)
    timings = LoadTimings()

    row = load_file("123", key, timings=timings)

    assert row.id_cpro == "123"
    assert row.xml_schema == "UBL-Invoice-2.4"
    assert timings.files == 1
    assert timings.total_bytes == len(content)
    for phase in LOAD_PHASES:
        assert len(timings.durations[phase]) == 1
