"""Ingestion nocturne des fichiers déposés par SFTP dans un bucket S3 dédié.

Chaque fichier CSV/Excel du bucket est copié dans la base `data` sous forme de
table `sftp_<chemin>_<extension>` (une table par onglet `...__<onglet>` pour les
Excel). Le modèle `SftpIngestState` (base applicative) mémorise l'etag et la
date de modification de chaque fichier traité : un fichier inchangé est ignoré,
un fichier nouveau ou modifié voit sa table recréée.
"""

import io
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import TypedDict

from django.conf import settings

import boto3
from sqlalchemy.engine import Engine

import pandas as pd

from gesec.data.pipeline.db import create_engine
from gesec.data.sync.models import SftpIngestState

logger = logging.getLogger(__name__)

FILE_PATTERN = re.compile(r"\.(csv|xlsx?)$", re.IGNORECASE)
TABLE_PREFIX = "sftp"
MAX_IDENTIFIER_LENGTH = 63
CHUNK_SIZE = 1000
CSV_ENCODINGS = ("utf-8-sig", "iso-8859-1")


class SourceFile(TypedDict):
    key: str
    etag: str
    last_modified: datetime
    base: str


def s3_client():
    """Client boto3 dédié au bucket SFTP, construit depuis les settings."""
    if not settings.SFTP_S3_BUCKET_NAME or not settings.SFTP_S3_ENDPOINT_URL:
        raise RuntimeError("SFTP_S3_BUCKET_NAME et SFTP_S3_ENDPOINT_URL doivent être définis")
    return boto3.client(
        "s3",
        endpoint_url=settings.SFTP_S3_ENDPOINT_URL,
        region_name=settings.SFTP_S3_REGION_NAME or None,
        aws_access_key_id=settings.SFTP_S3_ACCESS_KEY_ID or None,
        aws_secret_access_key=settings.SFTP_S3_SECRET_ACCESS_KEY or None,
    )


def slugify(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name.lower())
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_name).strip("_")
    return slug[:MAX_IDENTIFIER_LENGTH].strip("_") or "unnamed"


def table_name_for(base: str, sheet: str | None = None) -> str:
    name = f"{TABLE_PREFIX}_{base}" if sheet is None else f"{TABLE_PREFIX}_{base}__{slugify(sheet)}"
    return name[:MAX_IDENTIFIER_LENGTH]


def list_source_files(client, bucket: str, prefix: str) -> list[SourceFile]:
    files: list[SourceFile] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for entry in page.get("Contents", ()):
            key = entry["Key"]
            if key.endswith("/") or not FILE_PATTERN.search(key):
                continue
            relative = key[len(prefix) :] if key.startswith(prefix) else key
            files.append(
                {
                    "key": key,
                    "etag": entry["ETag"].strip('"'),
                    "last_modified": entry["LastModified"].astimezone(timezone.utc),
                    "base": slugify(relative),
                }
            )
    files.sort(key=lambda f: f["key"])
    return files


def load_state() -> dict[str, tuple[str, datetime]]:
    rows = SftpIngestState.objects.values("path", "etag", "last_modified")
    return {row["path"]: (row["etag"], row["last_modified"]) for row in rows}


def record_state(path: str, etag: str, last_modified: datetime, tables: list[str]) -> None:
    SftpIngestState.objects.update_or_create(
        path=path,
        defaults={"etag": etag, "last_modified": last_modified, "tables": tables},
    )


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [slugify(str(col)) for col in df.columns]
    return df


def read_csv_bytes(buffer: io.BytesIO) -> pd.DataFrame:
    for encoding in CSV_ENCODINGS:
        buffer.seek(0)
        try:
            return pd.read_csv(buffer, encoding=encoding)
        except UnicodeDecodeError:
            continue
    buffer.seek(0)
    return pd.read_csv(buffer, encoding=CSV_ENCODINGS[0])


def ingest_file(client, bucket: str, file: SourceFile, engine: Engine) -> list[str]:
    body = client.get_object(Bucket=bucket, Key=file["key"])["Body"].read()
    buffer = io.BytesIO(body)
    if file["key"].lower().endswith(".csv"):
        sheets = {None: clean_columns(read_csv_bytes(buffer))}
    else:
        sheets = {name: clean_columns(df) for name, df in pd.read_excel(buffer, sheet_name=None).items()}

    tables = []
    for sheet, df in sheets.items():
        table = table_name_for(file["base"], sheet)
        df.to_sql(table, engine, if_exists="replace", index=False, chunksize=CHUNK_SIZE)
        tables.append(table)
        logger.info(f"Table {table} recréée depuis {file['key']}" + (f" onglet {sheet!r}" if sheet else ""))
    return tables


def drop_colliding_files(files: list[SourceFile], stats: dict[str, int]) -> list[SourceFile]:
    by_base: dict[str, list[str]] = {}
    for file in files:
        by_base.setdefault(file["base"], []).append(file["key"])
    kept = []
    for file in files:
        if len(by_base[file["base"]]) > 1:
            logger.error(
                f"Collision de nom de table {TABLE_PREFIX}_{file['base']} entre {by_base[file['base']]}, fichier ignoré"
            )
            stats["errors"] += 1
        else:
            kept.append(file)
    return kept


def ingest_sftp(prefix: str | None = None, dry_run: bool = False) -> dict[str, int]:
    prefix = prefix if prefix is not None else settings.SFTP_INGEST_PREFIX
    client = s3_client()
    bucket = settings.SFTP_S3_BUCKET_NAME
    engine = create_engine()
    state = load_state()

    stats = {"created": 0, "updated": 0, "skipped": 0, "errors": 0}
    files = drop_colliding_files(list_source_files(client, bucket, prefix), stats)
    total = len(files)
    for index, file in enumerate(files, start=1):
        key = file["key"]
        progress = f"[{index}/{total}]"
        fingerprint = (file["etag"], file["last_modified"])
        if state.get(key) == fingerprint:
            logger.info(f"{progress} {key}: inchangé, ignoré")
            stats["skipped"] += 1
            continue
        action = "updated" if key in state else "created"
        if dry_run:
            logger.info(f"{progress} [dry-run] {action} {key}")
            stats[action] += 1
            continue
        logger.info(f"{progress} {key}: début du traitement ({action})")
        try:
            tables = ingest_file(client, bucket, file, engine)
            record_state(key, file["etag"], file["last_modified"], tables)
            stats[action] += 1
            logger.info(f"{progress} {key}: traitement terminé ({len(tables)} table(s), {action})")
        except Exception:
            logger.exception(f"{progress} {key}: échec du traitement")
            stats["errors"] += 1
    logger.info(f"Ingestion SFTP terminée: {stats}")
    return stats
