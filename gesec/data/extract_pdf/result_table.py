"""Table bronze persistante des tentatives d'extraction PDF."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, MetaData, Table, Text, func, text
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from gesec.data.extract_pdf.schemas import (
    ERROR_STATUSES,
    BronzeExtractPdf,
)
from gesec.data.pipeline.db import create_engine, execute_sql

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


def select_target_ids(
    inventory_ids: Sequence[str],
    *,
    mode: str,
    error_types: Sequence[str] | None = None,
    id_filter: Sequence[str] | None = None,
) -> set[str]:
    """Sélectionne en SQL les `id_cpro` cibles, bornés par `inventory_ids`.

    Les modes `new` et `all` se résolvent sans lire la table ; `retry` et
    `reprocess` filtrent `bronze_extract_pdf` par statut (`retry` accepte en
    outre un filtre `error_types`). Seule la colonne `id_cpro` est lue.
    """
    if mode not in ("new", "retry", "reprocess", "all"):
        raise ValueError(f"mode invalide : {mode!r} (attendu : new|retry|reprocess|all)")
    if not inventory_ids:
        return set()
    if mode == "all":
        return set(inventory_ids)

    engine = create_engine()
    has_table = sqlalchemy_inspect(engine).has_table(TABLE_NAME)

    if mode == "new":
        if not has_table:
            return set(inventory_ids)
        rows = execute_sql(
            text(f"SELECT id_cpro FROM {TABLE_NAME} WHERE id_cpro = ANY(:ids)"),
            {"ids": list(inventory_ids)},
        )
        return set(inventory_ids) - {row.id_cpro for row in rows}

    if not has_table:
        return set()
    if mode == "reprocess":
        statement = f"SELECT id_cpro FROM {TABLE_NAME} WHERE id_cpro = ANY(:ids)"
        parameters: dict[str, object] = {"ids": list(inventory_ids)}
    else:
        statement = f"SELECT id_cpro FROM {TABLE_NAME} WHERE id_cpro = ANY(:ids) AND status = ANY(:statuses)"
        parameters = {"ids": list(inventory_ids), "statuses": list(ERROR_STATUSES)}
        if error_types:
            allowed = list(error_types)
            statement += " AND (error_type = ANY(:allowed) OR status = ANY(:allowed))"
            parameters["allowed"] = allowed
    if id_filter:
        statement += " AND id_cpro = ANY(:explicit)"
        parameters["explicit"] = list(id_filter)

    rows = execute_sql(text(statement), parameters)
    return {row.id_cpro for row in rows}


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
