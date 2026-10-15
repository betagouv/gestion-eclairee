"""Tests for the missing reference download list builder."""

import pytest

import pandas as pd

from gesec.data.sync import build_missing_reference_download_list as module


def write_reference(tmp_path, rows: list[tuple[str, str]]) -> str:
    path = tmp_path / "reference.csv"
    pd.DataFrame(rows, columns=["REF_FAC", "MNT_FAC"]).to_csv(path, sep=";", index=False, encoding="iso-8859-3")
    return str(path)


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("286065697", False),
        ("9026673813", False),
        ("FAC-123", False),
        ("111559524112025", False),
        ("#NOM?", True),
        ("#VALEUR!", True),
        ("-117049582", True),
        ("-1,27444142864846", True),
        ("4,7020560922E+22", True),
    ],
)
def test_is_noise_reference(reference, expected):
    assert module.is_noise_reference(reference) is expected


def test_keeps_only_references_absent_from_numeros(tmp_path, monkeypatch):
    reference = write_reference(
        tmp_path,
        [("286065697", "161,2"), ("111559524112025", "70"), ("999999", "10")],
    )
    monkeypatch.setattr(
        module,
        "load_numeros",
        lambda: ["5148618752", "0111559524112025", "FAC-123"],
    )

    output = str(tmp_path / "liste_telechargement_missing.csv")
    written = module.build_missing_reference_download_list(reference_filepath=reference, output=output)

    assert written == output
    result = pd.read_csv(written, dtype=str)
    assert result.columns.tolist() == ["FACTURE_NUM", "FACTURE_MONTANT"]
    assert result["FACTURE_NUM"].tolist() == ["286065697", "999999"]
    assert result["FACTURE_MONTANT"].tolist() == ["161,2", "10"]


def test_keeps_unique_montant_and_blanks_ambiguous(tmp_path, monkeypatch):
    reference = write_reference(
        tmp_path,
        [("A", "10,5"), ("A", "10,5"), ("B", "20"), ("B", "30")],
    )
    monkeypatch.setattr(module, "load_numeros", lambda: [])

    output = str(tmp_path / "liste_telechargement_missing.csv")
    module.build_missing_reference_download_list(reference_filepath=reference, output=output)

    result = pd.read_csv(output, dtype=str, keep_default_na=False)
    montants = dict(zip(result["FACTURE_NUM"], result["FACTURE_MONTANT"], strict=True))
    assert montants == {"A": "10,5", "B": ""}


def test_filters_noise_from_output(tmp_path, monkeypatch):
    reference = write_reference(
        tmp_path,
        [("286065697", "161,2"), ("#NOM?", "10"), ("-117049582", "10"), ("4,7020560922E+22", "10")],
    )
    monkeypatch.setattr(module, "load_numeros", lambda: [])

    output = str(tmp_path / "liste_telechargement_missing.csv")
    written = module.build_missing_reference_download_list(reference_filepath=reference, output=output)

    assert written == output
    result = pd.read_csv(written, dtype=str)
    assert result["FACTURE_NUM"].tolist() == ["286065697"]


def test_deduplicates_and_sorts(tmp_path, monkeypatch):
    reference = write_reference(tmp_path, [("B", "1"), ("A", "2"), ("B", "1"), ("", "3")])
    monkeypatch.setattr(module, "load_numeros", lambda: [])

    output = str(tmp_path / "liste_telechargement_missing.csv")
    written = module.build_missing_reference_download_list(reference_filepath=reference, output=output)

    assert written == output
    result = pd.read_csv(written, dtype=str)
    assert result["FACTURE_NUM"].tolist() == ["A", "B"]


def test_returns_none_when_nothing_missing(tmp_path, monkeypatch):
    reference = write_reference(tmp_path, [("123", "5")])
    monkeypatch.setattr(module, "load_numeros", lambda: ["FAC-123"])

    written = module.build_missing_reference_download_list(
        reference_filepath=reference,
        output=str(tmp_path / "liste_telechargement_missing.csv"),
    )

    assert written is None
