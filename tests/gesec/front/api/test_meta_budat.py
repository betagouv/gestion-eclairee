from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.db import connections

import pytest

from gesec.front.api.models import MetaBudat
from tests.gesec.front.oauth.helpers import make_access_token, make_mcp_user

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")

ALL_FIELDS = [
    "source",
    "source_idx",
    "annee",
    "facture",
    "facture_ref",
    "facture_date_str",
    "facture_date",
    "date_payment_str",
    "date_payment",
    "ej",
    "marche",
    "seej",
    "facture_fi",
    "societe",
    "cc",
    "pce",
    "txt50",
    "activite",
    "description",
    "libelle_budat",
    "fournisseur_budat",
    "fournisseur_siren_budat",
    "service_budat",
    "montant",
    "montant_ligne_ttc",
    "id_cpro",
    "numero",
    "facture_ttc",
    "gm_multi",
    "budat_gm",
    "budat_segment",
    "budat_domaine",
    "cpro_gm",
    "cpro_segment",
    "cpro_domaine",
    "pred_gm",
    "pred_segment",
    "pred_domaine",
    "gm",
    "segment",
    "domaine",
    "ministere",
    "service",
    "destinataire_service",
    "fournisseur_facture",
    "est_ugap",
    "line_id",
    "item_name",
    "item_description",
    "item_reference",
    "quantity",
    "unit_price",
    "montant_ligne_ht",
    "fournisseur_in_fine_designation",
    "fournisseur_in_fine_siren",
    "cas",
]


def make_row(**overrides) -> dict:
    row = {
        "source": "budat",
        "source_idx": 1,
        "annee": "2025",
        "facture": "F1",
        "facture_ref": "REF1",
        "facture_date_str": "20250115",
        "facture_date": date(2025, 1, 15),
        "date_payment_str": "20250215",
        "date_payment": date(2025, 2, 15),
        "ej": "EJ1",
        "marche": "M1",
        "seej": "SEEJ1",
        "facture_fi": "FI1",
        "societe": "SOC1",
        "cc": "CC1",
        "pce": "PCE1",
        "txt50": "TXT",
        "activite": "ACT",
        "description": "DESC",
        "libelle_budat": "LIB",
        "fournisseur_budat": "Fournisseur A",
        "fournisseur_siren_budat": "111111111",
        "service_budat": "SVC1",
        "montant": Decimal("100.00"),
        "montant_ligne_ttc": Decimal("120.00"),
        "id_cpro": "CPRO1",
        "numero": "NUM1",
        "facture_ttc": Decimal("120.00"),
        "gm_multi": False,
        "budat_gm": "33.01.04",
        "budat_segment": "33.01",
        "budat_domaine": "33",
        "cpro_gm": "",
        "cpro_segment": "",
        "cpro_domaine": "",
        "pred_gm": "",
        "pred_segment": "",
        "pred_domaine": "",
        "gm": "33.01.04",
        "segment": "33.01",
        "domaine": "33",
        "ministere": "MINA",
        "service": "SVC1",
        "destinataire_service": "Destinataire",
        "fournisseur_facture": "Fournisseur A",
        "est_ugap": False,
        "line_id": "L1",
        "item_name": "Article 1",
        "item_description": "Description article",
        "item_reference": "REF-ART",
        "quantity": Decimal("2"),
        "unit_price": Decimal("60.00"),
        "montant_ligne_ht": Decimal("100.00"),
        "fournisseur_in_fine_designation": "Fournisseur In Fine A",
        "fournisseur_in_fine_siren": "222222222",
        "cas": "lignes_non_ugap",
    }
    row.update(overrides)
    return row


@pytest.fixture
def meta_budat_table():
    data_connection = connections["data"]
    if MetaBudat._meta.db_table not in data_connection.introspection.table_names():
        with data_connection.schema_editor() as editor:
            editor.create_model(MetaBudat)
    yield
    with data_connection.schema_editor() as editor:
        editor.delete_model(MetaBudat)


@pytest.fixture
def api_user():
    user = make_mcp_user()
    permission = Permission.objects.get(
        content_type__app_label="gesec", content_type__model="user", codename="api_access"
    )
    user.user_permissions.add(permission)
    return user


def auth_headers(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_access_token(user)}"}


def test_list_requires_token(client, meta_budat_table):
    response = client.get("/api/meta-budat/")
    assert response.status_code == 401


def test_list_requires_api_access_permission(client, meta_budat_table):
    user = make_mcp_user()
    response = client.get("/api/meta-budat/", headers=auth_headers(user))
    assert response.status_code == 403


def test_list_returns_rows(client, meta_budat_table, api_user):
    MetaBudat.objects.create(**make_row())
    MetaBudat.objects.create(**make_row(facture="F2", source_idx=2, montant=Decimal("50.00"), ministere="MINB"))

    response = client.get("/api/meta-budat/", headers=auth_headers(api_user))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert {row["facture"] for row in body} == {"F1", "F2"}


def test_list_filter_equality_and_icontains(client, meta_budat_table, api_user):
    MetaBudat.objects.create(**make_row())
    MetaBudat.objects.create(**make_row(facture="F2", source_idx=2, ministere="MINB", fournisseur_budat="Autre Soc"))

    response = client.get("/api/meta-budat/?ministere=MINB", headers=auth_headers(api_user))
    assert response.status_code == 200
    assert [row["facture"] for row in response.json()] == ["F2"]

    response = client.get("/api/meta-budat/?fournisseur_budat=fournisseur a", headers=auth_headers(api_user))
    assert response.status_code == 200
    assert [row["facture"] for row in response.json()] == ["F1"]

    response = client.get("/api/meta-budat/?fournisseur_in_fine_designation=in fine", headers=auth_headers(api_user))
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_filter_range_and_date_range(client, meta_budat_table, api_user):
    MetaBudat.objects.create(**make_row())
    MetaBudat.objects.create(
        **make_row(facture="F2", source_idx=2, montant=Decimal("500.00"), facture_date=date(2024, 6, 1))
    )

    response = client.get("/api/meta-budat/?montant_min=200", headers=auth_headers(api_user))
    assert [row["facture"] for row in response.json()] == ["F2"]

    response = client.get(
        "/api/meta-budat/?facture_date_after=2025-01-01&facture_date_before=2025-12-31", headers=auth_headers(api_user)
    )
    assert [row["facture"] for row in response.json()] == ["F1"]


def test_list_ordering(client, meta_budat_table, api_user):
    MetaBudat.objects.create(**make_row(montant=Decimal("10.00")))
    MetaBudat.objects.create(**make_row(facture="F2", source_idx=2, montant=Decimal("999.00")))

    response = client.get("/api/meta-budat/?ordering=montant", headers=auth_headers(api_user))
    assert [row["montant"] for row in response.json()] == ["10.00", "999.00"]

    response = client.get("/api/meta-budat/?ordering=not_a_field", headers=auth_headers(api_user))
    assert response.status_code == 200


def test_list_capped_at_100_rows(client, meta_budat_table, api_user):
    MetaBudat.objects.bulk_create(
        MetaBudat(**make_row(facture=f"F{i}", source_idx=i, montant=Decimal(i))) for i in range(150)
    )

    response = client.get("/api/meta-budat/", headers=auth_headers(api_user))

    assert response.status_code == 200
    assert len(response.json()) == 100


def test_aggregate_group_by(client, meta_budat_table, api_user):
    MetaBudat.objects.create(**make_row())
    MetaBudat.objects.create(**make_row(facture="F2", source_idx=2, ministere="MINB", montant=Decimal("50.00")))
    MetaBudat.objects.create(**make_row(facture="F3", source_idx=3, ministere="MINB", montant=Decimal("25.00")))

    response = client.get(
        "/api/meta-budat/?group_by=ministere&agg=sum:montant&agg=count:*",
        headers=auth_headers(api_user),
    )

    assert response.status_code == 200
    body = {row["ministere"]: row for row in response.json()}
    assert body["MINA"]["sum_montant"] == 100.0
    assert body["MINA"]["count_all"] == 1
    assert body["MINB"]["sum_montant"] == 75.0
    assert body["MINB"]["count_all"] == 2


def test_aggregate_without_group_by(client, meta_budat_table, api_user):
    MetaBudat.objects.create(**make_row(montant=Decimal("100.00")))
    MetaBudat.objects.create(**make_row(facture="F2", source_idx=2, montant=Decimal("50.00")))

    response = client.get("/api/meta-budat/?agg=sum:montant", headers=auth_headers(api_user))

    assert response.status_code == 200
    assert response.json() == [{"sum_montant": 150.0}]


def test_aggregate_applies_filters_and_cap(client, meta_budat_table, api_user):
    for i in range(5):
        MetaBudat.objects.create(**make_row(facture=f"F{i}", source_idx=i, ministere="MINB"))
    MetaBudat.objects.create(**make_row(facture="FX", source_idx=99, ministere="MINA"))

    response = client.get(
        "/api/meta-budat/?ministere=MINB&group_by=segment&agg=count:*", headers=auth_headers(api_user)
    )
    assert response.status_code == 200
    assert response.json() == [{"segment": "33.01", "count_all": 5}]

    MetaBudat.objects.bulk_create(
        MetaBudat(**make_row(facture=f"G{i}", source_idx=100 + i, segment=f"33.{i:03d}", domaine="33"))
        for i in range(120)
    )
    response = client.get("/api/meta-budat/?group_by=segment&agg=count:*", headers=auth_headers(api_user))
    assert response.status_code == 200
    assert len(response.json()) == 100


def test_aggregate_rejects_unknown_group_by_and_agg(client, meta_budat_table, api_user):
    response = client.get("/api/meta-budat/?group_by=hacker", headers=auth_headers(api_user))
    assert response.status_code == 400

    response = client.get("/api/meta-budat/?agg=sum:montant&agg=drop:montant", headers=auth_headers(api_user))
    assert response.status_code == 400

    response = client.get("/api/meta-budat/?agg=sum:ministere", headers=auth_headers(api_user))
    assert response.status_code == 400

    response = client.get("/api/meta-budat/?agg=sum:*", headers=auth_headers(api_user))
    assert response.status_code == 400


def test_aggregate_requires_permission(client, meta_budat_table):
    user = make_mcp_user()
    response = client.get("/api/meta-budat/?agg=count:*", headers=auth_headers(user))
    assert response.status_code == 403


def test_schema(client, meta_budat_table, api_user):
    response = client.get("/api/meta-budat/schema/", headers=auth_headers(api_user))

    assert response.status_code == 200
    body = response.json()
    assert body["filterable"] == sorted(MetaBudat.FILTERABLE)
    assert body["groupable"] == sorted(MetaBudat.GROUPABLE)
    assert body["numeric"] == sorted(MetaBudat.NUMERIC)
    assert body["agg_funcs"] == sorted(MetaBudat.AGG_FUNCS)
    assert body["max_rows"] == 100


def test_detail_route_not_exposed(client, meta_budat_table, api_user):
    response = client.get("/api/meta-budat/123/", headers=auth_headers(api_user))
    assert response.status_code == 404


def test_aggregate_ordering_by_annotation(client, meta_budat_table, api_user):
    MetaBudat.objects.create(**make_row(fournisseur_budat="Fourn A", montant=Decimal("10.00")))
    MetaBudat.objects.create(**make_row(fournisseur_budat="Fourn B", source_idx=2, montant=Decimal("999.00")))
    MetaBudat.objects.create(**make_row(fournisseur_budat="Fourn C", source_idx=3, montant=Decimal("500.00")))

    response = client.get(
        "/api/meta-budat/?group_by=fournisseur_budat&agg=sum:montant&ordering=-sum_montant",
        headers=auth_headers(api_user),
    )

    assert response.status_code == 200
    assert [row["fournisseur_budat"] for row in response.json()] == ["Fourn B", "Fourn C", "Fourn A"]


def test_aggregate_ordering_rejects_unknown_term(client, meta_budat_table, api_user):
    response = client.get(
        "/api/meta-budat/?group_by=ministere&agg=sum:montant&ordering=-montant",
        headers=auth_headers(api_user),
    )
    assert response.status_code == 400

    response = client.get(
        "/api/meta-budat/?group_by=ministere&agg=sum:montant&ordering=-sum_montant&ordering=montant",
        headers=auth_headers(api_user),
    )
    assert response.status_code == 400


def test_use_case_top_fournisseurs_on_segment(client, meta_budat_table, api_user):
    MetaBudat.objects.create(**make_row(fournisseur_budat="Fourn A", segment="33.xx", montant=Decimal("10.00")))
    MetaBudat.objects.create(
        **make_row(fournisseur_budat="Fourn B", source_idx=2, segment="33.xx", montant=Decimal("999.00"))
    )
    MetaBudat.objects.create(
        **make_row(fournisseur_budat="Fourn C", source_idx=3, segment="33.11", montant=Decimal("5000.00"))
    )

    response = client.get(
        "/api/meta-budat/?segment=33.xx&group_by=fournisseur_budat&agg=sum:montant&ordering=-sum_montant",
        headers=auth_headers(api_user),
    )

    assert response.status_code == 200
    body = response.json()
    assert [row["fournisseur_budat"] for row in body] == ["Fourn B", "Fourn A"]
    assert body[0]["sum_montant"] == 999.0


def test_use_case_top_ministeres_for_fournisseur(client, meta_budat_table, api_user):
    MetaBudat.objects.create(**make_row(ministere="MINA", fournisseur_budat="Fournisseur X", montant=Decimal("100.00")))
    MetaBudat.objects.create(
        **make_row(ministere="MINB", source_idx=2, fournisseur_budat="Fournisseur X", montant=Decimal("700.00"))
    )
    MetaBudat.objects.create(
        **make_row(ministere="MINC", source_idx=3, fournisseur_budat="Autre", montant=Decimal("9999.00"))
    )

    response = client.get(
        "/api/meta-budat/?fournisseur_budat=Fournisseur X&group_by=ministere&agg=sum:montant&ordering=-sum_montant",
        headers=auth_headers(api_user),
    )

    assert response.status_code == 200
    body = response.json()
    assert [row["ministere"] for row in body] == ["MINB", "MINA"]
    assert body[0]["sum_montant"] == 700.0


def test_aggregate_no_ordering_returns_rows(client, meta_budat_table, api_user):
    MetaBudat.objects.create(**make_row())
    MetaBudat.objects.create(**make_row(facture="F2", source_idx=2, ministere="MINB"))

    response = client.get("/api/meta-budat/?group_by=ministere&agg=count:*", headers=auth_headers(api_user))

    assert response.status_code == 200
    assert {row["ministere"] for row in response.json()} == {"MINA", "MINB"}


def test_aggregate_ordering_rejects_double_hyphen(client, meta_budat_table, api_user):
    response = client.get(
        "/api/meta-budat/?group_by=ministere&agg=sum:montant&ordering=--sum_montant",
        headers=auth_headers(api_user),
    )
    assert response.status_code == 400


def test_aggregate_rejects_invalid_filter_value(client, meta_budat_table, api_user):
    MetaBudat.objects.create(**make_row())

    response = client.get("/api/meta-budat/?montant_min=abc", headers=auth_headers(api_user))
    assert response.status_code == 400

    response = client.get(
        "/api/meta-budat/?montant_min=abc&group_by=ministere&agg=count:*", headers=auth_headers(api_user)
    )
    assert response.status_code == 400
