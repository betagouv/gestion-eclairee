"""Table bronze persistante des tentatives d'extraction PDF."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, MetaData, Table, Text, func
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from gesec.data.extract_pdf.schemas import BronzeExtractPdf
from gesec.data.pipeline.db import create_engine, iter_rows_from_table

TABLE_NAME = "bronze_extract_pdf"

TABLE = Table(
    TABLE_NAME,
    MetaData(),
    Column("id_cpro", Text, primary_key=True),
    Column("status", Text, nullable=False),
    Column("content", JSONB),
    Column("pdf_path", Text),
    Column("pdf_filename", Text),
    Column("pdf_sha256", Text),
    Column("markdown_path", Text),
    Column("markdown_sha256", Text),
    Column("page_count", Integer),
    Column("extraction_model", Text),
    Column("prompt_version", Text),
    Column("error_type", Text),
    Column("error", Text),
    Column("attempts", Integer, nullable=False),
    Column("last_attempt_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


def ensure_table() -> None:
    TABLE.create(create_engine(), checkfirst=True)


def load_results() -> dict[str, BronzeExtractPdf]:
    engine = create_engine()
    if not sqlalchemy_inspect(engine).has_table(TABLE_NAME):
        return {}
    return {row.id_cpro: row for row in iter_rows_from_table(TABLE_NAME, BronzeExtractPdf)}


def upsert(result: BronzeExtractPdf) -> None:
    """Insère ou met à jour une tentative, en incrémentant `attempts` sur conflit."""
    ensure_table()
    now = datetime.now(UTC)
    values = result.model_dump(exclude={"created_at", "updated_at", "last_attempt_at"})
    values.update(attempts=1, last_attempt_at=now, created_at=now, updated_at=now)

    statement = pg_insert(TABLE).values(**values)
    update_values = {
        column: getattr(statement.excluded, column)
        for column in TABLE.c.keys()
        if column not in {"id_cpro", "created_at"}
    }
    update_values.update(attempts=TABLE.c.attempts + 1, last_attempt_at=func.now(), updated_at=func.now())
    statement = statement.on_conflict_do_update(index_elements=[TABLE.c.id_cpro], set_=update_values)

    engine = create_engine()
    with engine.begin() as conn:
        conn.execute(statement)
