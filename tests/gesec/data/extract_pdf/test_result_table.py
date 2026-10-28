from collections.abc import Iterator

import psycopg
import pytest
from psycopg import sql

from gesec.data.classify_gm.db import get_database_url
from gesec.data.extract_pdf.result_table import TABLE_NAME, load_results, upsert
from gesec.data.extract_pdf.schemas import BronzeExtractPdf

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def bronze_table(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", get_database_url())
    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(TABLE_NAME)))
    connection.commit()
    yield
    with connection.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(TABLE_NAME)))
    connection.commit()
    connection.close()


def test_load_results_without_table(bronze_table: None) -> None:
    assert load_results() == {}


def test_upsert_creates_and_increments_attempts(bronze_table: None) -> None:
    upsert(BronzeExtractPdf(id_cpro="1", status="failed", error_type="llm", error="boom"))
    first = load_results()["1"]

    assert first.status == "failed"
    assert first.attempts == 1
    assert first.last_attempt_at is not None
    assert first.created_at is not None

    upsert(BronzeExtractPdf(id_cpro="1", status="success", content={"objet_facture": "Objet"}))

    second = load_results()["1"]
    assert second.status == "success"
    assert second.content == {"objet_facture": "Objet"}
    assert second.error_type is None
    assert second.attempts == 2
    assert second.created_at == first.created_at
