"""Connexion Postgres et table de résultats gold pour gesec.data.classify_gm.

La source est le gold Django (gesec_facture / gesec_facture_ligne) ; les
prédictions sont écrites dans la table dédiée gesec_facture_gm_pred. Le DSN
est dérivé de DATABASE_URL (settings Django) par défaut.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, LiteralString

import psycopg
from psycopg import sql


def get_database_url() -> str:
    url = os.environ.get("CLASSIFY_GM_DATABASE_URL")
    if url:
        return url
    from django.conf import settings

    database = settings.DATABASES["default"]
    if database.get("PASSWORD"):
        auth = f"{database['USER']}:{database['PASSWORD']}"
    else:
        auth = database["USER"]
    host = database["HOST"] or "localhost"
    port = f":{database['PORT']}" if database.get("PORT") else ""
    return f"postgres://{auth}@{host}{port}/{database['NAME']}"


def connect(database_url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(database_url or get_database_url())


@contextmanager
def get_connection(database_url: str | None = None) -> Iterator[psycopg.Connection]:
    conn = connect(database_url)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_result_table(conn: psycopg.Connection, ddl: LiteralString) -> None:
    """Crée la table de résultats si absente (idempotent)."""
    with conn.cursor() as cur:
        cur.execute(sql.SQL(ddl))
    conn.commit()
