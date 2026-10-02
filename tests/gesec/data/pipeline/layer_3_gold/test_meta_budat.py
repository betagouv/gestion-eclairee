import logging
from datetime import date
from decimal import Decimal
from typing import Any, Iterator, Sequence

from django.conf import settings

import pytest
import sqlalchemy
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.engine import URL

import pandas as pd

from gesec.data.pipeline.db import pydantic_model_to_dtype
from gesec.data.pipeline.layer_1_bronze.schemas import BronzeBudatExportAugdt
from gesec.data.pipeline.layer_2_silver.schemas import SilverService
from gesec.data.pipeline.layer_3_gold.constants import UGAP_SIREN
from gesec.data.pipeline.layer_3_gold.meta_budat import TABLE_NAME, process_to_gold
from gesec.data.pipeline.layer_3_gold.schemas import GoldCproExportFactureLigne
from gesec.models import Facture

pytestmark = pytest.mark.django_db(transaction=True)

RAW_TABLES = ["bronze_budat_export_augdt", "silver_services", "gesec_facture_ligne", TABLE_NAME]


def build_engine() -> Engine:
    database = settings.DATABASES["default"]
    url = URL.create(
        "postgresql+psycopg",
        username=database["USER"] or None,
        password=database["PASSWORD"] or None,
        host=database["HOST"] or None,
        port=database["PORT"] or None,
        database=database["NAME"],
    )
    return sqlalchemy.create_engine(url)


def drop_raw_tables(engine: Engine) -> None:
    with engine.begin() as conn:
        for table in RAW_TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))


@pytest.fixture
def engine() -> Iterator[Engine]:
    test_engine = build_engine()
    drop_raw_tables(test_engine)
    create_empty_table(test_engine, "gesec_facture_ligne", GoldCproExportFactureLigne)
    yield test_engine
    drop_raw_tables(test_engine)
    test_engine.dispose()


def create_empty_table(engine: Engine, table_name: str, model_class: type[BaseModel]) -> None:
    dtype = pydantic_model_to_dtype(model_class)
    pd.DataFrame(columns=list(dtype)).to_sql(table_name, con=engine, if_exists="replace", index=False, dtype=dtype)


def save_rows(engine: Engine, table_name: str, rows: Sequence[BaseModel]) -> None:
    dtype = pydantic_model_to_dtype(rows[0].__class__)
    df = pd.DataFrame([row.model_dump() for row in rows])
    df.to_sql(table_name, con=engine, if_exists="replace", index=False, dtype=dtype, chunksize=1000)


def budat_row(
    source_idx: int,
    facture_ref: str,
    montant: str = "100,00",
    service: str = "SEDP1",
    gm: str = "",
    facture_date: str = "20250312",
    date_payment: str = "",
) -> BronzeBudatExportAugdt:
    return BronzeBudatExportAugdt(
        source="budat/export.csv",
        source_idx=source_idx,
        annee="2025",
        facture="",
        facture_ref=facture_ref,
        facture_date=facture_date,
        facture_montant=montant,
        date_payment=date_payment,
        ej="EJ1",
        marche="",
        seej="",
        gm=gm,
        libelle="Libellé",
        fournisseur="Fournisseur BUDAT",
        fournisseur_siren="111111111",
        facture_fi="",
        societe="",
        service=service,
        cc="",
        pce="",
        txt50="",
        activite="",
        description="",
    )


def create_facture(
    numero: str,
    id_cpro: str,
    fournisseur_identifiant: str = "123456789",
    gm: str | None = None,
    ministere: str = "INCONNU",
) -> Facture:
    return Facture.objects.create(
        source="cpro/exports/f.csv",
        source_idx=Facture.objects.count() + 1,
        identifiant_chorus_pro=id_cpro,
        numero=numero,
        date_etat_courant=date(2025, 1, 1),
        date_modification=date(2025, 1, 1),
        mt_ht=Decimal("100"),
        mt_ttc=Decimal("120"),
        montant_tva=Decimal("20"),
        montant_a_payer=Decimal("120"),
        fournisseur_type_d_identifiant="SIREN",
        fournisseur_identifiant=fournisseur_identifiant,
        fournisseur_designation="Fournisseur",
        destinataire_code_service="SERVICE",
        destinataire_service="Service",
        devise_de_la_facture="EUR",
        numero_du_bon_de_commande="BC",
        numero_de_marche="MARCHE",
        gm=gm,
        ministere=ministere,
    )


def gold_line(
    id_cpro: str,
    line_id: str,
    amount_incl_tax: str,
    fournisseur_in_fine_designation: str | None = None,
    fournisseur_in_fine_siren: str | None = None,
) -> GoldCproExportFactureLigne:
    return GoldCproExportFactureLigne(
        id_cpro=id_cpro,
        source="facture-xml",
        xml_schema="UBL-Invoice-2",
        line_id=line_id,
        item_name="Article",
        item_description="Description",
        item_reference=f"ART-{line_id}",
        quantity=Decimal("1"),
        quantity_unit_code="C62",
        unit_price=Decimal(amount_incl_tax),
        line_amount_excl_tax=Decimal(amount_incl_tax),
        line_amount_incl_tax=Decimal(amount_incl_tax),
        line_amount_vat=Decimal("0"),
        currency="EUR",
        fournisseur_in_fine_designation=fournisseur_in_fine_designation,
        fournisseur_in_fine_siren=fournisseur_in_fine_siren,
    )


def fetch_meta(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        result = conn.execute(
            text(f"""
                SELECT source_idx, cas, montant, montant_ligne_ttc, segment, ministere, service,
                       facture_date_str, facture_date, date_payment_str, date_payment,
                       fournisseur_in_fine_designation, fournisseur_in_fine_siren
                FROM {TABLE_NAME}
                ORDER BY source_idx, line_id
            """)
        )
        return [dict(row._mapping) for row in result]


def test_repli_budat_sur_les_lignes_non_rapprochees(engine: Engine) -> None:
    save_rows(engine, "silver_services", [SilverService(code="SEDP1", name="Service 1", ministere="INTERIEUR")])
    create_facture(numero="456", id_cpro="cpro-sans-lignes", gm="33.02.01", ministere="FINANCES")
    save_rows(
        engine,
        "bronze_budat_export_augdt",
        [
            budat_row(1, "123", montant="100,00", gm="33.01.04", facture_date="20250312"),
            budat_row(2, "456", montant="50,00", gm="33.99.99"),
        ],
    )

    process_to_gold(engine=engine)

    rows = fetch_meta(engine)
    assert len(rows) == 2

    facture_absente = rows[0]
    assert facture_absente["cas"] == "facture_absente"
    assert facture_absente["montant"] == Decimal("100.00")
    assert facture_absente["montant_ligne_ttc"] is None
    assert facture_absente["segment"] == "33.01"
    assert facture_absente["ministere"] == "INTERIEUR"
    assert facture_absente["service"] == "SEDP1"
    assert facture_absente["facture_date_str"] == "20250312"
    assert facture_absente["facture_date"] == date(2025, 3, 12)
    assert facture_absente["date_payment_str"] == ""
    assert facture_absente["date_payment"] is None

    facture_sans_lignes = rows[1]
    assert facture_sans_lignes["cas"] == "facture_sans_lignes"
    assert facture_sans_lignes["montant"] == Decimal("50.00")
    assert facture_sans_lignes["segment"] == "33.02.01"
    assert facture_sans_lignes["ministere"] == "FINANCES"
    assert facture_sans_lignes["service"] == "SERVICE"


def test_eclatement_prorata_et_fournisseur_in_fine(engine: Engine) -> None:
    save_rows(engine, "silver_services", [SilverService(code="SEDP1", name="Service 1", ministere="INTERIEUR")])
    create_facture(numero="789", id_cpro="cpro-non-ugap", gm="33.04.01", ministere="ECOLOGIE")
    create_facture(numero="790", id_cpro="cpro-ugap", fournisseur_identifiant=f"{UGAP_SIREN}0001")
    create_facture(numero="791", id_cpro="cpro-total-nul")
    save_rows(
        engine,
        "gesec_facture_ligne",
        [
            gold_line("cpro-non-ugap", "00010", "30.00"),
            gold_line("cpro-non-ugap", "00020", "90.00"),
            gold_line("cpro-ugap", "00010", "60.00", "EDITEUR", "222222222"),
            gold_line("cpro-ugap", "00020", "60.00"),
            gold_line("cpro-total-nul", "00010", "0.00"),
            gold_line("cpro-total-nul", "00020", "0.00"),
        ],
    )
    save_rows(
        engine,
        "bronze_budat_export_augdt",
        [
            budat_row(1, "0789", montant="60,00"),
            budat_row(2, "0790", montant="100,00"),
            budat_row(3, "0791", montant="10,00"),
        ],
    )

    process_to_gold(engine=engine)

    rows = fetch_meta(engine)
    assert len(rows) == 6

    non_ugap = [row for row in rows if row["source_idx"] == 1]
    assert [row["cas"] for row in non_ugap] == ["lignes_non_ugap", "lignes_non_ugap"]
    assert [row["montant"] for row in non_ugap] == [Decimal("15.00"), Decimal("45.00")]
    assert [row["montant_ligne_ttc"] for row in non_ugap] == [Decimal("30.00"), Decimal("90.00")]

    ugap = [row for row in rows if row["source_idx"] == 2]
    assert [row["cas"] for row in ugap] == [
        "lignes_ugap_avec_fournisseur_in_fine",
        "lignes_ugap_sans_fournisseur_in_fine",
    ]
    assert [row["montant"] for row in ugap] == [Decimal("50.00"), Decimal("50.00")]
    assert ugap[0]["fournisseur_in_fine_designation"] == "EDITEUR"
    assert ugap[0]["fournisseur_in_fine_siren"] == "222222222"

    total_nul = [row for row in rows if row["source_idx"] == 3]
    assert [row["cas"] for row in total_nul] == ["lignes_non_ugap", "lignes_non_ugap"]
    assert [row["montant"] for row in total_nul] == [Decimal("5.00"), Decimal("5.00")]


def test_dates_parsee_et_non_parsee(engine: Engine, caplog: pytest.LogCaptureFixture) -> None:
    save_rows(engine, "silver_services", [SilverService(code="SEDP1", name="Service 1", ministere="INTERIEUR")])
    save_rows(
        engine,
        "bronze_budat_export_augdt",
        [
            budat_row(1, "001", facture_date="20250201", date_payment="20250304"),
            budat_row(2, "002", facture_date="invalide", date_payment=""),
        ],
    )

    with caplog.at_level(logging.WARNING):
        process_to_gold(engine=engine)

    rows = fetch_meta(engine)
    assert rows[0]["facture_date_str"] == "20250201"
    assert rows[0]["facture_date"] == date(2025, 2, 1)
    assert rows[0]["date_payment_str"] == "20250304"
    assert rows[0]["date_payment"] == date(2025, 3, 4)
    assert rows[1]["facture_date_str"] == "invalide"
    assert rows[1]["facture_date"] is None
    assert rows[1]["date_payment_str"] == ""
    assert rows[1]["date_payment"] is None
    assert any("dates non parsées" in message for message in caplog.messages)
