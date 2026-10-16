import datetime
import logging
import os
from collections.abc import Iterable, Iterator
from decimal import Decimal
from typing import Any, Literal, Optional, Sequence, Type, TypeVar, Union, get_args, get_origin
from uuid import UUID

import sqlalchemy
from pydantic import BaseModel
from sqlalchemy import ARRAY, Column, Engine, Executable, MetaData, Row, Table, text
from sqlalchemy.dialects.postgresql import HSTORE, JSONB
from sqlalchemy.engine.interfaces import _CoreAnyExecuteParams
from sqlalchemy.sql.sqltypes import TypeEngine

logger = logging.getLogger(__name__)


T = TypeVar("T")

IfExists = Literal["replace", "append"]

DEFAULT_BATCH_SIZE = 1000

_TYPE_MAPPING: dict[Any, type[TypeEngine]] = {
    str: sqlalchemy.types.TEXT,
    int: sqlalchemy.types.INTEGER,
    float: sqlalchemy.types.FLOAT,
    bool: sqlalchemy.types.BOOLEAN,
    dict: JSONB,
    list: HSTORE,
    Any: JSONB,
    datetime.date: sqlalchemy.types.DATE,
    datetime.datetime: sqlalchemy.types.TIMESTAMP,
    datetime.time: sqlalchemy.types.TIME,
    UUID: sqlalchemy.types.UUID,
    Decimal: sqlalchemy.types.DECIMAL,
}


def create_engine() -> Engine:
    # Get database URL from environment
    db_url = os.environ.get("DATABASE_URL")
    if db_url is None:
        raise ValueError("DATABASE_URL environment variable is required")
    db_url = db_url.replace("postgres:", "postgresql+psycopg:")

    # Create SQLAlchemy engine
    return sqlalchemy.create_engine(db_url)


def execute_sql(statement: Executable, parameters: Optional[_CoreAnyExecuteParams] = None) -> Sequence[Row[Any]]:
    engine = create_engine()
    with engine.connect() as conn:
        result = conn.execute(statement, parameters)
        rows = result.fetchall()
        return rows


def sqltype_for_annotation(annotation: Any) -> TypeEngine:
    """Résout une annotation Python en type SQLAlchemy.

    Mapping :
    - dict, Any -> JSONB
    - list -> HSTORE, list[T] -> ARRAY(T)
    - datetime.date -> DATE, datetime.datetime -> TIMESTAMP, datetime.time -> TIME
    - str -> TEXT, int -> INTEGER, float -> FLOAT, bool -> BOOLEAN
    - UUID -> UUID, Decimal -> DECIMAL
    - Optional[T] -> T, Literal -> TEXT
    - défaut -> TEXT
    """
    origin = get_origin(annotation)
    if origin is Union:
        args = get_args(annotation)
        if len(args) == 2 and type(None) in args:
            annotation = next(arg for arg in args if arg is not type(None))
        else:
            raise ValueError(f"Unknown annotation {annotation}")
        origin = get_origin(annotation)
    elif origin is Literal:
        annotation = str

    if origin is list:
        args = get_args(annotation)
        item_type = args[0] if args else str
        return ARRAY(sqltype_for_annotation(item_type))

    final_type = _TYPE_MAPPING.get(annotation, sqlalchemy.types.TEXT)
    return final_type()


def pydantic_model_to_table(model_class: Type[BaseModel], table_name: str, use_validation_alias: bool = False) -> Table:
    """Construit une table SQLAlchemy à partir des champs d'un modèle Pydantic.

    Si `use_validation_alias`, les colonnes portent l'alias d'entrée du champ
    lorsqu'il existe (cas des dictionnaires issus de colonnes sources) ; sinon
    elles portent le nom du champ (cas de `model_dump`).
    """
    columns = [
        Column(_column_name(field_name, field, use_validation_alias), sqltype_for_annotation(field.annotation))
        for field_name, field in model_class.model_fields.items()
    ]
    return Table(table_name, MetaData(), *columns)


def _column_name(field_name: str, field: Any, use_validation_alias: bool) -> str:
    if use_validation_alias and isinstance(field.validation_alias, str):
        return field.validation_alias
    return field_name


def create_empty_table(table: Table) -> None:
    """Vide (drop) puis recrée une table vide à partir de sa définition SQLAlchemy."""
    engine = create_engine()
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table.name}"))
    table.create(engine)
    logger.info(f"Created empty table {table.name}")


def _write_batch(
    engine: Engine,
    table: Table,
    batch: list[dict],
) -> int:
    with engine.begin() as conn:
        conn.execute(table.insert(), batch)
    return len(batch)


def load_rows_from_table(table_name: str, row_model: Type[T]) -> list[T]:
    rows = execute_sql(text(f"SELECT * FROM {table_name}"))
    return [row_model(**row._asdict()) for row in rows]


def iter_rows_from_table(
    table_name: str,
    row_model: Type[T],
    batch_size: int = DEFAULT_BATCH_SIZE,
    query: Optional[str] = None,
) -> Iterator[T]:
    """Itère les lignes d'une table, via un cursor serveur psycopg.

    Évite de charger toute la table en mémoire lorsque celle-ci est figée
    (lecture en aval d'une écriture). Le cursor nommé laisse Postgres streamer
    les résultats. Si `query` est fourni, elle est exécutée à la place du
    `SELECT *` par défaut ; les colonnes sont lues via `cursor.description`.
    """
    engine = create_engine()
    raw_conn = engine.raw_connection()
    cursor = raw_conn.cursor(name=f"iter_{table_name}")
    try:
        cursor.execute(query if query is not None else f"SELECT * FROM {table_name}")
        columns = [desc[0] for desc in cursor.description]
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            for row in rows:
                yield row_model(**dict(zip(columns, row, strict=True)))
    finally:
        cursor.close()
        raw_conn.close()


class TableWriter:
    """Accumule des lignes et les écrit par lots dans une table.

    Utilisable comme gestionnaire de contexte : `init` prépare la table
    (`replace` : recréée vide), `add`/`add_all` bufferisent les lignes et
    déclenchent l'écriture dès que `batch_size` est atteint ; `finish` vide le
    reliquat et renvoie le total écrit. `__exit__` garantit l'appel à `finish`.
    Seul le premier lot suit `if_exists`, les suivants sont ajoutés en `append`.

    Les lignes sont des modèles Pydantic (`add`/`add_all`) ou des dictionnaires
    dont les clés correspondent aux colonnes (`add_dict`/`add_all_dicts`) ; dans
    ce cas, `use_validation_alias` aligne les colonnes sur l'alias d'entrée des
    champs.
    """

    def __init__(
        self,
        table_name: str,
        model: Type[BaseModel],
        if_exists: IfExists = "replace",
        batch_size: int = DEFAULT_BATCH_SIZE,
        use_validation_alias: bool = False,
    ) -> None:
        self.table = pydantic_model_to_table(model, table_name, use_validation_alias=use_validation_alias)
        self.if_exists = if_exists
        self.batch_size = batch_size
        self.engine = create_engine()
        self.buffer: list[dict] = []
        self.written = 0
        self.finished = False

    def __enter__(self) -> TableWriter:
        self.init()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if exc_type is None:
            self.finish()

    def init(self) -> None:
        if self.if_exists == "replace":
            create_empty_table(self.table)
        if self.batch_size < 1:
            raise ValueError(f"Invalid batch_size {self.batch_size}")

    def add(self, row: BaseModel) -> None:
        self._push(row.model_dump())

    def add_all(self, rows: Iterable[BaseModel]) -> None:
        for row in rows:
            self.add(row)

    def add_dict(self, row: dict) -> None:
        self._push(row)

    def add_all_dicts(self, rows: Iterable[dict]) -> None:
        for row in rows:
            self.add_dict(row)

    def finish(self) -> int:
        self._flush()
        self.finished = True
        if self.written == 0:
            if self.if_exists == "replace":
                create_empty_table(self.table)
            logger.warning(f"No data to export, skipping database insertion in {self.table.name}")
        return self.written

    def _push(self, row: dict) -> None:
        self.buffer.append(row)
        if len(self.buffer) >= self.batch_size:
            self._flush()

    def _flush(self) -> None:
        if not self.buffer:
            return
        self.written += _write_batch(self.engine, self.table, self.buffer)
        self.buffer = []
