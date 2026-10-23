import csv
from decimal import Decimal
from pathlib import Path

import pymupdf
import pytest

from gesec.data.extract_pdf.extract_llm import _parse_extraction
from gesec.data.extract_pdf.io_csv import (
    ENTETE_FIELDNAMES,
    LIGNE_FIELDNAMES,
    TIMINGS_FIELDNAMES,
    write_entete_rows,
    write_ligne_rows,
    write_timings_rows,
)
from gesec.data.extract_pdf.pdf4llm_extract import (
    Pdf4llmWorkerJob,
    extract_invoice_pdf4llm_markdown,
    extract_invoice_pdf4llm_markdown_cached,
    extract_invoice_pdf4llm_markdown_lighton,
    pdf4llm_markdown_cache_path,
    pdf4llm_markdown_worker,
    pdf4llm_tesseract_function,
)
from gesec.data.extract_pdf.paths import resolve_data_paths
from gesec.data.extract_pdf.pdf_utils import (
    parse_id_cpro,
    pdf_within_page_limit,
    skip_too_many_pages_error,
)
from gesec.data.extract_pdf.prompt import response_format_lignes
from gesec.data.extract_pdf.schemas import (
    EnteteCsvRow,
    ExtractedFacture,
    ExtractedLigne,
    ExtractTimings,
    LigneCsvRow,
    TimingsCsvRow,
)


def test_resolve_data_paths_requires_root_or_cli(settings):
    settings.EXTRACT_PDF_DATA_ROOT = ""
    with pytest.raises(ValueError, match="EXTRACT_PDF_DATA_ROOT"):
        resolve_data_paths(factures_dir=None, ocr_dir=None, output_dir=None)


def test_resolve_data_paths_from_env(settings, tmp_path: Path):
    settings.EXTRACT_PDF_DATA_ROOT = str(tmp_path)
    factures, ocr, output = resolve_data_paths(factures_dir=None, ocr_dir=None, output_dir=None)
    assert factures == tmp_path / "factures"
    assert ocr == tmp_path / "facture_ocr"
    assert output == tmp_path


def test_skip_too_many_pages_error():
    assert "51" in skip_too_many_pages_error(page_count=51, max_pages=50)


@pytest.fixture
def minimal_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "123456789_TEST.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Ligne facture test 100 EUR")
    doc.save(path)
    doc.close()
    return path


def test_pdf_within_page_limit(minimal_pdf: Path):
    assert pdf_within_page_limit(minimal_pdf, 50)
    assert not pdf_within_page_limit(minimal_pdf, 0)


def test_parse_id_cpro_from_filename():
    assert parse_id_cpro("456964696_COMPUTACENTER_PJ00XFAC388734568004953990450534.pdf") == "456964696"


def test_parse_id_cpro_invalid():
    with pytest.raises(ValueError, match="Impossible d'extraire"):
        parse_id_cpro("sans_prefixe.pdf")


def test_response_format_lignes_schema():
    fmt = response_format_lignes()
    assert fmt["type"] == "json_schema"
    props = fmt["json_schema"]["schema"]["properties"]
    assert "lignes" in props
    assert "objet_facture" in props


def test_parse_extraction_objet_facture():
    facture = _parse_extraction(
        {
            "objet_facture": "  DGAFP - ASI pilotage  ",
            "lignes": [
                {
                    "line_id": "1",
                    "item_name": "Prestation",
                    "item_description": "",
                    "item_reference": None,
                    "quantity": None,
                    "quantity_unit_code": "",
                    "unit_price": None,
                    "line_amount_excl_tax": 100.0,
                    "line_amount_incl_tax": None,
                    "line_amount_vat": None,
                    "currency": "EUR",
                }
            ],
        }
    )
    assert facture.objet_facture == "DGAFP - ASI pilotage"
    assert len(facture.lignes) == 1


def test_parse_extraction_objet_facture_absent():
    facture = _parse_extraction({"objet_facture": None, "lignes": []})
    assert facture.objet_facture is None


def test_extract_invoice_pdf4llm_markdown(minimal_pdf: Path):
    markdown = extract_invoice_pdf4llm_markdown(minimal_pdf, use_ocr=False)
    assert "--- page 1 ---" in markdown
    assert "Ligne facture" in markdown


def test_pdf4llm_tesseract_function():
    ocr_fn = pdf4llm_tesseract_function()
    assert callable(ocr_fn)


def test_extract_invoice_pdf4llm_markdown_lighton_routing(minimal_pdf: Path, monkeypatch: pytest.MonkeyPatch):
    ocr_calls = 0

    class FakeOcr:
        def ocr_image_data_uri(self, data_uri: str) -> str:
            nonlocal ocr_calls
            ocr_calls += 1
            return "texte ocr lighton"

    def fake_analyze(page, blocks=None):
        return {"needs_ocr": page.number == 0}

    monkeypatch.setattr("gesec.data.extract_pdf.pdf4llm_extract.pdf4llm_utils.analyze_page", fake_analyze)
    markdown = extract_invoice_pdf4llm_markdown_lighton(minimal_pdf, ocr_client=FakeOcr())
    assert ocr_calls == 1
    assert "texte ocr lighton" in markdown
    assert "Ligne facture" in markdown


def test_pdf4llm_markdown_cache(minimal_pdf: Path, tmp_path: Path):
    ocr_dir = tmp_path / "facture_ocr"
    cache = pdf4llm_markdown_cache_path(ocr_dir, "123456789")
    md1, cached1 = extract_invoice_pdf4llm_markdown_cached(minimal_pdf, cache, use_ocr=False)
    assert not cached1
    assert cache.parent.name == "pdf4llm"
    assert cache.is_file()
    md2, cached2 = extract_invoice_pdf4llm_markdown_cached(minimal_pdf, cache, use_ocr=False)
    assert cached2
    assert md2 == md1


def test_pdf4llm_markdown_worker(minimal_pdf: Path, tmp_path: Path):
    cache = pdf4llm_markdown_cache_path(tmp_path, "123456789")
    result = pdf4llm_markdown_worker(
        Pdf4llmWorkerJob(
            pdf_path_str=str(minimal_pdf),
            cache_path_str=str(cache),
            force_refresh=False,
        )
    )
    assert not result.error
    assert "Ligne facture" in result.markdown
    assert result.page_count == 1
    assert cache.is_file()


def test_write_csv_rows(tmp_path: Path):
    entete = EnteteCsvRow.from_extraction(
        run_id="run1",
        id_cpro="123",
        pdf_filename="123_x.pdf",
        facture=ExtractedFacture(objet_facture="Objet test"),
    )
    ligne = LigneCsvRow.from_extraction(
        run_id="run1",
        id_cpro="123",
        pdf_filename="123_x.pdf",
        ligne=ExtractedLigne(
            line_id="1",
            item_name="Article",
            item_description="Desc",
            item_reference=None,
            quantity=Decimal("2"),
            quantity_unit_code="C62",
            unit_price=Decimal("10.5"),
            line_amount_excl_tax=Decimal("21"),
            line_amount_incl_tax=None,
            line_amount_vat=None,
            currency="EUR",
        ),
    )
    timings = TimingsCsvRow.from_timings(
        run_id="run1",
        id_cpro="123",
        pdf_filename="123_x.pdf",
        timings=ExtractTimings(duration_total_s=1.5, page_count=1),
    )
    lignes_path = tmp_path / "lignes.csv"
    entete_path = tmp_path / "entete.csv"
    timings_path = tmp_path / "timings.csv"
    write_entete_rows(entete_path, [entete])
    write_ligne_rows(lignes_path, [ligne])
    write_timings_rows(timings_path, [timings])

    with lignes_path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == LIGNE_FIELDNAMES
        row = next(reader)
        assert row["id_cpro"] == "123"
        assert row["item_name"] == "Article"
        assert row["source"] == "extract_pdf"
        assert "scenario" not in (reader.fieldnames or [])

    with entete_path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ENTETE_FIELDNAMES
        row = next(reader)
        assert row["objet_facture"] == "Objet test"

    with timings_path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == TIMINGS_FIELDNAMES
        row = next(reader)
        assert row["duration_total_s"] == "1.5"
