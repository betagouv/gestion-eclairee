from datetime import date, datetime
from decimal import Decimal
from typing import Any

from gesec.data.pipeline.layer_1_bronze.schemas import BronzeUgapExportFacture
from gesec.data.pipeline.layer_2_silver.ugap_export_factures import (
    DEFAULT_TABLE_NAME,
    _status,
    deduplicate,
    parse_bronze_row,
    to_date,
    to_decimal,
    to_text,
    transform_bronze_row,
)
from gesec.data.pipeline.utils import cell_to_text
from tests.gesec.data.pipeline.ugap_helpers import ugap_row


def bronze_row(
    source_idx: str = "dinum_2025_0",
    source: str = "ugap/f.xlsx",
    onglet: str = "Dinum 2025",
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
        "Jour de création de la commande UGAP": "10/04/2025",
        "Jour de paiement de la commande UGAP": datetime(2025, 11, 6),
        "CE HT": 5.94,
        "TVA": 1.19,
        "CE TTC": 7.13,
        "Qté Article commandée": 0.27,
        "Montant Facturé HT": 12.34,
        "Code Article UGAP": 5650607,
    }
    row = transform_bronze_row(bronze_row(**overrides))

    assert row.jour_creation_commande_ugap == date(2025, 4, 10)
    assert row.jour_paiement_commande_ugap == date(2025, 11, 6)
    assert row.ce_ht == Decimal("5.94")
    assert row.tva == Decimal("1.19")
    assert row.ce_ttc == Decimal("7.13")
    assert row.qte_article_commandee == Decimal("0.27")
    assert row.montant_facture_ht == Decimal("12.34")
    assert row.code_article_ugap == "5650607"
    assert row.numero_commande_ugap == "103858990"
    assert row.numero_facture == "7004133026"


def test_to_text_sentinels_and_types():
    assert to_text(None) is None
    assert to_text("-") is None
    assert to_text("  # ") is None
    assert to_text("#N/A") is None
    assert to_text("N/A") is None
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
        "Siren Titultaire 1": " 424982650 ",
        "Type ent Titulaire 2": "-",
    }
    row = transform_bronze_row(bronze_row(**overrides))

    assert row.siren == "180092447"
    assert row.siren_titulaire_1 == "424982650"
    assert row.siren_titulaire_2 == ""


def test_transform_maps_swapped_siren_columns():
    row = transform_bronze_row(bronze_row())

    assert row.type_ent_titulaire_2 == "PME"
    assert row.siren_titulaire_2 == "410117303"


def test_transform_empty_texts_become_empty_strings():
    overrides: dict[str, Any] = {
        "Part.: nom 2 organ.": "#",
        "SAE Niveau 4": None,
        "Type offre logicielle": "#N/A",
        "Constructeur de l'article": 0,
        "Titulaire de rang 2 (Marche Multi Editeurs)": "  ",
    }
    row = transform_bronze_row(bronze_row(**overrides))

    assert row.part_nom_2_organ == ""
    assert row.sae_niveau_4 == ""
    assert row.type_offre_logicielle == ""
    assert row.constructeur_article == ""
    assert row.titulaire_rang_2 == ""


def test_parse_bronze_row_rejects_invalid_types():
    entry = parse_bronze_row(bronze_row(**{"Jour de création de la commande UGAP": "not a date"}))

    assert entry.silver is None
    assert entry.error
    assert _status(entry) == "Validation error"


def test_parse_bronze_row_keeps_valid_row():
    entry = parse_bronze_row(bronze_row(source_idx="a"))

    assert entry.silver is not None
    assert entry.error is None
    assert _status(entry) == "Ok"


def test_deduplicate_keeps_distinct_payments():
    early: dict[str, Any] = {"Jour de paiement de la commande UGAP": "01/01/2025"}
    late: dict[str, Any] = {"Jour de paiement de la commande UGAP": "01/01/2026"}
    parsed = [
        parse_bronze_row(bronze_row(source_idx="p1", **early)),
        parse_bronze_row(bronze_row(source_idx="p2", **late)),
    ]

    assert deduplicate(parsed) == 0
    assert {_status(entry) for entry in parsed} == {"Ok"}


def test_deduplicate_keeps_distinct_amounts():
    partial: dict[str, Any] = {"Montant Facturé HT": 100}
    full: dict[str, Any] = {"Montant Facturé HT": 200}
    parsed = [
        parse_bronze_row(bronze_row(source_idx="a_partial", **partial)),
        parse_bronze_row(bronze_row(source_idx="b_full", **full)),
    ]

    assert deduplicate(parsed) == 0
    assert {_status(entry) for entry in parsed} == {"Ok"}


def test_deduplicate_same_payment_ignores_creation_day():
    first: dict[str, Any] = {
        "Jour de paiement de la commande UGAP": "01/01/2025",
        "Jour de création de la commande UGAP": "01/01/2024",
    }
    second: dict[str, Any] = {
        "Jour de paiement de la commande UGAP": "01/01/2025",
        "Jour de création de la commande UGAP": "01/01/2026",
    }
    parsed = [
        parse_bronze_row(bronze_row(source_idx="a_first", **first)),
        parse_bronze_row(bronze_row(source_idx="b_second", **second)),
    ]

    assert deduplicate(parsed) == 1
    status_by_idx = {entry.source_idx: _status(entry) for entry in parsed}
    assert status_by_idx["b_second"] == "Ok"
    assert status_by_idx["a_first"] == "Duplicat"


def test_deduplicate_last_sorted_wins():
    parsed = [
        parse_bronze_row(bronze_row(source_idx="second", source="ugap/b.xlsx")),
        parse_bronze_row(bronze_row(source_idx="first", source="ugap/a.xlsx")),
    ]

    assert deduplicate(parsed) == 1
    status_by_idx = {entry.source_idx: _status(entry) for entry in parsed}
    assert status_by_idx["second"] == "Ok"
    assert status_by_idx["first"] == "Duplicat"
