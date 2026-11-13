"""Accès à la base de données du pipeline (alias Django "data").

Point d'entrée unique : tous les sous-modules de `gesec.data` (pipeline,
extract_pdf, classify_gm, sync) passent par `get_data_database_url` pour l'URL
et par `get_connection` pour une connexion psycopg.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from urllib.parse import quote

from django.conf import settings

import psycopg


def database_url_from_settings_dict(database: dict[str, Any]) -> str:
    """Construit une URL postgres:// à partir d'une entrée settings.DATABASES."""
    auth = quote(database["USER"] or "", safe="")
    if database.get("PASSWORD"):
        auth = f"{auth}:{quote(database['PASSWORD'], safe='')}"
    host = database["HOST"] or "localhost"
    port = f":{database['PORT']}" if database.get("PORT") else ""
    return f"postgres://{auth}@{host}{port}/{database['NAME']}"


def get_data_database_url() -> str:
    """URL de la base de données du pipeline, lue dans settings.DATABASES["data"]."""
    return database_url_from_settings_dict(settings.DATABASES["data"])


def connect(database_url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(database_url or get_data_database_url())


@contextmanager
def get_connection(database_url: str | None = None) -> Generator[psycopg.Connection, None, None]:
    conn = connect(database_url)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
