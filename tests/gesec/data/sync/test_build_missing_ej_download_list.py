"""Tests for the missing download list builder."""

import pandas as pd

from gesec.data.sync import build_missing_ej_download_list as module


def write_reference(tmp_path, rows: list[dict]) -> str:
    path = tmp_path / "reference.csv"
    pd.DataFrame(rows).to_csv(path, sep=";", index=False, encoding="iso-8859-3")
    return str(path)


def test_builds_single_file_with_missing_factures(tmp_path, monkeypatch):
    reference = write_reference(
        tmp_path,
        [
            {"EJ": "EJ1", "SEDP": "S1"},
            {"EJ": "EJ1", "SEDP": "S2"},
            {"EJ": "EJ2", "SEDP": "S3"},
            {"EJ": "EJ2", "SEDP": "S4"},
        ],
    )
    monkeypatch.setattr(
        module,
        "load_factures",
        lambda: pd.DataFrame(
            [
                {"id_cpro": "111111111", "EJ": "EJ1", "SERVICES": "S1"},
                {"id_cpro": "222222222", "EJ": "EJ1", "SERVICES": "S2"},
                {"id_cpro": "333333333", "EJ": "EJ2", "SERVICES": "S3"},
                {"id_cpro": "444444444", "EJ": "EJ2", "SERVICES": "S4"},
            ]
        ),
    )
    monkeypatch.setattr(module, "load_downloaded_ids", lambda prefix=module.FACTURES_PREFIX: {"111111111"})

    output = str(tmp_path / "liste_telechargement_missing.csv")
    written = module.build_missing_ej_download_list(
        reference_filepath=reference,
        output=output,
    )

    assert written == output
    result = pd.read_csv(written, dtype=str)
    assert result.columns.tolist() == ["EJ", "SERVICES"]
    assert sorted(result["EJ"] + "/" + result["SERVICES"]) == ["EJ1/S2", "EJ2/S3", "EJ2/S4"]


def test_returns_none_when_nothing_missing(tmp_path, monkeypatch):
    reference = write_reference(tmp_path, [{"EJ": "EJ1", "SEDP": "S1"}])
    monkeypatch.setattr(
        module,
        "load_factures",
        lambda: pd.DataFrame([{"id_cpro": "111111111", "EJ": "EJ1", "SERVICES": "S1"}]),
    )
    monkeypatch.setattr(module, "load_downloaded_ids", lambda prefix=module.FACTURES_PREFIX: {"111111111"})

    written = module.build_missing_ej_download_list(
        reference_filepath=reference,
        output=str(tmp_path / "liste_telechargement_missing.csv"),
    )

    assert written is None
