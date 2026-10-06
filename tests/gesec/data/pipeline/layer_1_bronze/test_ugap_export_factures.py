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
        skip_rows=0,
        source_key=clean_column_name,
    )


@pytest.fixture
def ugap_file(s3_client) -> str:
    key = "ugap/exports/2026_10_01.xlsx"
    put_file(
        s3_client,
        key,
        build_ugap_xlsx(
            {
                "Dinum 2025": [ugap_row(), ugap_row(**{"Code Article UGAP": 899638})],
                "Dinum janv sept 2026": [ugap_row(**{"Numéro de commande UGAP": 103858991})],
                "DAE 2025": [ugap_row(**{"Numéro de commande UGAP": 999})],
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


def test_load_bronze_imports_all_dinum_sheets(s3_client, ugap_file):
    rows = load_bronze(ugap_file)

    assert len(rows) == 3
    assert {row.onglet for row in rows} == {"Dinum 2025", "Dinum janv sept 2026"}
    assert all(row.source == ugap_file for row in rows)
    assert [row.source_idx for row in rows] == ["dinum_2025_0", "dinum_2025_1", "dinum_janv_sept_2026_0"]
    assert rows[0].source_idx.startswith(clean_column_name("Dinum 2025"))
    assert rows[2].source_idx.startswith(clean_column_name("Dinum janv sept 2026"))


def test_load_bronze_keeps_raw_text(s3_client, ugap_file):
    row = load_bronze(ugap_file)[0]

    assert row.numero_commande_ugap == "103858990"
    assert row.numero_facture == "7004133026"
    assert row.code_article_ugap == "899637"
    assert row.part_nom_2_organ == "#"
    assert row.type_offre_logicielle == "Multi Editeurs"
    assert row.designation_titulaire_marche == "SCC FRANCE"


def test_load_bronze_maps_swapped_siren_columns(s3_client, ugap_file):
    row = load_bronze(ugap_file)[0]

    assert row.siren_titulaire_2 == "410117303"
    assert row.type_ent_titulaire_2 == "PME"


def test_load_bronze_parses_amounts_as_decimal(s3_client, ugap_file):
    row = load_bronze(ugap_file)[0]

    assert row.ce_ht == Decimal("5.94")
    assert row.tva == Decimal("1.19")
    assert row.ce_ttc == Decimal("7.13")
    assert row.qte_article_commandee == Decimal("1")
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
                            "Jour de création de la commande UGAP": datetime(2025, 4, 10),
                            "Jour de paiement de la commande UGAP": date(2025, 11, 6),
                        }
                    )
                ],
            }
        ),
    )

    row = load_bronze(key)[0]

    assert row.jour_creation_commande_ugap in ("2025-04-10", "2025-04-10T00:00:00")
    assert row.jour_paiement_commande_ugap in ("2025-11-06", "2025-11-06T00:00:00")


def test_load_bronze_raises_without_dinum_sheet(s3_client):
    key = "ugap/exports/dae_only.xlsx"
    put_file(s3_client, key, build_ugap_xlsx({"DAE 2025": [ugap_row()]}))

    with pytest.raises(ValueError, match="No sheet matching"):
        load_bronze(key)


def test_process_files_to_bronze_skips_missing_directory(s3_client):
    process_files_to_bronze("ugap_missing", table_name="bronze_ugap_unused")
