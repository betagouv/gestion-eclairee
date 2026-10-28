from collections.abc import Iterator

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import text

from gesec.data.classify_gm.db import get_database_url
from gesec.data.extract_pdf.result_table import TABLE_NAME, select_target_ids, upsert
from gesec.data.extract_pdf.schemas import BronzeExtractPdf
from gesec.data.pipeline.db import execute_sql

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def bronze_table(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", get_database_url())
    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(TABLE_NAME)))
    connection.commit()
    yield
    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(TABLE_NAME)))
    connection.commit()
    connection.close()


def _row(id_cpro: str) -> dict:
    rows = execute_sql(
        text(f"SELECT status, error_type, attempts, content FROM {TABLE_NAME} WHERE id_cpro = :id"), {"id": id_cpro}
    )
    return dict(rows[0]._mapping)


def test_select_target_ids_sans_table(bronze_table: None) -> None:
    assert select_target_ids(["1", "2"], mode="new") == {"1", "2"}
    assert select_target_ids(["1", "2"], mode="all") == {"1", "2"}
    assert select_target_ids(["1", "2"], mode="retry") == set()
    assert select_target_ids(["1", "2"], mode="reprocess") == set()


def test_select_target_ids_avec_id_filter(bronze_table: None) -> None:
    upsert(BronzeExtractPdf(id_cpro="1", status="failed", error_type="llm"))
    inventory = ["1", "2", "3"]

    assert select_target_ids(inventory, mode="new", id_filter=["1", "3"]) == {"3"}
    assert select_target_ids(inventory, mode="all", id_filter=["1", "3"]) == {"1", "3"}
    assert select_target_ids(inventory, mode="retry", id_filter=["1", "3"]) == {"1"}
    assert select_target_ids(inventory, mode="reprocess", id_filter=["1", "3"]) == {"1"}
    assert select_target_ids(inventory, mode="reprocess", id_filter=["3"]) == set()
    assert select_target_ids(inventory, mode="new", id_filter=["9"]) == set()


def test_select_target_ids_modes(bronze_table: None) -> None:
    upsert(BronzeExtractPdf(id_cpro="1", status="failed", error_type="llm"))
    upsert(BronzeExtractPdf(id_cpro="2", status="success"))
    upsert(BronzeExtractPdf(id_cpro="3", status="no_lines"))
    upsert(BronzeExtractPdf(id_cpro="4", status="failed", error_type="ocr"))
    inventory = ["1", "2", "3", "4", "5"]

    assert select_target_ids(inventory, mode="new") == {"5"}
    assert select_target_ids(inventory, mode="retry") == {"1", "3", "4"}
    assert select_target_ids(inventory, mode="retry", error_types=["llm"]) == {"1"}
    assert select_target_ids(inventory, mode="retry", error_types=["no_lines"]) == {"3"}
    assert select_target_ids(inventory, mode="retry", error_types=["failed"]) == {"1", "4"}
    assert select_target_ids(inventory, mode="reprocess") == {"1", "2", "3", "4"}
    assert select_target_ids(inventory, mode="all") == {"1", "2", "3", "4", "5"}
    assert select_target_ids(inventory, mode="reprocess", id_filter=["2", "3", "9"]) == {"2", "3"}


def test_select_target_ids_mode_invalide(bronze_table: None) -> None:
    with pytest.raises(ValueError, match="mode invalide"):
        select_target_ids(["1"], mode="bogus")


def test_upsert_creates_and_increments_attempts(bronze_table: None) -> None:
    upsert(BronzeExtractPdf(id_cpro="1", status="failed", error_type="llm", error="boom"))
    first = _row("1")

    assert first["status"] == "failed"
    assert first["error_type"] == "llm"
    assert first["attempts"] == 1

    upsert(BronzeExtractPdf(id_cpro="1", status="success", content={"objet_facture": "Objet"}))

    second = _row("1")
    assert second["status"] == "success"
    assert second["error_type"] is None
    assert second["attempts"] == 2
    assert second["content"] == {"objet_facture": "Objet"}
