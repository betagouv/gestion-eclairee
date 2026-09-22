"""Tests for the factur-x bronze layer."""

from pathlib import Path

import pytest

from gesec.data.pipeline.layer_1_bronze.cpro_export_factur_x import filter_files
from gesec.storage import FileSystemStorage


@pytest.fixture
def prefix(request):
    return f"test-factur-x/{request.node.name}"


def put_objects(s3_client, keys: list[str], body: bytes = b"x") -> None:
    bucket = s3_client.Bucket("test-depec")
    for key in keys:
        bucket.put_object(Key=key, Body=body)


def write_files(root: Path, paths: list[str]) -> None:
    for path in paths:
        filepath = root / path
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text("")


def test_filter_files_selects_factur_x_and_keeps_every_pivot_file(prefix, s3_client):
    put_objects(
        s3_client,
        [
            f"{prefix}/facture_111111111/44444444444_5555555555/PJ00XFAC444444444445555555555.pdf",
            f"{prefix}/facture_111111111/pivot/FAC444444444445555555555.xml",
            f"{prefix}/facture_111111111/pivot/PJ00XFAC444444444445555555555.pdf",
            f"{prefix}/facture_111111111/pivot/PJ00XFAC444444444445555555555.pdf.factur-x.xml",
            f"{prefix}/facture_111111111/pivot/annexe.factur-x.xml",
            f"{prefix}/facture_111111111/PivotS.xml",
        ],
    )

    assert sorted(filter_files(prefix)) == sorted(
        [
            ("111111111", f"{prefix}/facture_111111111/pivot/PJ00XFAC444444444445555555555.pdf.factur-x.xml"),
            ("111111111", f"{prefix}/facture_111111111/pivot/annexe.factur-x.xml"),
        ]
    )


def test_filter_files_selects_factur_x_on_filesystem_storage(tmp_path, monkeypatch):
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
    monkeypatch.setattr("gesec.data.pipeline.layer_1_bronze.cpro_export_factur_x.default_storage", storage)

    assert filter_files("cpro/factures_unzipped") == [
        (
            "111111111",
            "cpro/factures_unzipped/facture_111111111/pivot/PJ00XFAC444444444445555555555.pdf.factur-x.xml",
        )
    ]


def test_filter_files_filters_ids_cpro(prefix, s3_client):
    put_objects(
        s3_client,
        [
            f"{prefix}/facture_1/pivot/a.factur-x.xml",
            f"{prefix}/facture_2/pivot/b.factur-x.xml",
        ],
    )

    assert filter_files(prefix, ["2"]) == [("2", f"{prefix}/facture_2/pivot/b.factur-x.xml")]


def test_filter_files_logs_and_skips_unexpected_facture_folder(prefix, s3_client, caplog):
    put_objects(s3_client, [f"{prefix}/not_a_facture/pivot/a.factur-x.xml"])

    with caplog.at_level("WARNING"):
        assert filter_files(prefix) == []

    assert "Dossier de facture au nom inattendu" in caplog.text


def test_filter_files_handles_missing_or_empty_pivot(prefix, s3_client):
    put_objects(s3_client, [f"{prefix}/facture_1/metadata.json", f"{prefix}/facture_2/pivot/"])

    assert filter_files(prefix) == []
