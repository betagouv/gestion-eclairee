from decimal import Decimal
from pathlib import Path

import pymupdf
import pytest

from gesec.data.extract_pdf.extract_llm import parse_extraction
from gesec.data.extract_pdf.paths import markdown_storage_path
from gesec.data.extract_pdf.pdf4llm_extract import (
    extract_invoice_pdf4llm_markdown,
    extract_invoice_pdf4llm_markdown_lighton,
    extract_pdf_markdown,
)
from gesec.data.extract_pdf.pdf_utils import page_count, pdf_within_page_limit
from gesec.data.extract_pdf.prompt import response_format_lignes
from gesec.data.extract_pdf.run import run_extract, select_targets
from gesec.data.extract_pdf.schemas import BronzeExtractPdf, ExtractedFacture, ExtractedLigne
from gesec.data.extract_pdf.selection import PdfCandidate, PdfSelection, scan_inventory
from gesec.data.pipeline.layer_2_silver.extract_pdf_ligne import transform_to_silver


@pytest.fixture
def minimal_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "123456789_TEST.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Ligne facture test 100 EUR")
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def two_page_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "deux_pages.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.new_page()
    doc.save(path)
    doc.close()
    return path


class FakeOcr:
    def __init__(self, text: str = "texte ocr lighton") -> None:
        self.text = text
        self.calls = 0

    def ocr_image_data_uri(self, data_uri: str) -> str:
        self.calls += 1
        return self.text


def test_response_format_lignes_schema():
    fmt = response_format_lignes()
    props = fmt["json_schema"]["schema"]["properties"]
    assert "lignes" in props
    assert "objet_facture" in props


def test_parse_extraction_objet_facture():
    facture = parse_extraction(
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
    facture = parse_extraction({"objet_facture": None, "lignes": []})
    assert facture.objet_facture is None


def test_pdf_page_count(minimal_pdf: Path, two_page_pdf: Path):
    assert page_count(minimal_pdf) == 1
    assert page_count(two_page_pdf) == 2
    assert pdf_within_page_limit(minimal_pdf, 50)
    assert not pdf_within_page_limit(minimal_pdf, 0)


def test_extract_invoice_pdf4llm_markdown(minimal_pdf: Path):
    markdown = extract_invoice_pdf4llm_markdown(minimal_pdf, use_ocr=False)
    assert "--- page 1 ---" in markdown
    assert "Ligne facture" in markdown


def test_extract_invoice_pdf4llm_markdown_lighton_routing(minimal_pdf: Path, monkeypatch: pytest.MonkeyPatch):
    fake_ocr = FakeOcr()

    def fake_analyze(page, blocks=None):
        return {"needs_ocr": page.number == 0}

    monkeypatch.setattr("gesec.data.extract_pdf.pdf4llm_extract.pdf4llm_utils.analyze_page", fake_analyze)
    markdown = extract_invoice_pdf4llm_markdown_lighton(minimal_pdf, ocr_client=fake_ocr)
    assert fake_ocr.calls == 1
    assert "texte ocr lighton" in markdown
    assert "Ligne facture" not in markdown


def test_extract_pdf_markdown_caches_in_s3(s3_client, minimal_pdf: Path):
    id_cpro = "123456789"
    pdf_path = "test-extract-pdf/cache/facture.pdf"
    s3_client.Bucket("test-depec").put_object(Key=pdf_path, Body=minimal_pdf.read_bytes())
    ocr = FakeOcr()

    first = extract_pdf_markdown(
        id_cpro=id_cpro,
        pdf_path=pdf_path,
        pdf_filename="facture.pdf",
        ocr_client=ocr,
        force_refresh=False,
        max_pages=50,
    )
    second = extract_pdf_markdown(
        id_cpro=id_cpro,
        pdf_path=pdf_path,
        pdf_filename="facture.pdf",
        ocr_client=ocr,
        force_refresh=False,
        max_pages=50,
    )

    assert first.status is None
    assert not first.markdown_cached
    assert second.markdown_cached
    assert second.markdown == first.markdown
    assert second.markdown_path == markdown_storage_path(id_cpro, "facture.pdf")
    assert second.page_count == 1
    assert second.pdf_sha256


def test_extract_pdf_markdown_too_large(s3_client, two_page_pdf: Path):
    pdf_path = "test-extract-pdf/too-large/facture.pdf"
    s3_client.Bucket("test-depec").put_object(Key=pdf_path, Body=two_page_pdf.read_bytes())

    result = extract_pdf_markdown(
        id_cpro="2",
        pdf_path=pdf_path,
        pdf_filename="facture.pdf",
        ocr_client=FakeOcr(),
        force_refresh=False,
        max_pages=1,
    )

    assert result.status == "too_large"
    assert result.page_count == 2
    assert result.markdown == ""


def test_extract_pdf_markdown_missing_s3_object():
    result = extract_pdf_markdown(
        id_cpro="3",
        pdf_path="test-extract-pdf/missing/facture.pdf",
        pdf_filename="facture.pdf",
        ocr_client=FakeOcr(),
        force_refresh=False,
        max_pages=50,
    )
    assert result.status == "failed"
    assert result.error_type == "s3"


def _pivot_xml(id_cpro: str, pjs: list[tuple[int, str, str]]) -> str:
    pj_xml = "\n".join(
        f"""
            <PJ NumOrdre="{num}">
                <Contenu>eA==</Contenu>
                <NomPJ>{name}</NomPJ>
                <CategoriePJ>{categorie}</CategoriePJ>
                <TypePJ>01</TypePJ>
                <MimeTypePJ>application/pdf</MimeTypePJ>
            </PJ>"""
        for num, name, categorie in pjs
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<CPPFacturePivot xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:noNamespaceSchemaLocation="CPPFacturePivot.xsd">
    <Enveloppe><ID>ENV</ID></Enveloppe>
    <CPPFactures Compteur="1">
        <CPPFacturePivotUnitaire NumOrdre="1">
            <Fournisseur>
                <TypeIdentifiant>SIREN</TypeIdentifiant>
                <Identifiant>123456789</Identifiant>
                <RaisonSociale>Fournisseur</RaisonSociale>
                <CodePays>FR</CodePays>
                <ModeEmission>E</ModeEmission>
            </Fournisseur>
            <Debiteur>
                <TypeIdentifiant>SIREN</TypeIdentifiant>
                <Identifiant>987654321</Identifiant>
                <Nom>Client</Nom>
                <CodeService>SERVICE</CodeService>
                <NomService>Service</NomService>
            </Debiteur>
            <DonneesFacture>
                <Id>F001</Id>
                <IdCPRO>{id_cpro}</IdCPRO>
                <Renvoi>Non</Renvoi>
                <Type>1</Type>
                <Cadre>TEST</Cadre>
                <DateEmissionFacture>2025-01-01</DateEmissionFacture>
                <DateLivraison>2025-01-01</DateLivraison>
                <DateReception>2025-01-01</DateReception>
                <ModePaiement><Code>VIR</Code><Libelle>Virement</Libelle></ModePaiement>
                <Devise>EUR</Devise>
                <Montants>
                    <MontantHT>100.00</MontantHT>
                    <MontantTTC>120.00</MontantTTC>
                    <MontantNetAPayer>120.00</MontantNetAPayer>
                </Montants>
                <Engagement><NumeroEngagement>ENG</NumeroEngagement></Engagement>
                <TVAs></TVAs>
                <Lignes></Lignes>
            </DonneesFacture>
            {pj_xml}
        </CPPFacturePivotUnitaire>
    </CPPFactures>
</CPPFacturePivot>"""


def _put(s3_client, key: str, body: bytes | str) -> None:
    if isinstance(body, str):
        body = body.encode()
    s3_client.Bucket("test-depec").put_object(Key=key, Body=body)


def test_scan_inventory_selects_pdf_and_skips_xml(
    s3_client, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
):
    prefix = f"test-extract-pdf/{request.node.name}"
    monkeypatch.setattr("gesec.data.extract_pdf.selection.UNZIPPED_PREFIX", prefix)
    monkeypatch.setattr(
        "gesec.data.extract_pdf.selection._existing_headers",
        lambda ids: set(ids) - {"444444444"},
    )

    _put(
        s3_client,
        f"{prefix}/facture_111111111/PivotS.xml",
        _pivot_xml("111111111", [(1, "facture.pdf", "Facture PDF")]),
    )
    _put(s3_client, f"{prefix}/facture_111111111/pivot/facture.pdf", b"pdf")
    _put(
        s3_client,
        f"{prefix}/facture_222222222/PivotS.xml",
        _pivot_xml("222222222", [(1, "facture.pdf", "Facture PDF")]),
    )
    _put(s3_client, f"{prefix}/facture_222222222/pivot/facture.xml", b"xml")
    _put(s3_client, f"{prefix}/facture_222222222/pivot/facture.pdf", b"pdf")
    _put(
        s3_client,
        f"{prefix}/facture_333333333/PivotS.xml",
        _pivot_xml("333333333", [(1, "annexe.pdf", "Document annexe")]),
    )
    _put(
        s3_client,
        f"{prefix}/facture_444444444/PivotS.xml",
        _pivot_xml("444444444", [(1, "facture.pdf", "Facture PDF")]),
    )
    _put(s3_client, f"{prefix}/facture_444444444/pivot/facture.pdf", b"pdf")

    selection = scan_inventory()

    assert sorted(selection.candidates) == ["111111111"]
    assert selection.candidates["111111111"].pdf_filename == "facture.pdf"
    assert selection.header_missing == ["444444444"]
    assert selection.no_pdf == ["333333333"]
    assert selection.xml_ids == {"222222222"}


def test_scan_inventory_chooses_first_pdf_by_num_ordre_and_duplicate_suffix(
    s3_client, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
):
    prefix = f"test-extract-pdf/{request.node.name}"
    monkeypatch.setattr("gesec.data.extract_pdf.selection.UNZIPPED_PREFIX", prefix)
    monkeypatch.setattr("gesec.data.extract_pdf.selection._existing_headers", lambda ids: set(ids))

    _put(
        s3_client,
        f"{prefix}/facture_555555555/PivotS.xml",
        _pivot_xml(
            "555555555",
            [
                (1, "duplicata.pdf", "DUPLICATA_FACTUR-X"),
                (2, "facture.pdf", "Facture PDF"),
                (1, "facture.pdf", "Facture PDF"),
            ],
        ),
    )
    _put(s3_client, f"{prefix}/facture_555555555/pivot/facture.3.pdf", b"pdf")

    selection = scan_inventory()

    assert selection.candidates["555555555"].pdf_filename == "facture.3.pdf"


def test_scan_inventory_tracks_pivot_parse_error(
    s3_client, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
):
    prefix = f"test-extract-pdf/{request.node.name}"
    monkeypatch.setattr("gesec.data.extract_pdf.selection.UNZIPPED_PREFIX", prefix)
    monkeypatch.setattr("gesec.data.extract_pdf.selection._existing_headers", lambda ids: set(ids))

    _put(s3_client, f"{prefix}/facture_666666666/PivotS.xml", "<not-xml")

    selection = scan_inventory()

    assert "666666666" in selection.parse_errors
    assert selection.candidates == {}


def _candidate(id_cpro: str) -> PdfCandidate:
    return PdfCandidate(
        id_cpro=id_cpro,
        folder=f"facture_{id_cpro}",
        pdf_path=f"pivot/{id_cpro}.pdf",
        pdf_filename=f"{id_cpro}.pdf",
    )


def test_select_targets_modes_and_error_filter():
    selection = PdfSelection(
        candidates={id_cpro: _candidate(id_cpro) for id_cpro in ("1", "2", "3", "4", "5", "9")},
        header_missing=[],
        no_pdf=[],
        parse_errors={},
        xml_ids={"9"},
        all_ids={"1", "2", "3", "4", "5", "9"},
    )
    results = {
        "1": BronzeExtractPdf(id_cpro="1", status="failed", error_type="llm"),
        "2": BronzeExtractPdf(id_cpro="2", status="success"),
        "3": BronzeExtractPdf(id_cpro="3", status="no_lines"),
        "4": BronzeExtractPdf(id_cpro="4", status="failed", error_type="ocr"),
    }

    assert select_targets(selection, results, mode="new") == (["5"], 1)
    assert select_targets(selection, results, mode="retry") == (["1", "3", "4"], 0)
    assert select_targets(selection, results, mode="retry", error_types=["llm"]) == (["1"], 0)
    assert select_targets(selection, results, mode="retry", error_types=["no_lines"]) == (["3"], 0)
    assert select_targets(selection, results, mode="retry", error_types=["failed"]) == (["1", "4"], 0)
    assert select_targets(selection, results, mode="reprocess") == (["1", "2", "3", "4"], 0)
    assert select_targets(selection, results, mode="all") == (["1", "2", "3", "4", "5"], 1)


def _ligne(**overrides) -> ExtractedLigne:
    values = {
        "line_id": "1",
        "item_name": "Prestation",
        "item_description": "",
        "item_reference": None,
        "quantity": Decimal("1"),
        "quantity_unit_code": "C62",
        "unit_price": Decimal("100"),
        "line_amount_excl_tax": Decimal("100"),
        "line_amount_incl_tax": Decimal("120"),
        "line_amount_vat": Decimal("20"),
        "currency": "EUR",
    }
    values.update(overrides)
    return ExtractedLigne(**values)


def _facture(*lignes: ExtractedLigne) -> ExtractedFacture:
    return ExtractedFacture(objet_facture="Objet", lignes=list(lignes))


def test_transform_to_silver_derives_ttc_from_ht_and_vat():
    lignes, error = transform_to_silver(
        _facture(_ligne(line_amount_incl_tax=None)),
        id_cpro="1",
        pdf_filename="facture.pdf",
    )

    assert error is None
    assert len(lignes) == 1
    assert lignes[0].line_amount_vat == Decimal("20")
    assert lignes[0].line_amount_incl_tax == Decimal("120")
    assert lignes[0].pdf_filename == "facture.pdf"


def test_transform_to_silver_rejects_duplicate_line_id():
    lignes, error = transform_to_silver(
        _facture(_ligne(), _ligne()),
        id_cpro="1",
        pdf_filename="facture.pdf",
    )
    assert lignes == []
    assert error is not None and "dupliqué" in error


def test_transform_to_silver_rejects_line_amount_mismatch():
    lignes, error = transform_to_silver(
        _facture(_ligne(line_amount_vat=Decimal("10"))),
        id_cpro="1",
        pdf_filename="facture.pdf",
    )
    assert lignes == []
    assert error is not None and "HT + TVA" in error


def test_transform_to_silver_reports_incomplete_amounts():
    lignes, error = transform_to_silver(
        _facture(_ligne(line_amount_incl_tax=None, line_amount_vat=None)),
        id_cpro="1",
        pdf_filename="facture.pdf",
    )

    assert error is None
    assert lignes[0].line_amount_excl_tax == Decimal("100")
    assert lignes[0].line_amount_incl_tax is None
    assert lignes[0].line_amount_vat is None


def test_run_extract_dry_run_counts_statuses_without_writes():
    selection = PdfSelection(
        candidates={"1": _candidate("1")},
        header_missing=["2"],
        no_pdf=["3"],
        parse_errors={"4": "bad xml"},
        xml_ids=set(),
        all_ids={"1", "2", "3", "4"},
    )

    summary = run_extract(selection=selection, results={}, mode="new", dry_run=True)

    assert summary.selected == 4
    assert summary.pending == 1
    assert summary.header_missing == 1
    assert summary.no_pdf == 1
    assert summary.failed == 1
    assert summary.success == 0
