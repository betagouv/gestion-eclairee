from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import cast

import psycopg
import pymupdf
import pytest

from gesec.data.classify_gm.llm import LLMClient
from gesec.data.extract_pdf.extract_llm import parse_extraction
from gesec.data.extract_pdf.ocr_lighton import LightonOcrClient
from gesec.data.extract_pdf.paths import markdown_storage_path
from gesec.data.extract_pdf.pdf4llm_extract import (
    extract_invoice_pdf4llm_markdown,
    extract_invoice_pdf4llm_markdown_lighton,
    extract_pdf_markdown,
)
from gesec.data.extract_pdf.pdf_utils import page_count, pdf_within_page_limit
from gesec.data.extract_pdf.prompt import response_format_lignes
from gesec.data.extract_pdf.result_table import TABLE_NAME, upsert
from gesec.data.extract_pdf.run import ExtractSummary, _process_candidates, resolve_pdf, run_extract, select_targets
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


def test_scan_inventory_selects_factures_without_gold_lines(
    s3_client, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest, gold_tables: None
):
    prefix = f"test-extract-pdf/{request.node.name}"
    monkeypatch.setattr("gesec.data.extract_pdf.selection.UNZIPPED_PREFIX", prefix)
    _seed_gold(
        factures=["111111111", "222222222", "333333333", "444444444", "555555555"],
        lignes=["222222222"],
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
    _put(s3_client, f"{prefix}/facture_222222222/pivot/facture.factur-x.xml", b"xml")
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

    assert sorted(selection.candidates) == ["111111111", "333333333", "444444444", "555555555"]
    assert selection.candidates["111111111"].folder == "facture_111111111"
    assert selection.candidates["333333333"].folder == "facture_333333333"
    assert selection.candidates["555555555"].folder is None


def test_resolve_pdf_chooses_first_pdf_by_num_ordre_and_duplicate_suffix(
    s3_client, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
):
    prefix = f"test-extract-pdf/{request.node.name}"
    monkeypatch.setattr("gesec.data.extract_pdf.run.UNZIPPED_PREFIX", prefix)

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

    resolved = resolve_pdf(PdfCandidate(id_cpro="555555555", folder="facture_555555555"))

    assert resolved == (f"{prefix}/facture_555555555/pivot/facture.3.pdf", "facture.3.pdf")


def test_resolve_pdf_returns_none_without_facture_pdf(
    s3_client, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
):
    prefix = f"test-extract-pdf/{request.node.name}"
    monkeypatch.setattr("gesec.data.extract_pdf.run.UNZIPPED_PREFIX", prefix)

    _put(
        s3_client,
        f"{prefix}/facture_666666666/PivotS.xml",
        _pivot_xml("666666666", [(1, "annexe.pdf", "Document annexe")]),
    )

    assert resolve_pdf(PdfCandidate(id_cpro="666666666", folder="facture_666666666")) is None


def test_resolve_pdf_returns_none_without_folder():
    assert resolve_pdf(PdfCandidate(id_cpro="777777777", folder=None)) is None


def test_resolve_pdf_raises_on_unreadable_pivot(
    s3_client, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
):
    prefix = f"test-extract-pdf/{request.node.name}"
    monkeypatch.setattr("gesec.data.extract_pdf.run.UNZIPPED_PREFIX", prefix)

    _put(s3_client, f"{prefix}/facture_777777777/PivotS.xml", "<not-xml")

    with pytest.raises(Exception):
        resolve_pdf(PdfCandidate(id_cpro="777777777", folder="facture_777777777"))


def _candidate(id_cpro: str) -> PdfCandidate:
    return PdfCandidate(id_cpro=id_cpro, folder=f"facture_{id_cpro}")


@pytest.fixture
def bronze_table(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from psycopg import sql

    from gesec.data.classify_gm.db import get_database_url

    monkeypatch.setenv("DATABASE_URL", get_database_url())
    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(TABLE_NAME)))
    connection.commit()
    connection.close()
    yield
    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(TABLE_NAME)))
    connection.commit()
    connection.close()


def _seed_gold(*, factures: list[str], lignes: list[str]) -> None:
    from psycopg import sql

    from gesec.data.classify_gm.db import get_database_url

    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        for table in ("gesec_facture", "gesec_facture_ligne"):
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table)))
        cur.execute("CREATE TABLE gesec_facture (identifiant_chorus_pro text)")
        cur.execute("CREATE TABLE gesec_facture_ligne (id_cpro text)")
        cur.executemany("INSERT INTO gesec_facture VALUES (%s)", [(id_cpro,) for id_cpro in factures])
        cur.executemany("INSERT INTO gesec_facture_ligne VALUES (%s)", [(id_cpro,) for id_cpro in lignes])
    connection.commit()
    connection.close()


@pytest.fixture
def gold_tables(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from psycopg import sql

    from gesec.data.classify_gm.db import get_database_url

    monkeypatch.setenv("DATABASE_URL", get_database_url())
    yield
    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        for table in ("gesec_facture", "gesec_facture_ligne"):
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table)))
    connection.commit()
    connection.close()


@pytest.mark.django_db(transaction=True)
def test_select_targets_respecte_les_modes(bronze_table: None):
    upsert(BronzeExtractPdf(id_cpro="1", status="failed", error_type="llm"))
    upsert(BronzeExtractPdf(id_cpro="2", status="success"))
    selection = PdfSelection(
        candidates={id_cpro: _candidate(id_cpro) for id_cpro in ("1", "2", "5", "9")},
    )

    assert select_targets(selection, mode="new") == ["5"]
    assert select_targets(selection, mode="retry") == ["1"]
    assert select_targets(selection, mode="reprocess") == ["1", "2"]
    assert select_targets(selection, mode="all") == ["1", "2", "5", "9"]
    assert select_targets(selection, mode="new", id_filter=["9"]) == ["9"]
    assert select_targets(selection, mode="all", id_filter=["5", "9"]) == ["5", "9"]


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


@pytest.mark.django_db(transaction=True)
def test_run_extract_dry_run_counts_statuses_without_writes(bronze_table: None):
    selection = PdfSelection(
        candidates={"1": _candidate("1")},
    )

    summary = run_extract(selection=selection, mode="new", dry_run=True)

    assert summary.selected == 1
    assert summary.pending == 1
    assert summary.success == 0


@pytest.mark.django_db(transaction=True)
def test_run_extract_limit_borne_les_candidats(bronze_table: None):
    selection = PdfSelection(
        candidates={id_cpro: _candidate(id_cpro) for id_cpro in ("1", "2", "3")},
    )

    summary = run_extract(selection=selection, mode="new", limit=2, dry_run=True)

    assert summary.selected == 3
    assert summary.pending == 2


def test_process_candidates_borne_les_taches_en_vol(monkeypatch: pytest.MonkeyPatch):
    import threading
    import time

    from gesec.data.extract_pdf import run as run_module
    from gesec.data.extract_pdf.pdf4llm_extract import PdfMarkdownResult
    from gesec.data.extract_pdf.schemas import BronzeExtractPdf

    lock = threading.Lock()
    md_in_flight = 0
    llm_in_flight = 0
    max_md = 0
    max_llm = 0

    def fake_markdown(candidate, *, ocr_client, force_refresh, max_pages):
        nonlocal md_in_flight, max_md
        with lock:
            md_in_flight += 1
            max_md = max(max_md, md_in_flight)
        time.sleep(0.02)
        with lock:
            md_in_flight -= 1
        return PdfMarkdownResult(
            markdown="texte",
            duration_s=0.0,
            page_count=1,
            pdf_sha256=None,
            markdown_sha256=None,
            markdown_cached=False,
            markdown_path="",
        )

    def fake_llm(candidate, markdown, *, llm_client, extraction_model):
        nonlocal llm_in_flight, max_llm
        with lock:
            llm_in_flight += 1
            max_llm = max(max_llm, llm_in_flight)
        time.sleep(0.02)
        with lock:
            llm_in_flight -= 1
        return BronzeExtractPdf(id_cpro=candidate.id_cpro, status="success")

    monkeypatch.setattr(run_module, "_safe_markdown", fake_markdown)
    monkeypatch.setattr(run_module, "_run_llm", fake_llm)
    monkeypatch.setattr(run_module, "ensure_table", lambda: None)
    monkeypatch.setattr(run_module, "upsert", lambda result, *, ensure=True: None)

    candidates = [_candidate(str(index)) for index in range(20)]
    summary = ExtractSummary(mode="new", dry_run=False)

    _process_candidates(
        candidates,
        summary=summary,
        llm_client=cast("LLMClient", object()),
        ocr_client=cast("LightonOcrClient", object()),
        force_refresh=False,
        max_pages=50,
        workers=3,
        md_workers=2,
        extraction_model="test",
    )

    assert max_md <= 2
    assert max_llm <= 3
    assert summary.success == 20
