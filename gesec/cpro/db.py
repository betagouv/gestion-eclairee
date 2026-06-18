import logging
import os
from typing import Literal

import sqlalchemy
from pydantic import BaseModel
from sqlalchemy import Engine, text

import pandas as pd

from gesec.cpro.schemas import BronzeCproExportFacture

logger = logging.getLogger(__name__)


def create_engine() -> Engine:
    # Get database URL from environment
    db_url = os.environ.get("DATABASE_URL")
    db_url = db_url.replace("postgres:", "postgresql+psycopg:")

    # Create SQLAlchemy engine
    return sqlalchemy.create_engine(db_url)


def load_bronze_factures_cpro_export(table_name: str) -> list[BronzeCproExportFacture]:
    """Récupère toutes les lignes d'une table et les convertit en BronzeCproExportFacture."""
    engine = create_engine()
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT * FROM {table_name}"))
        rows = result.fetchall()
        return [BronzeCproExportFacture(**dict(row._asdict())) for row in rows]


def save_list_dict(
    list_dicts: list[dict],
    table_name: str,
    if_exists: Literal["fail", "replace", "append", "delete_rows"] = "fail",
) -> None:
    df = pd.DataFrame(list_dicts)
    save_df(df, table_name, if_exists=if_exists)


def save_list_pydantic(
    list_objects: list[BaseModel],
    table_name: str,
    if_exists: Literal["fail", "replace", "append", "delete_rows"] = "fail",
) -> None:
    """
    Sauvegarde une liste dans une table.
    Droppe et recrée la table automatiquement (if_exists="replace").
    """
    df = pd.DataFrame([obj.model_dump() for obj in list_objects])
    save_df(df, table_name, if_exists=if_exists)


def save_df(
    df: pd.DataFrame,
    table_name: str,
    if_exists: Literal["fail", "replace", "append", "delete_rows"] = "fail",
) -> None:
    engine = create_engine()
    df.to_sql(name=table_name, con=engine, if_exists=if_exists, index=False)
