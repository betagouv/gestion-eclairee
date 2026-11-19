"""Tests for the SFTP bucket nightly ingestion."""

import io

from django.db import connections
from django.test import override_settings

import pytest
from sqlalchemy import text

import pandas as pd

from gesec.data.pipeline.db import create_engine
from gesec.data.sync.models import SftpIngestState
from gesec.data.sync.sftp_ingest import ingest_sftp, slugify, table_name_for

MOTO_ENDPOINT = "https://s3.testing.beta.gouv.fr"

pytestmark = pytest.mark.django_db(databases=["default", "data"])


@pytest.fixture
def sftp_settings():
    with override_settings(
        SFTP_S3_ENDPOINT_URL=MOTO_ENDPOINT,
        SFTP_S3_REGION_NAME="eu",
        SFTP_S3_ACCESS_KEY_ID="",
        SFTP_S3_SECRET_ACCESS_KEY="",
        SFTP_S3_BUCKET_NAME="test-depec",
    ):
        yield


@pytest.fixture
def clean_db():
    SftpIngestState.objects.all().delete()
    engine = create_engine()
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT tablename FROM pg_tables WHERE tablename LIKE 'sftp_%'"))
        for (name,) in rows:
            conn.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
    yield
    SftpIngestState.objects.all().delete()
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT tablename FROM pg_tables WHERE tablename LIKE 'sftp_%'"))
        for (name,) in rows:
            conn.execute(text(f'DROP TABLE IF EXISTS "{name}"'))


def put_csv(s3_client, key: str, content: str) -> None:
    s3_client.Bucket("test-depec").put_object(Key=key, Body=content.encode("utf-8"))


def put_xlsx(s3_client, key: str, sheets: dict[str, pd.DataFrame]) -> None:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
    buffer.seek(0)
    s3_client.Bucket("test-depec").put_object(Key=key, Body=buffer.read())


def table_rows(table: str) -> list[tuple]:
    engine = create_engine()
    with engine.connect() as conn:
        rows = conn.execute(text(f'SELECT * FROM "{table}" ORDER BY 1')).fetchall()
    return [tuple(row) for row in rows]


def test_slugify():
    assert slugify("Data Brute.CSV") == "data_brute_csv"
    assert slugify("Évolution 2026 !") == "evolution_2026"
    assert slugify("Contrats signés ÇA") == "contrats_signes_ca"


def test_table_name_for():
    assert table_name_for("sous_dossier_rapport_csv") == "sftp_sous_dossier_rapport_csv"
    assert table_name_for("classeur_xlsx", "Feuil 1") == "sftp_classeur_xlsx__feuil_1"


def test_new_csv_creates_table(s3_client, sftp_settings, clean_db):
    put_csv(s3_client, "metabase-t1/data.csv", "a,b\n1,x\n2,y\n")

    stats = ingest_sftp(prefix="metabase-t1/")

    assert stats == {"created": 1, "updated": 0, "skipped": 0, "errors": 0}
    assert [tuple(row) for row in table_rows("sftp_data_csv")] == [(1, "x"), (2, "y")]


def test_unchanged_file_is_skipped(s3_client, sftp_settings, clean_db):
    put_csv(s3_client, "metabase-t2/data.csv", "a\n1\n")
    ingest_sftp(prefix="metabase-t2/")

    stats = ingest_sftp(prefix="metabase-t2/")

    assert stats["skipped"] == 1
    assert stats["created"] == 0


def test_modified_file_recreates_table(s3_client, sftp_settings, clean_db):
    put_csv(s3_client, "metabase-t3/data.csv", "a\n1\n")
    ingest_sftp(prefix="metabase-t3/")
    put_csv(s3_client, "metabase-t3/data.csv", "a\n9\n8\n")

    stats = ingest_sftp(prefix="metabase-t3/")

    assert stats["updated"] == 1
    assert [tuple(row) for row in table_rows("sftp_data_csv")] == [(8,), (9,)]


def test_xlsx_creates_one_table_per_sheet(s3_client, sftp_settings, clean_db):
    put_xlsx(
        s3_client,
        "metabase-t4/classeur.xlsx",
        {"Alpha": pd.DataFrame({"x": [1]}), "Beta 2": pd.DataFrame({"y": [2, 3]})},
    )

    stats = ingest_sftp(prefix="metabase-t4/")

    assert stats["created"] == 1
    assert [tuple(row) for row in table_rows("sftp_classeur_xlsx__alpha")] == [(1,)]
    assert [tuple(row) for row in table_rows("sftp_classeur_xlsx__beta_2")] == [(2,), (3,)]


def test_dry_run_writes_nothing(s3_client, sftp_settings, clean_db):
    put_csv(s3_client, "metabase-t5/data.csv", "a\n1\n")

    stats = ingest_sftp(prefix="metabase-t5/", dry_run=True)

    assert stats["created"] == 1
    with connections["data"].cursor() as cursor:
        cursor.execute("SELECT to_regclass('sftp_data_csv')")
        exists = cursor.fetchone()[0]
    assert exists is None
    assert SftpIngestState.objects.count() == 0


def test_latin1_csv_is_read(s3_client, sftp_settings, clean_db):
    s3_client.Bucket("test-depec").put_object(Key="metabase-t6/data.csv", Body="a\ncafé\n".encode("iso-8859-1"))

    stats = ingest_sftp(prefix="metabase-t6/")

    assert stats["errors"] == 0
    assert [tuple(row) for row in table_rows("sftp_data_csv")] == [("café",)]


def test_colliding_table_names_are_skipped(s3_client, sftp_settings, clean_db):
    put_csv(s3_client, "metabase-t7/rapport.csv", "a\n1\n")
    put_csv(s3_client, "metabase-t7/Rapport.CSV", "a\n2\n")

    stats = ingest_sftp(prefix="metabase-t7/")

    assert stats == {"created": 0, "updated": 0, "skipped": 0, "errors": 2}
    with connections["data"].cursor() as cursor:
        cursor.execute("SELECT to_regclass('sftp_rapport_csv')")
        assert cursor.fetchone()[0] is None
    assert SftpIngestState.objects.count() == 0
