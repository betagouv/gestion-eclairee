from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg import sql

from gesec.data.classify_gm.db import get_database_url
from gesec.data.extract_pdf.result_table import TABLE_NAME as BRONZE_TABLE_NAME
from gesec.data.extract_pdf.result_table import upsert
from gesec.data.extract_pdf.schemas import BronzeExtractPdf, ExtractedFacture, ExtractedLigne
from gesec.data.pipeline.layer_2_silver.extract_pdf_facture import (
    DEFAULT_TABLE_NAME as FACTURE_TABLE_NAME,
)
from gesec.data.pipeline.layer_2_silver.extract_pdf_facture import process_to_silver
from gesec.data.pipeline.layer_2_silver.extract_pdf_ligne import (
    DEFAULT_TABLE_NAME as LIGNE_TABLE_NAME,
)
from gesec.data.pipeline.layer_2_silver.extract_pdf_ligne import derive_amounts, transform_to_silver

pytestmark = pytest.mark.django_db(transaction=True)

TABLES = (BRONZE_TABLE_NAME, FACTURE_TABLE_NAME, LIGNE_TABLE_NAME)


@pytest.fixture
def tables(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", get_database_url())
    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        _drop_tables(cur)
    connection.commit()
    connection.close()
    yield
    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        _drop_tables(cur)
    connection.commit()
    connection.close()


def _drop_tables(cur: psycopg.Cursor) -> None:
    for table in TABLES:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table)))


def test_process_to_silver_writes_factures_and_lignes(tables: None) -> None:
    upsert(
        BronzeExtractPdf(
            id_cpro="1",
            status="success",
            pdf_filename="facture1.pdf",
            content={
                "objet_facture": "Objet PDF",
                "lignes": [
                    {
                        "line_id": "1",
                        "item_name": "Prestation",
                        "item_description": "",
                        "quantity": "1",
                        "unit_price": "100",
                        "line_amount_excl_tax": "100",
                        "line_amount_incl_tax": "120",
                        "line_amount_vat": "20",
                        "currency": "EUR",
                    }
                ],
            },
        )
    )
    upsert(BronzeExtractPdf(id_cpro="2", status="no_lines", content={"lignes": []}))
    upsert(BronzeExtractPdf(id_cpro="3", status="failed", error_type="llm", error="boom"))

    process_to_silver()

    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT id_cpro, status, objet_facture, error_type FROM {} ORDER BY id_cpro").format(
                sql.Identifier(FACTURE_TABLE_NAME)
            )
        )
        assert cur.fetchall() == [
            ("1", "success", "Objet PDF", None),
            ("2", "no_lines", None, None),
            ("3", "failed", None, "llm"),
        ]
        cur.execute(
            sql.SQL("SELECT id_cpro, line_id, line_amount_incl_tax, currency FROM {}").format(
                sql.Identifier(LIGNE_TABLE_NAME)
            )
        )
        assert cur.fetchall() == [("1", "1", 120, "EUR")]
    connection.close()


def _ligne(**overrides: Any) -> ExtractedLigne:
    values: dict[str, Any] = {
        "line_id": "1",
        "item_name": "Prestation",
        "quantity": Decimal("1"),
        "unit_price": Decimal("100"),
        "line_amount_excl_tax": Decimal("100"),
        "line_amount_incl_tax": Decimal("120"),
        "line_amount_vat": Decimal("20"),
        "currency": "EUR",
    }
    values.update(overrides)
    return ExtractedLigne(**values)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, (Decimal("100"), Decimal("120"), Decimal("20"))),
        ({"line_amount_vat": None}, (Decimal("100"), Decimal("120"), Decimal("20"))),
        ({"line_amount_incl_tax": None}, (Decimal("100"), Decimal("120"), Decimal("20"))),
        ({"line_amount_excl_tax": None}, (Decimal("100"), Decimal("120"), Decimal("20"))),
        (
            {"line_amount_excl_tax": None, "line_amount_incl_tax": None},
            (None, None, Decimal("20")),
        ),
    ],
)
def test_derive_amounts_reconstruit_les_trois_montants(overrides: dict, expected: tuple) -> None:
    assert derive_amounts(_ligne(**overrides)) == expected


def test_transform_to_silver_rejette_un_line_id_duplique() -> None:
    facture = ExtractedFacture(lignes=[_ligne(line_id="1"), _ligne(line_id="1")])

    lignes, error = transform_to_silver(facture, id_cpro="1", pdf_filename="facture.pdf")

    assert lignes == []
    assert error is not None


def test_transform_to_silver_rejette_ht_plus_tva_different_de_ttc() -> None:
    facture = ExtractedFacture(lignes=[_ligne(line_amount_incl_tax=Decimal("121"))])

    lignes, error = transform_to_silver(facture, id_cpro="1", pdf_filename="facture.pdf")

    assert lignes == []
    assert error is not None


def test_transform_to_silver_report_les_montants_incomplets() -> None:
    facture = ExtractedFacture(lignes=[_ligne(line_amount_vat=None, line_amount_incl_tax=None)])

    lignes, error = transform_to_silver(facture, id_cpro="1", pdf_filename="facture.pdf")

    assert error is None
    assert lignes[0].line_amount_excl_tax == Decimal("100")
    assert lignes[0].line_amount_incl_tax is None
    assert lignes[0].line_amount_vat is None
