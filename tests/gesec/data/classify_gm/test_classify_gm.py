from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

import psycopg
import pytest
from psycopg import sql

from gesec.data.classify_gm.classify import read_identifiants_csv
from gesec.data.classify_gm.classify_hierarchy import run_classify_hierarchical
from gesec.data.classify_gm.db import get_database_url
from gesec.data.classify_gm.gold import TABLE_NAME
from gesec.data.classify_gm.llm import LLMAskResult
from gesec.data.classify_gm.paths import load_ddl
from gesec.models import Facture

pytestmark = pytest.mark.django_db(transaction=True)


class FakeLLM:
    """Répond domaine=33, segment=33.02, feuille=33.02.05 sans appel réseau."""

    def __init__(self) -> None:
        self.calls = 0

    def ask_llm(
        self, messages: list[dict], model: str, response_format: dict | None = None, **kwargs: Any
    ) -> LLMAskResult:
        assert response_format is not None
        field = response_format["json_schema"]["name"].removeprefix("GmHierarchy_")
        self.calls += 1
        choices = {"domaine": "33", "segment": "33.02", "gm_pred": "33.02.05"}
        return LLMAskResult(content={field: choices[field], "raison": "test"})


_LIGNE_DDL = """
CREATE TABLE IF NOT EXISTS gesec_facture_ligne (
    id BIGSERIAL PRIMARY KEY,
    id_cpro TEXT NOT NULL,
    source TEXT,
    xml_schema TEXT,
    line_id TEXT,
    item_name TEXT,
    item_description TEXT,
    item_reference TEXT,
    quantity NUMERIC,
    quantity_unit_code TEXT,
    unit_price NUMERIC,
    line_amount_excl_tax NUMERIC,
    line_amount_incl_tax NUMERIC,
    line_amount_vat NUMERIC,
    currency TEXT,
    fournisseur_in_fine_designation TEXT,
    fournisseur_in_fine_siren TEXT
)
"""


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    connection = psycopg.connect(get_database_url())
    with connection.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(TABLE_NAME)))
        cur.execute(load_ddl())
        cur.execute(_LIGNE_DDL)
    connection.commit()
    yield connection
    with connection.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(TABLE_NAME)))
        cur.execute("DROP TABLE IF EXISTS gesec_facture_ligne")
    connection.commit()
    connection.close()


def create_facture(
    id_cpro: str,
    *,
    ministere: str = "FINANCES",
    date_etat_courant: date = date(2025, 1, 1),
    gm: str | None = "33.02",
) -> Facture:
    facture = Facture.objects.create(
        source="cpro/exports/f.csv",
        source_idx=Facture.objects.count() + 1,
        identifiant_chorus_pro=id_cpro,
        numero=id_cpro,
        date_etat_courant=date_etat_courant,
        date_modification=date_etat_courant,
        mt_ht=Decimal("100"),
        mt_ttc=Decimal("120"),
        montant_tva=Decimal("20"),
        montant_a_payer=Decimal("120"),
        fournisseur_type_d_identifiant="SIREN",
        fournisseur_identifiant="123456789",
        fournisseur_designation="Fournisseur",
        destinataire_code_service="SERVICE",
        destinataire_service="Service",
        devise_de_la_facture="EUR",
        numero_du_bon_de_commande="BC",
        numero_de_marche="MARCHE",
        gm=gm,
        ministere=ministere,
    )
    return facture


def add_ligne(conn: psycopg.Connection, id_cpro: str, line_id: str = "1") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO gesec_facture_ligne (
                id_cpro, source, line_id, item_name, item_description,
                quantity, quantity_unit_code, unit_price,
                line_amount_excl_tax, line_amount_incl_tax, line_amount_vat, currency
            )
            VALUES (%s, 'facture-xml', %s, 'Article', 'Description',
                    1, 'C62', 100, 100, 120, 20, 'EUR')
            """,
            (id_cpro, line_id),
        )
    conn.commit()


def fetch_predictions(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT identifiant_chorus_pro, ministere, gm, gm_pred, gm_pred_domaine, gm_pred_segment
            FROM {TABLE_NAME}
            ORDER BY identifiant_chorus_pro
            """
        )
        columns = [c.name for c in cur.description or []]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def test_classifie_et_ecrit_la_prediction(conn: psycopg.Connection) -> None:
    create_facture("cpro-1")
    add_ligne(conn, "cpro-1")

    results = run_classify_hierarchical(conn, FakeLLM(), model="test", mode="new")

    assert len(results) == 1
    assert results[0]["gm_pred"] == "33.02.05"
    rows = fetch_predictions(conn)
    assert rows == [
        {
            "identifiant_chorus_pro": "cpro-1",
            "ministere": "FINANCES",
            "gm": "33.02",
            "gm_pred": "33.02.05",
            "gm_pred_domaine": "33",
            "gm_pred_segment": "33.02",
        }
    ]


def test_filtre_ministere(conn: psycopg.Connection) -> None:
    create_facture("cpro-fin", ministere="FINANCES")
    add_ligne(conn, "cpro-fin")
    create_facture("cpro-int", ministere="INTERIEUR")
    add_ligne(conn, "cpro-int")

    results = run_classify_hierarchical(conn, FakeLLM(), model="test", ministere="INTERIEUR")

    assert [r["identifiant_chorus_pro"] for r in results] == ["cpro-int"]


def test_filtre_date(conn: psycopg.Connection) -> None:
    create_facture("cpro-old", date_etat_courant=date(2024, 1, 1))
    add_ligne(conn, "cpro-old")
    create_facture("cpro-new", date_etat_courant=date(2025, 6, 1))
    add_ligne(conn, "cpro-new")

    results = run_classify_hierarchical(
        conn, FakeLLM(), model="test", date_min=date(2025, 1, 1), date_max=date(2025, 12, 31)
    )

    assert [r["identifiant_chorus_pro"] for r in results] == ["cpro-new"]


def test_mode_new_ignore_deja_classifiees(conn: psycopg.Connection) -> None:
    create_facture("cpro-1")
    add_ligne(conn, "cpro-1")
    run_classify_hierarchical(conn, FakeLLM(), model="test", mode="new")

    results = run_classify_hierarchical(conn, FakeLLM(), model="test", mode="new")

    assert results == []
    assert len(fetch_predictions(conn)) == 1


def test_reprocess_ecrase_la_prediction(conn: psycopg.Connection) -> None:
    create_facture("cpro-1")
    add_ligne(conn, "cpro-1")
    run_classify_hierarchical(conn, FakeLLM(), model="test", mode="new")

    results = run_classify_hierarchical(conn, FakeLLM(), model="test", mode="reprocess")

    assert len(results) == 1
    assert len(fetch_predictions(conn)) == 1


def test_read_identifiants_csv(tmp_path: Path) -> None:
    path = tmp_path / "ids.csv"
    path.write_text(
        "rank,identifiant_chorus_pro,gm_original,gm\n1,cpro-1,33.04,33.04\n2,cpro-2,33.06,\n3,cpro-1,33.04,33.04\n",
        encoding="utf-8",
    )

    assert read_identifiants_csv(path) == ["cpro-1", "cpro-2"]


def test_read_identifiants_csv_sans_colonne_nommee(tmp_path: Path) -> None:
    path = tmp_path / "ids.csv"
    path.write_text("id,autre\ncpro-9,x\n", encoding="utf-8")

    assert read_identifiants_csv(path) == ["cpro-9"]


def test_read_identifiants_csv_vide(tmp_path: Path) -> None:
    path = tmp_path / "ids.csv"
    path.write_text("identifiant_chorus_pro\n", encoding="utf-8")

    with pytest.raises(ValueError):
        read_identifiants_csv(path)


def test_identifiants_cible_le_classement(conn: psycopg.Connection) -> None:
    create_facture("cpro-a")
    add_ligne(conn, "cpro-a")
    create_facture("cpro-b")
    add_ligne(conn, "cpro-b")

    results = run_classify_hierarchical(conn, FakeLLM(), model="test", identifiants=["cpro-b"])

    assert [r["identifiant_chorus_pro"] for r in results] == ["cpro-b"]
    assert [r["identifiant_chorus_pro"] for r in fetch_predictions(conn)] == ["cpro-b"]


def test_sans_n_classifie_tout_le_perimetre(conn: psycopg.Connection) -> None:
    for i in range(5):
        create_facture(f"cpro-{i}")
        add_ligne(conn, f"cpro-{i}")

    results = run_classify_hierarchical(conn, FakeLLM(), model="test", batch_size=2)

    assert len(results) == 5
    assert len(fetch_predictions(conn)) == 5


def test_batch_size_pagine_par_cle_sans_doublon(conn: psycopg.Connection) -> None:
    for i in range(3):
        create_facture(f"cpro-{i}")
        add_ligne(conn, f"cpro-{i}")

    results = run_classify_hierarchical(conn, FakeLLM(), model="test", batch_size=1)

    identifiants = [r["identifiant_chorus_pro"] for r in results]
    assert identifiants == ["cpro-0", "cpro-1", "cpro-2"]
    assert len(fetch_predictions(conn)) == 3


def test_n_plafonne_le_nombre_de_factures(conn: psycopg.Connection) -> None:
    for i in range(4):
        create_facture(f"cpro-{i}")
        add_ligne(conn, f"cpro-{i}")

    results = run_classify_hierarchical(conn, FakeLLM(), model="test", n=2, batch_size=1)

    assert [r["identifiant_chorus_pro"] for r in results] == ["cpro-0", "cpro-1"]
    assert len(fetch_predictions(conn)) == 2
