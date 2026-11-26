"""Tests for the download list builder reading the augdt from the storage."""

import pandas as pd

from gesec.data.sync import build_download_list_from_storage as module


def put_augdt(s3_client, key: str, rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    body = df.to_csv(sep=";", index=False, encoding="iso-8859-3").encode("iso-8859-3")
    s3_client.Bucket("test-depec").put_object(Key=key, Body=body)


def test_builds_list_sorted_by_date(s3_client, tmp_path):
    put_augdt(
        s3_client,
        "budat/export_augdt_20260814.csv",
        [
            {"EJ": "EJ2", "SEDP": "S2", "DATE": "15/03/2024", "LIBELLE": "Crédits °"},
            {"EJ": "EJ1", "SEDP": "S1", "DATE": "01/02/2023", "LIBELLE": "Crédits °"},
            {"EJ": "EJ1", "SEDP": "S1", "DATE": "10/01/2023", "LIBELLE": "Crédits °"},
            {"EJ": "EJ2", "SEDP": "S2", "DATE": "15/03/2024", "LIBELLE": "Crédits °"},
        ],
    )

    output = str(tmp_path / "liste.csv")
    written = module.build_download_list(output=output)

    assert written == output
    result = pd.read_csv(output, dtype=str)
    assert result.columns.tolist() == ["EJ", "SERVICES"]
    assert result.values.tolist() == [["EJ1", "S1"], ["EJ2", "S2"]]


def test_uses_latest_augdt(s3_client, tmp_path):
    put_augdt(s3_client, "budat/export_augdt_20260101.csv", [{"EJ": "OLD", "SEDP": "S", "DATE": "01/01/2024"}])
    put_augdt(s3_client, "budat/export_augdt_20260814.csv", [{"EJ": "NEW", "SEDP": "S", "DATE": "01/01/2024"}])

    output = str(tmp_path / "liste.csv")
    module.build_download_list(output=output)

    result = pd.read_csv(output, dtype=str)
    assert result["EJ"].tolist() == ["NEW"]


def test_raises_without_augdt(s3_client, tmp_path):
    bucket = s3_client.Bucket("test-depec")
    for obj in bucket.objects.filter(Prefix="budat/"):
        obj.delete()
    try:
        module.build_download_list(output=str(tmp_path / "liste.csv"))
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("FileNotFoundError expected")
