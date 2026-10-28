from collections.abc import Iterator
from decimal import Decimal

import psycopg
import pytest
from psycopg import sql

from gesec.data.classify_gm.db import get_database_url
from gesec.data.pipeline.db import TableWriter
from gesec.data.pipeline.layer_2_silver.extract_pdf_ligne import DEFAULT_TABLE_NAME as SILVER_PDF_LIGNE_TABLE_NAME
from gesec.data.pipeline.layer_2_silver.schemas import SilverExtractPdfLigne
from gesec.data.pipeline.layer_3_gold.extract_pdf import transform_to_gold
from gesec.data.pipeline.layer_3_gold.facture import transform_silver_to_gold
from tests.gesec.data.pipeline.layer_3_gold.test_facture_ligne import silver_facture

pytestmark = pytest.mark.django_db(transaction=True)

_FACTURE_DDL = """
CREATE TABLE gesec_facture (
    identifiant_chorus_pro TEXT PRIMARY KEY,
    mt_ht NUMERIC,
    mt_ttc NUMERIC,
    montant_tva NUMERIC
)
"""


@pytest.fixture
def tables(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", get_database_url())
    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        for table in ("gesec_facture", SILVER_PDF_LIGNE_TABLE_NAME, "silver_extract_pdf_facture"):
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table)))
        cur.execute(_FACTURE_DDL)
        cur.execute("INSERT INTO gesec_facture VALUES ('1', 100, 120, 20), ('2', 100, 120, 20)")
    connection.commit()
    connection.close()
    yield
    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        for table in ("gesec_facture", SILVER_PDF_LIGNE_TABLE_NAME, "silver_extract_pdf_facture"):
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table)))
    connection.commit()
    connection.close()


def _silver_line(id_cpro: str, pdf_filename: str = "facture.pdf", **overrides: object) -> SilverExtractPdfLigne:
    values: dict[str, object] = {
        "id_cpro": id_cpro,
        "pdf_filename": pdf_filename,
        "line_id": "1",
        "item_name": "Article PDF",
        "item_description": "Description",
        "item_reference": "REF",
        "quantity": Decimal("1"),
        "quantity_unit_code": "C62",
        "unit_price": Decimal("100"),
        "line_amount_excl_tax": Decimal("100"),
        "line_amount_incl_tax": Decimal("120"),
        "line_amount_vat": Decimal("20"),
        "currency": "EUR",
    }
    values.update(overrides)
    return SilverExtractPdfLigne(**values)


def _write_silver(lines: list[SilverExtractPdfLigne]) -> None:
    with TableWriter(SILVER_PDF_LIGNE_TABLE_NAME, SilverExtractPdfLigne) as writer:
        writer.add_all(lines)


def test_transform_to_gold_derives_missing_amounts_from_header(tables: None) -> None:
    _write_silver([_silver_line("1", line_amount_incl_tax=None, line_amount_vat=None)])

    lines = list(transform_to_gold(covered_ids=set()))

    assert len(lines) == 1
    assert lines[0].source == "extract_pdf:facture.pdf"
    assert lines[0].line_amount_incl_tax == Decimal("120")
    assert lines[0].line_amount_vat == Decimal("20")


def test_transform_to_gold_skips_covered_and_unknown_factures(tables: None) -> None:
    _write_silver([_silver_line("1"), _silver_line("2"), _silver_line("3")])

    lines = list(transform_to_gold(covered_ids={"2"}))

    assert [line.id_cpro for line in lines] == ["1"]


def test_transform_to_gold_rejects_incoherent_totals(tables: None) -> None:
    _write_silver([_silver_line("1", line_amount_excl_tax=Decimal("200"), line_amount_incl_tax=Decimal("240"))])

    assert list(transform_to_gold(covered_ids=set())) == []


def test_transform_to_gold_regroupe_par_facture_contigue(tables: None) -> None:
    def demi(id_cpro: str, line_id: str) -> SilverExtractPdfLigne:
        return _silver_line(
            id_cpro,
            line_id=line_id,
            quantity=Decimal("1"),
            unit_price=Decimal("50"),
            line_amount_excl_tax=Decimal("50"),
            line_amount_incl_tax=Decimal("60"),
            line_amount_vat=Decimal("10"),
        )

    _write_silver(
        [
            demi("1", "1"),
            _silver_line("2", line_id="1"),
            demi("1", "2"),
        ]
    )

    lines = list(transform_to_gold(covered_ids=set()))

    assert sorted((line.id_cpro, line.line_id) for line in lines) == [("1", "1"), ("1", "2"), ("2", "1")]


def test_transform_to_gold_ecarte_facture_sans_en_tete(tables: None) -> None:
    _write_silver([_silver_line("1"), _silver_line("999")])

    lines = list(transform_to_gold(covered_ids=set()))

    assert [line.id_cpro for line in lines] == ["1"]


def test_transform_silver_to_gold_reprend_objet_pdf(tables: None) -> None:
    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        cur.execute("CREATE TABLE silver_extract_pdf_facture (id_cpro TEXT, objet_facture TEXT)")
        cur.execute("INSERT INTO silver_extract_pdf_facture VALUES ('cpro-1', 'Objet PDF')")
    connection.commit()
    connection.close()

    factures = transform_silver_to_gold(
        iter([silver_facture(id_cpro="cpro-1")]),
        {},
        [],
        "silver_extract_pdf_facture",
    )

    assert [facture.objet_facture for facture in factures] == ["Objet PDF"]

    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier("silver_extract_pdf_facture")))
    connection.commit()
    connection.close()


def test_transform_silver_to_gold_lit_les_objets_par_fenetre(tables: None) -> None:
    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        cur.execute("CREATE TABLE silver_extract_pdf_facture (id_cpro TEXT, objet_facture TEXT)")
        cur.execute(
            "INSERT INTO silver_extract_pdf_facture VALUES "
            "('cpro-1', 'Objet 1'), ('cpro-2', 'Objet 2'), ('cpro-3', 'Objet 3')"
        )
    connection.commit()
    connection.close()

    factures = transform_silver_to_gold(
        iter([silver_facture(id_cpro="cpro-1"), silver_facture(id_cpro="cpro-2"), silver_facture(id_cpro="cpro-3")]),
        {},
        [],
        "silver_extract_pdf_facture",
        batch_size=2,
    )

    assert [facture.objet_facture for facture in factures] == ["Objet 1", "Objet 2", "Objet 3"]

    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier("silver_extract_pdf_facture")))
    connection.commit()
    connection.close()
