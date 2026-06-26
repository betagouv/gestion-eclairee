import datetime
import logging
import os
from decimal import Decimal
from typing import Literal, Type, Union, get_args, get_origin
from uuid import UUID

import sqlalchemy
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import JSONB

import pandas as pd

logger = logging.getLogger(__name__)


def create_engine() -> Engine:
    # Get database URL from environment
    db_url = os.environ.get("DATABASE_URL")
    db_url = db_url.replace("postgres:", "postgresql+psycopg:")

    # Create SQLAlchemy engine
    return sqlalchemy.create_engine(db_url)


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
    dtype = pydantic_model_to_dtype(list_objects[0].__class__) if list_objects else None
    df = pd.DataFrame([obj.model_dump() for obj in list_objects])
    save_df(df, table_name, if_exists=if_exists, dtype=dtype)


def save_df(
    df: pd.DataFrame,
    table_name: str,
    if_exists: Literal["fail", "replace", "append", "delete_rows"] = "fail",
    dtype: dict | None = None,
) -> None:
    engine = create_engine()
    df.to_sql(name=table_name, con=engine, if_exists=if_exists, index=False, dtype=dtype)
    logger.info(f"Saved {df.shape[0]} rows in {table_name}")


def pydantic_model_to_dtype(model_class: Type[BaseModel]) -> dict:
    """Convertit un modèle Pydantic en un dictionnaire de types SQLAlchemy pour `to_sql`.

    Mapping des types :
    - dict -> JSONB
    - datetime.date -> DATE
    - datetime.datetime -> TIMESTAMP
    - datetime.time -> TIME
    - str -> TEXT
    - int -> INTEGER
    - float -> FLOAT
    - bool -> BOOLEAN
    - UUID -> UUID
    - Optional[T] -> T
    - Literal -> TEXT

    Args:
        model_class: Classe Pydantic à convertir en types SQLAlchemy.

    Returns:
        dict: Dictionnaire {nom_champ: type_SQLAlchemy} pour utiliser avec pd.to_sql(dtype=...).
    """

    # Mapping des types Python vers types SQLAlchemy
    type_mapping = {
        str: sqlalchemy.types.TEXT,
        int: sqlalchemy.types.INTEGER,
        float: sqlalchemy.types.FLOAT,
        bool: sqlalchemy.types.BOOLEAN,
        dict: JSONB,
        datetime.date: sqlalchemy.types.DATE,
        datetime.datetime: sqlalchemy.types.TIMESTAMP,
        datetime.time: sqlalchemy.types.TIME,
        UUID: sqlalchemy.types.UUID,
        Decimal: sqlalchemy.types.DECIMAL,
    }

    dtype = {}
    for field_name, annotation in model_class.__annotations__.items():
        origin = get_origin(annotation)

        # Gérer Optional[T] et Union[T, None], prendre le type non-None
        if origin is Union:
            args = get_args(annotation)
            # Vérifier qu'on est pas dans le cas d'un Union de plusieurs types
            if len(args) == 2 and type(None) in args:
                # Prendre le premier type non-None
                non_none_types = [arg for arg in args if arg is not type(None)]
                annotation = non_none_types[0]
            else:
                raise ValueError(f"Unknown annotation {field_name} {annotation}")
        # Pour Literal, mapper vers TEXT
        elif origin is Literal:
            annotation = str

        # Résoudre le type final
        final_type = type_mapping.get(annotation, sqlalchemy.types.TEXT)
        dtype[field_name] = final_type

    return dtype
