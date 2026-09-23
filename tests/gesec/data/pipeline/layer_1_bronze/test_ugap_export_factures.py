from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from gesec.data.pipeline.layer_1_bronze.schemas import BronzeUgapExportFacture
from gesec.data.pipeline.layer_1_bronze.ugap_export_factures import (
    DEFAULT_TABLE_NAME,
    DINUM_SHEET_PATTERN,
    list_xlsx_files,
    process_files_to_bronze,
)
from gesec.data.pipeline.layer_1_bronze.utils import clean_column_name
from gesec.data.pipeline.utils import load_xlsx, model_headers
from tests.gesec.data.pipeline.ugap_helpers import UGAP_HEADERS, build_ugap_xlsx, ugap_row


def put_file(s3_client, key: str, body: bytes) -> None:
    s3_client.Bucket("test-depec").put_object(Key=key, Body=body)


def load_bronze(filepath: str) -> list[BronzeUgapExportFacture]:
    return load_xlsx(
        filepath,
        BronzeUgapExportFacture,
        DINUM_SHEET_PATTERN,
        source_key=clean_column_name,
    )


@pytest.fixture
def ugap_file(s3_client) -> str:
    key = "ugap/exports/2026_08_24_DINUM_DAE_10_lignes.xlsx"
    put_file(
        s3_client,
        key,
        build_ugap_xlsx(
            {
                "11 2025 - Dinum": [ugap_row(), ugap_row(**{"Article - N°": 5650760})],
                "11 2025 - DAE": [ugap_row(**{"Cde Client - N°": 999})],
            }
        ),
    )
    return key


def test_default_table_name():
    assert DEFAULT_TABLE_NAME == "bronze_ugap_export_factures"


def test_model_headers_match_ugap_sample():
    assert model_headers(BronzeUgapExportFacture) == UGAP_HEADERS
    assert len(UGAP_HEADERS) == 44


def test_list_xlsx_files_missing_directory(s3_client):
    assert list_xlsx_files("ugap_missing") == []


def test_list_xlsx_files_keeps_only_sorted_xlsx(s3_client):
    put_file(s3_client, "ugap/exports/b.xlsx", b"")
    put_file(s3_client, "ugap/exports/a.xlsx", b"")
    put_file(s3_client, "ugap/exports/c.csv", b"")

    assert list_xlsx_files("ugap/exports") == ["ugap/exports/a.xlsx", "ugap/exports/b.xlsx"]


def test_load_bronze_selects_dinum_sheets_only(s3_client, ugap_file):
    rows = load_bronze(ugap_file)

    assert len(rows) == 2
    assert {row.onglet for row in rows} == {"11 2025 - Dinum"}
    assert all(row.source == ugap_file for row in rows)
    assert [row.source_idx for row in rows] == ["11_2025_dinum_0", "11_2025_dinum_1"]
    assert rows[0].source_idx.startswith(clean_column_name("11 2025 - Dinum"))


def test_load_bronze_keeps_raw_text(s3_client, ugap_file):
    row = load_bronze(ugap_file)[0]

    assert row.cde_client_numero == "104521399"
    assert row.article_numero == "5650607"
    assert row.part_nom_2_organ == "#"
    assert row.type_d_offre_logiciels == "-"
    assert row.article_code_fourniseur == "SOC FRANCAISE DU RADIOTELEPHONE - S"


def test_load_bronze_parses_amounts_as_decimal(s3_client, ugap_file):
    row = load_bronze(ugap_file)[0]

    assert row.ce_ht == Decimal("5.94")
    assert row.tva_collectee == Decimal("1.19")
    assert row.ce_ttc == Decimal("7.13")
    assert row.qte_commandees == Decimal("1")
    assert row.montant_facture_ht == Decimal("5.94")


@pytest.mark.parametrize("value", ["abc", None])
def test_load_bronze_raises_on_invalid_amount(s3_client, value):
    key = "ugap/exports/invalid_amount.xlsx"
    put_file(s3_client, key, build_ugap_xlsx({"Dinum": [ugap_row(**{"CE HT": value})]}))

    with pytest.raises(ValidationError):
        load_bronze(key)


def test_load_bronze_turns_empty_cells_into_empty_strings(s3_client):
    key = "ugap/exports/empty.xlsx"
    put_file(s3_client, key, build_ugap_xlsx({"Dinum": [ugap_row(**{"SAE Niveau 4": None})]}))

    row = load_bronze(key)[0]

    assert row.sae_niveau_4 == ""


def test_load_bronze_converts_datetimes_to_iso(s3_client):
    key = "ugap/exports/dates.xlsx"
    put_file(
        s3_client,
        key,
        build_ugap_xlsx(
            {
                "Dinum": [
                    ugap_row(
                        **{
                            "Cde client - Jour de création": datetime(2025, 4, 10),
                            "Cde client - Date Paiement client": date(2025, 11, 6),
                        }
                    )
                ]
            }
        ),
    )

    row = load_bronze(key)[0]

    assert row.cde_client_jour_de_creation in ("2025-04-10", "2025-04-10T00:00:00")
    assert row.cde_client_date_paiement_client in ("2025-11-06", "2025-11-06T00:00:00")


def test_load_bronze_raises_without_dinum_sheet(s3_client):
    key = "ugap/exports/dae_only.xlsx"
    put_file(s3_client, key, build_ugap_xlsx({"11 2025 - DAE": [ugap_row()]}))

    with pytest.raises(ValueError, match="No sheet matching"):
        load_bronze(key)


def test_process_files_to_bronze_skips_missing_directory(s3_client):
    process_files_to_bronze("ugap_missing", table_name="bronze_ugap_unused")
