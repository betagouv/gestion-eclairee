"""Tests for the missing reference rows extractor."""

import pandas as pd

from gesec.data.sync import build_missing_reference_rows as module


def write_export(tmp_path, rows: list[dict]) -> str:
    path = tmp_path / "export.csv"
    pd.DataFrame(rows).to_csv(path, sep=";", index=False, encoding="iso-8859-3")
    return str(path)


def test_keeps_only_rows_absent_from_numeros_preserving_columns(tmp_path, monkeypatch):
    export = write_export(
        tmp_path,
        [
            {"ANNEE": "2022", "REF_FAC": "286065697", "MNT_FAC": "161,2", "FOURN": "ORANGE"},
            {"ANNEE": "2022", "REF_FAC": "111559524112025", "MNT_FAC": "70", "FOURN": "OVH"},
            {"ANNEE": "2022", "REF_FAC": "999999", "MNT_FAC": "10", "FOURN": "DUPONT"},
        ],
    )
    monkeypatch.setattr(
        module,
        "load_numeros",
        lambda: ["5148618752", "0111559524112025", "FAC-123"],
    )

    output = str(tmp_path / "export_missing.csv")
    written = module.build_missing_reference_rows(reference_filepath=export, output=output)

    assert written == output
    result = pd.read_csv(written, dtype=str, sep=";", keep_default_na=False)
    assert result.columns.tolist() == ["ANNEE", "REF_FAC", "MNT_FAC", "FOURN"]
    assert result["REF_FAC"].tolist() == ["286065697", "999999"]
    assert result["FOURN"].tolist() == ["ORANGE", "DUPONT"]


def test_filters_noise_and_empty_rows(tmp_path, monkeypatch):
    export = write_export(
        tmp_path,
        [
            {"REF_FAC": "286065697", "MNT_FAC": "161,2"},
            {"REF_FAC": "#NOM?", "MNT_FAC": "10"},
            {"REF_FAC": "-117049582", "MNT_FAC": "10"},
            {"REF_FAC": "", "MNT_FAC": "10"},
        ],
    )
    monkeypatch.setattr(module, "load_numeros", lambda: [])

    output = str(tmp_path / "export_missing.csv")
    written = module.build_missing_reference_rows(reference_filepath=export, output=output)

    assert written == output
    result = pd.read_csv(written, dtype=str, sep=";", keep_default_na=False)
    assert result["REF_FAC"].tolist() == ["286065697", "#NOM?", "-117049582", ""]


def test_returns_none_when_nothing_missing(tmp_path, monkeypatch):
    export = write_export(tmp_path, [{"REF_FAC": "123", "MNT_FAC": "5"}])
    monkeypatch.setattr(module, "load_numeros", lambda: ["FAC-123"])

    written = module.build_missing_reference_rows(
        reference_filepath=export,
        output=str(tmp_path / "export_missing.csv"),
    )

    assert written is None
