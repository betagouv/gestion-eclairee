from datetime import date, datetime
from decimal import Decimal
from typing import Any

from gesec.data.pipeline.layer_1_bronze.schemas import BronzeUgapExportFacture
from gesec.data.pipeline.layer_2_silver.ugap_export_factures import (
    DEFAULT_TABLE_NAME,
    to_date,
    to_decimal,
    to_text,
    transform_bronze_row,
    transform_bronze_to_silver,
)
from gesec.data.pipeline.utils import cell_to_text
from tests.gesec.data.pipeline.ugap_helpers import ugap_row


def bronze_row(
    source_idx: str = "11_2025_dinum_0",
    source: str = "ugap/f.xlsx",
    onglet: str = "11 2025 - Dinum",
    **overrides: Any,
) -> BronzeUgapExportFacture:
    return BronzeUgapExportFacture(
        **{header: cell_to_text(value) for header, value in ugap_row(**overrides).items()},
        source=source,
        source_idx=source_idx,
        onglet=onglet,
    )


def test_default_table_name():
    assert DEFAULT_TABLE_NAME == "silver_ugap_export_factures"


def test_transform_bronze_row_types_and_dates():
    overrides: dict[str, Any] = {
        "Cde client - Jour de création": "10/04/2025",
        "Cde client - Date Paiement client": datetime(2025, 11, 6),
        "CE HT": 5.94,
        "TVA Collectée": 1.19,
        "CE TTC": 7.13,
        "Qté commandées": 0.27,
        "Montant Facturé HT": 12.34,
        "Article - N°": 5650607,
    }
    row = transform_bronze_row(bronze_row(**overrides))

    assert row.cde_client_jour_de_creation == date(2025, 4, 10)
    assert row.cde_client_date_paiement_client == date(2025, 11, 6)
    assert row.ce_ht == Decimal("5.94")
    assert row.tva_collectee == Decimal("1.19")
    assert row.ce_ttc == Decimal("7.13")
    assert row.qte_commandees == Decimal("0.27")
    assert row.montant_facture_ht == Decimal("12.34")
    assert row.article_ndeg == "5650607"
    assert row.cde_client_ndeg == "104521399"
    assert row.line_id == 0


def test_to_text_sentinels_and_types():
    assert to_text(None) is None
    assert to_text("-") is None
    assert to_text("  # ") is None
    assert to_text("   ") is None
    assert to_text("  Titulaire  ") == "Titulaire"
    assert to_text(343059564) == "343059564"
    assert to_text(5650607.0) == "5650607"


def test_to_date_sentinels_and_errors():
    assert to_date(None) is None
    assert to_date("-") is None
    assert to_date("10/04/2025") == date(2025, 4, 10)
    assert to_date("2025-04-10") == date(2025, 4, 10)
    assert to_date("2025-04-10T00:00:00") == date(2025, 4, 10)
    assert to_date(datetime(2025, 4, 10, 12, 30)) == date(2025, 4, 10)
    assert to_date(date(2025, 4, 10)) == date(2025, 4, 10)


def test_to_decimal_sentinels_and_errors():
    assert to_decimal(None) is None
    assert to_decimal("#") is None
    assert to_decimal(0) == Decimal("0")
    assert to_decimal("12,34") == Decimal("12.34")


def test_transform_siren_is_stripped():
    overrides: dict[str, Any] = {
        "SIREN": 180092447,
        "SIREN Titulaire": " 343059564 ",
        "Siren Titulaire 2": "-",
    }
    row = transform_bronze_row(bronze_row(**overrides))

    assert row.siren == "180092447"
    assert row.siren_titulaire == "343059564"
    assert row.siren_titulaire_2 == ""


def test_transform_empty_texts_become_empty_strings():
    overrides: dict[str, Any] = {
        "Part.: nom 2 organ.": "#",
        "SAE Niveau 4": None,
        "Type d'offre Logiciels": "-",
        "Titulaire 2 (Editeurs Multi Editeurs)": "  ",
    }
    row = transform_bronze_row(bronze_row(**overrides))

    assert row.part_nom_2_organ == ""
    assert row.sae_niveau_4 == ""
    assert row.type_d_offre_logiciels == ""
    assert row.titulaire_2_editeurs_multi_editeurs == ""


def test_transform_bronze_to_silver_rejects_missing_keys():
    missing_article: dict[str, Any] = {"Article - N°": None}
    rows, statuses = transform_bronze_to_silver(
        [
            bronze_row(source_idx="a", **{"Cde Client - N°": "#"}),
            bronze_row(source_idx="b", **missing_article),
            bronze_row(source_idx="c"),
        ]
    )

    assert [row.source_idx for row in rows] == ["c"]
    status_by_idx = {status.source_idx: status for status in statuses}
    assert status_by_idx["a"].status == "Validation error"
    assert status_by_idx["b"].status == "Validation error"
    assert status_by_idx["c"].status == "Ok"


def test_transform_bronze_to_silver_rejects_invalid_types():
    rows, statuses = transform_bronze_to_silver([bronze_row(**{"Cde client - Jour de création": "not a date"})])

    assert rows == []
    assert statuses[0].status == "Validation error"
    assert "date" in (statuses[0].status_details or "")


def test_deduplicate_keeps_most_recent_payment_date():
    rows, statuses = transform_bronze_to_silver(
        [
            bronze_row(
                source_idx="old",
                **{
                    "Cde client - Date Paiement client": "01/01/2025",
                    "Cde client - Jour de création": "01/01/2024",
                },
            ),
            bronze_row(
                source_idx="new",
                **{
                    "Cde client - Date Paiement client": "01/01/2026",
                    "Cde client - Jour de création": "01/01/2024",
                },
            ),
        ]
    )

    assert [row.source_idx for row in rows] == ["new"]
    status_by_idx = {status.source_idx: status for status in statuses}
    assert status_by_idx["new"].status == "Ok"
    assert status_by_idx["old"].status == "Duplicat"


def test_deduplicate_keeps_most_recent_creation_day():
    rows, _statuses = transform_bronze_to_silver(
        [
            bronze_row(
                source_idx="old",
                **{
                    "Cde client - Date Paiement client": "01/01/2025",
                    "Cde client - Jour de création": "01/01/2024",
                },
            ),
            bronze_row(
                source_idx="new",
                **{
                    "Cde client - Date Paiement client": "01/01/2025",
                    "Cde client - Jour de création": "01/01/2026",
                },
            ),
        ]
    )

    assert [row.source_idx for row in rows] == ["new"]


def test_deduplicate_tie_break_on_ingestion_order():
    rows, statuses = transform_bronze_to_silver(
        [
            bronze_row(source_idx="first", source="ugap/a.xlsx"),
            bronze_row(source_idx="second", source="ugap/b.xlsx"),
        ]
    )

    assert [row.source_idx for row in rows] == ["second"]
    status_by_idx = {status.source_idx: status for status in statuses}
    assert status_by_idx["first"].status == "Duplicat"
    assert status_by_idx["second"].status == "Ok"


def test_line_ids_are_assigned_per_facture_after_deduplication():
    cells_a1: dict[str, Any] = {"Cde Client - N°": "A", "Article - N°": 1}
    cells_b1: dict[str, Any] = {"Cde Client - N°": "B", "Article - N°": 2}
    cells_a2: dict[str, Any] = {"Cde Client - N°": "A", "Article - N°": 3}
    cells_a1_old: dict[str, Any] = {
        "Cde Client - N°": "A",
        "Article - N°": 1,
        "Cde client - Date Paiement client": "01/01/2020",
    }
    rows, _statuses = transform_bronze_to_silver(
        [
            bronze_row(source_idx="a1", **cells_a1),
            bronze_row(source_idx="b1", **cells_b1),
            bronze_row(source_idx="a2", **cells_a2),
            bronze_row(source_idx="a1_old", **cells_a1_old),
        ]
    )

    assert [(row.cde_client_ndeg, row.article_ndeg, row.line_id) for row in rows] == [
        ("A", "1", 1),
        ("B", "2", 1),
        ("A", "3", 2),
    ]
