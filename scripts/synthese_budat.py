"""Génère en JSON les chiffres de la synthèse BUDAT.

Lecture seule de la base pointée par la variable d'environnement indiquée en
argument. Les tableaux sont émis sous forme de tableaux de tableaux, la première
ligne étant l'en-tête.

Usage :
    uv run python scripts/synthese_budat.py PROD_DB_URL 2025 > synthese.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy
from sqlalchemy import Engine, inspect, text

Tableau = list[list[Any]]

LINE_TOLERANCE = Decimal("0.02")
TOTAL_TOLERANCE = Decimal("0.005")


@dataclass(frozen=True)
class TotauxFacture:
    mt_ht: Decimal
    mt_ttc: Decimal
    montant_tva: Decimal


def create_engine(env_var: str) -> Engine:
    db_url = os.environ.get(env_var)
    if db_url is None:
        raise ValueError(f"{env_var} environment variable is required")
    engine = sqlalchemy.create_engine(db_url.replace("postgres:", "postgresql+psycopg:"))
    return engine.execution_options(isolation_level="AUTOCOMMIT", postgresql_readonly=True)


def table_exists(engine: Engine, name: str) -> bool:
    return inspect(engine).has_table(name)


def fetch_one(engine: Engine, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(text(sql), params or {}).one()
        return dict(row._mapping)


def fetch_all(engine: Engine, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(sql), params or {})]


def en_millions(value: Any) -> float:
    return round(float(value) / 1e6, 1)


def pct(part: Any, total: Any) -> float:
    return round(100.0 * float(part) / float(total), 1) if total else 0.0


def couverture(engine: Engine, annee: str) -> dict[str, Any]:
    row = fetch_one(
        engine,
        """
        select
            count(*) as lignes,
            round(sum(montant), 2) as montant,
            count(*) filter (where id_cpro is not null) as rattachees_lignes,
            round(sum(montant) filter (where id_cpro is not null), 2) as rattachees_montant,
            count(*) filter (where montant_ligne_ttc is not null) as eclatees_lignes,
            round(sum(montant) filter (where montant_ligne_ttc is not null), 2) as eclatees_montant,
            count(distinct id_cpro) filter (where id_cpro is not null) as factures_rattachees,
            count(distinct id_cpro) filter (where montant_ligne_ttc is not null) as factures_eclatees
        from gesec_meta_budat
        where annee = :annee
        """,
        {"annee": annee},
    )
    total_l = row["lignes"]
    total_m = row["montant"]
    tableau: Tableau = [
        ["etape", "lignes", "part_lignes", "montant_m", "part_montant"],
        ["Total BUDAT", total_l, 100.0, en_millions(total_m), 100.0],
        [
            "rattachées à une facture CPRO",
            row["rattachees_lignes"],
            pct(row["rattachees_lignes"], total_l),
            en_millions(row["rattachees_montant"]),
            pct(row["rattachees_montant"], total_m),
        ],
        [
            "éclatées en lignes gold",
            row["eclatees_lignes"],
            pct(row["eclatees_lignes"], total_l),
            en_millions(row["eclatees_montant"]),
            pct(row["eclatees_montant"], total_m),
        ],
    ]
    origines = fetch_all(
        engine,
        """
        select
            case
                when l.source like 'extract_pdf:%' then 'Extraction PDF'
                when l.source = 'factur-x' then 'Factur-X'
                when l.source = 'facture-xml' then 'XML'
                else 'Autre'
            end as origine,
            count(distinct l.id_cpro) as factures,
            count(*) as lignes,
            sum(l.line_amount_incl_tax) as montant
        from gesec_facture_ligne l
        where exists (
            select 1 from gesec_meta_budat b where b.id_cpro = l.id_cpro and b.annee = :annee
        )
        group by 1
        order by 3 desc
        """,
        {"annee": annee},
    )
    total_lignes_gold = sum(r["lignes"] for r in origines)
    total_montant_gold = sum(float(r["montant"]) for r in origines)
    origines_tableau: Tableau = [["origine", "factures", "lignes", "part_lignes", "montant_m", "part_montant"]]
    for r in origines:
        origines_tableau.append(
            [
                r["origine"],
                r["factures"],
                r["lignes"],
                pct(r["lignes"], total_lignes_gold),
                en_millions(r["montant"]),
                pct(r["montant"], total_montant_gold),
            ]
        )
    origines_tableau.append(["Total", None, total_lignes_gold, 100.0, en_millions(total_montant_gold), 100.0])

    return {
        "tableau": tableau,
        "origines": origines_tableau,
        "factures_distinctes_rattachees": row["factures_rattachees"],
        "factures_distinctes_eclatees": row["factures_eclatees"],
    }


def couverture_par_ministere(engine: Engine, annee: str) -> dict[str, Any]:
    rows = fetch_all(
        engine,
        """
        with tot as (
            select count(*) as l, sum(montant) as m
            from gesec_meta_budat where annee = :annee
        )
        select
            b.ministere,
            count(*) as lignes,
            round(sum(b.montant), 2) as montant,
            round(100.0 * count(*) / t.l, 1) as part_lignes,
            round(100.0 * sum(b.montant) / t.m, 1) as part_montant,
            round(100.0 * sum(b.montant) filter (where b.montant_ligne_ttc is not null)
                / nullif(sum(b.montant), 0), 1) as part_montant_eclatee
        from gesec_meta_budat b
        cross join tot t
        where b.annee = :annee
        group by b.ministere, t.l, t.m
        order by sum(b.montant) desc
        """,
        {"annee": annee},
    )
    total_l = sum(r["lignes"] for r in rows)
    total_m = sum(float(r["montant"]) for r in rows)
    tableau: Tableau = [["ministere", "lignes", "montant_m", "part_lignes", "part_montant", "part_montant_eclatee"]]
    for r in rows:
        tableau.append(
            [
                r["ministere"],
                r["lignes"],
                en_millions(r["montant"]),
                r["part_lignes"],
                r["part_montant"],
                r["part_montant_eclatee"],
            ]
        )
    tableau.append(["Total", total_l, en_millions(total_m), 100.0, 100.0, None])
    return {"tableau": tableau}


def restant_eclater_par_fournisseur(engine: Engine, annee: str) -> dict[str, Any]:
    rows = fetch_all(
        engine,
        """
        with facture as (
            select
                id_cpro,
                fournisseur_facture,
                bool_or(montant_ligne_ttc is not null) as eclatee,
                sum(montant) as montant
            from gesec_meta_budat
            where annee = :annee and id_cpro is not null
            group by id_cpro, fournisseur_facture
        ),
        restant as (select * from facture where not eclatee),
        tot as (select count(*) as n, sum(montant) as m from restant)
        select
            r.fournisseur_facture,
            count(*) as factures,
            round(sum(r.montant), 2) as montant,
            round(100.0 * count(*) / t.n, 1) as part_factures,
            round(100.0 * sum(r.montant) / t.m, 1) as part_montant
        from restant r
        cross join tot t
        group by r.fournisseur_facture, t.n, t.m
        order by sum(r.montant) desc
        limit 20
        """,
        {"annee": annee},
    )
    tableau: Tableau = [["fournisseur", "factures", "montant_m", "part_factures", "part_montant"]]
    for r in rows:
        tableau.append(
            [r["fournisseur_facture"], r["factures"], en_millions(r["montant"]), r["part_factures"], r["part_montant"]]
        )
    return {"tableau": tableau}


def enrichissement_ugap(engine: Engine, annee: str) -> dict[str, Any]:
    row = fetch_one(
        engine,
        """
        with per_facture as (
            select
                id_cpro,
                count(*) filter (where fournisseur_in_fine_designation is not null) as nb_fif,
                round(sum(montant), 2) as montant
            from gesec_meta_budat
            where est_ugap and annee = :annee
            group by id_cpro
        ),
        lignes as (
            select id_cpro, count(*) as nb_lignes_gold
            from gesec_facture_ligne group by id_cpro
        )
        select
            count(*) as factures,
            round(sum(p.montant), 2) as montant,
            count(*) filter (where l.nb_lignes_gold is not null and p.nb_fif > 0) as enrichies,
            round(sum(p.montant) filter (where l.nb_lignes_gold is not null and p.nb_fif > 0), 2) as enrichies_montant,
            count(*) filter (where l.nb_lignes_gold is null) as sans_lignes,
            round(sum(p.montant) filter (where l.nb_lignes_gold is null), 2) as sans_lignes_montant,
            count(*) filter (where l.nb_lignes_gold is not null and p.nb_fif = 0) as sans_match,
            round(sum(p.montant) filter (where l.nb_lignes_gold is not null and p.nb_fif = 0), 2) as sans_match_montant
        from per_facture p
        left join lignes l on l.id_cpro = p.id_cpro
        """,
        {"annee": annee},
    )
    total_f = row["factures"]
    total_m = row["montant"]
    tableau: Tableau = [
        ["etat", "factures", "part", "montant_m", "part"],
        [
            "enrichi",
            row["enrichies"],
            pct(row["enrichies"], total_f),
            en_millions(row["enrichies_montant"]),
            pct(row["enrichies_montant"], total_m),
        ],
        [
            "sans lignes gold",
            row["sans_lignes"],
            pct(row["sans_lignes"], total_f),
            en_millions(row["sans_lignes_montant"]),
            pct(row["sans_lignes_montant"], total_m),
        ],
        [
            "aucun match",
            row["sans_match"],
            pct(row["sans_match"], total_f),
            en_millions(row["sans_match_montant"]),
            pct(row["sans_match_montant"], total_m),
        ],
    ]

    reliquat = fetch_one(
        engine,
        """
        with per_facture as (
            select id_cpro,
                count(*) filter (where fournisseur_in_fine_designation is not null) as nb_fif
            from gesec_meta_budat where est_ugap and annee = :annee group by id_cpro
        ),
        lignes as (select id_cpro from gesec_facture_ligne group by id_cpro),
        suivi as (
            select id_cpro, bool_or(status = 'ligne_absente') as a_ligne_absente
            from gesec_facture_ugap_ligne where id_cpro is not null group by id_cpro
        )
        select
            count(*) as total,
            count(*) filter (where coalesce(s.a_ligne_absente, false)) as commande_presente_article_absent,
            count(*) filter (where not coalesce(s.a_ligne_absente, false)) as commande_absente
        from per_facture f
        join lignes l on l.id_cpro = f.id_cpro
        left join suivi s on s.id_cpro = f.id_cpro
        where f.nb_fif = 0
        """,
        {"annee": annee},
    )
    reliquat_tableau: Tableau = [
        ["cas", "factures"],
        ["commande absente de l'export UGAP", reliquat["commande_absente"]],
        ["commande présente, article absent de l'export", reliquat["commande_presente_article_absent"]],
    ]

    return {"tableau": tableau, "reliquat": reliquat_tableau}


def montant_factures(engine: Engine, annee: str) -> dict[str, float]:
    rows = fetch_all(
        engine,
        """
        select id_cpro, sum(montant) as montant
        from gesec_meta_budat
        where annee = :annee
        group by id_cpro
        """,
        {"annee": annee},
    )
    return {r["id_cpro"]: round(float(r["montant"] or 0), 2) for r in rows}


def extraction_pdf(engine: Engine, annee: str) -> dict[str, Any]:
    empty: dict[str, Any] = {
        "statuts": [["statut", "factures", "part", "pages", "page_moy", "montant"]],
        "reconciliation": {"extractions_reussies": 0, "extractions_en_gold": 0, "rejetees": 0},
        "echecs": [["error_type", "factures", "part", "montant"]],
        "echecs_silver": [["motif", "factures", "montant"]],
        "rejets_gold": [["motif", "factures", "part", "montant"]],
    }
    if not table_exists(engine, "bronze_extract_pdf"):
        return empty

    statuts = fetch_all(
        engine,
        """
        with tentatives as (
            select distinct p.id_cpro, p.status, p.page_count
            from bronze_extract_pdf p
            join gesec_meta_budat b on b.id_cpro = p.id_cpro and b.annee = :annee
        ),
        fm as (
            select id_cpro, sum(montant) as montant
            from gesec_meta_budat where annee = :annee group by id_cpro
        ),
        montants as (
            select t.status, sum(f.montant) as montant
            from (select distinct id_cpro, status from tentatives) t
            join fm f on f.id_cpro = t.id_cpro
            group by t.status
        )
        select
            t.status,
            count(*) as factures,
            coalesce(sum(t.page_count), 0) as pages,
            count(t.page_count) as factures_avec_pages,
            coalesce(m.montant, 0) as montant
        from tentatives t
        left join montants m on m.status = t.status
        group by t.status, m.montant
        order by count(*) desc
        """,
        {"annee": annee},
    )
    total_f = sum(r["factures"] for r in statuts)
    total_pages = sum(r["pages"] for r in statuts)
    total_avec_pages = sum(r["factures_avec_pages"] for r in statuts)
    total_montant = sum(float(r["montant"]) for r in statuts)
    statuts_tableau: Tableau = [["statut", "factures", "part", "pages", "page_moy", "montant"]]
    for r in statuts:
        statuts_tableau.append(
            [
                r["status"],
                r["factures"],
                pct(r["factures"], total_f),
                r["pages"],
                round(float(r["pages"]) / float(r["factures_avec_pages"]), 1) if r["factures_avec_pages"] else 0.0,
                round(float(r["montant"]), 2),
            ]
        )
    statuts_tableau.append(
        [
            "Total",
            total_f,
            100.0,
            total_pages,
            round(float(total_pages) / total_avec_pages, 1) if total_avec_pages else 0.0,
            round(total_montant, 2),
        ]
    )

    reconciliation = fetch_one(
        engine,
        """
        with tentatives as (
            select distinct p.id_cpro, p.status
            from bronze_extract_pdf p
            join gesec_meta_budat b on b.id_cpro = p.id_cpro and b.annee = :annee
        )
        select
            count(*) filter (where status = 'success') as succes,
            count(*) filter (
                where status = 'success'
                    and exists (select 1 from gesec_facture_ligne l where l.id_cpro = tentatives.id_cpro)
            ) as succes_en_gold
        from tentatives
        """,
        {"annee": annee},
    )

    echecs = fetch_all(
        engine,
        """
        with tentatives as (
            select distinct p.id_cpro, p.error_type
            from bronze_extract_pdf p
            join gesec_meta_budat b on b.id_cpro = p.id_cpro and b.annee = :annee
            where p.status = 'failed'
        ),
        fm as (
            select id_cpro, sum(montant) as montant
            from gesec_meta_budat where annee = :annee group by id_cpro
        )
        select
            t.error_type,
            count(*) as factures,
            coalesce(sum(f.montant), 0) as montant
        from tentatives t
        left join fm f on f.id_cpro = t.id_cpro
        group by t.error_type
        order by count(*) desc
        """,
        {"annee": annee},
    )
    total_echecs = sum(r["factures"] for r in echecs)
    echecs_tableau: Tableau = [["error_type", "factures", "part", "montant"]]
    for r in echecs:
        echecs_tableau.append(
            [r["error_type"], r["factures"], pct(r["factures"], total_echecs), round(float(r["montant"]), 2)]
        )

    return {
        "statuts": statuts_tableau,
        "reconciliation": {
            "extractions_reussies": reconciliation["succes"],
            "extractions_en_gold": reconciliation["succes_en_gold"],
            "rejetees": reconciliation["succes"] - reconciliation["succes_en_gold"],
        },
        "echecs": echecs_tableau,
        "echecs_silver": echecs_silver(engine, annee),
        "rejets_gold": rejets_gold(engine, annee),
    }


def echecs_silver(engine: Engine, annee: str) -> Tableau:
    tableau: Tableau = [["motif", "factures", "montant"]]
    if not table_exists(engine, "silver_extract_pdf_facture"):
        return tableau
    rows = fetch_all(
        engine,
        """
        with sf as (
            select
                s.id_cpro,
                case
                    when bool_or(
                        s.error_type = 'validation' and s.error ilike '%ht%tva%ttc%'
                    ) then 'HT + TVA != TTC ligne'
                    when bool_or(
                        s.error_type = 'validation'
                        and (s.error ilike '%dupliqu%' or s.error ilike '%line_id%')
                    ) then 'line_id dupliqué'
                    when bool_or(s.error_type = 'validation') then 'validation autre'
                    else min(s.error_type)
                end as motif
            from silver_extract_pdf_facture s
            join gesec_meta_budat b on b.id_cpro = s.id_cpro and b.annee = :annee
            where s.status = 'failed'
            group by s.id_cpro
        ),
        fm as (
            select id_cpro, sum(montant) as montant
            from gesec_meta_budat where annee = :annee group by id_cpro
        )
        select
            sf.motif,
            count(*) as factures,
            coalesce(sum(f.montant), 0) as montant
        from sf
        left join fm f on f.id_cpro = sf.id_cpro
        group by sf.motif
        order by count(*) desc
        """,
        {"annee": annee},
    )
    for r in rows:
        tableau.append([r["motif"], r["factures"], round(float(r["montant"]), 2)])
    return tableau


def derive_montants(
    ht: Decimal | None,
    ttc: Decimal | None,
    tva: Decimal | None,
    totals: TotauxFacture,
) -> tuple[Decimal, Decimal, Decimal] | None:
    tva_rate = totals.montant_tva / totals.mt_ht if totals.mt_ht else None
    ttc_rate = totals.mt_ttc / totals.mt_ht if totals.mt_ht else None
    if tva is None and ht is not None and tva_rate is not None:
        tva = ht * tva_rate
        if ttc is None:
            ttc = ht + tva
    if ttc is None and ht is not None and ttc_rate is not None:
        ttc = ht * ttc_rate
        if tva is None:
            tva = ttc - ht
    if ht is None or ttc is None or tva is None:
        return None
    return ht, ttc, tva


def within_tolerance(total: Decimal, expected: Decimal) -> bool:
    return abs(total - expected) <= abs(expected) * TOTAL_TOLERANCE


def _motif_rejet(lignes: list[dict[str, Any]], totals: TotauxFacture) -> str:
    sum_ht = Decimal("0")
    sum_ttc = Decimal("0")
    for ligne in lignes:
        amounts = derive_montants(
            ligne["line_amount_excl_tax"],
            ligne["line_amount_incl_tax"],
            ligne["line_amount_vat"],
            totals,
        )
        if amounts is None:
            return "Montants incomplets"
        ht, ttc, tva = amounts
        if abs(ht + tva - ttc) > LINE_TOLERANCE:
            return "HT + TVA != TTC ligne"
        sum_ht += ht
        sum_ttc += ttc
    if not within_tolerance(sum_ht, totals.mt_ht) or not within_tolerance(sum_ttc, totals.mt_ttc):
        return "Totaux PDF hors tolérance"
    return "autre"


def rejets_gold(engine: Engine, annee: str) -> Tableau:
    tableau: Tableau = [["motif", "factures", "part", "montant"]]
    if not table_exists(engine, "silver_extract_pdf_facture"):
        return tableau
    succes = fetch_all(
        engine,
        """
        select distinct s.id_cpro
        from silver_extract_pdf_facture s
        join gesec_meta_budat b on b.id_cpro = s.id_cpro and b.annee = :annee
        where s.status = 'success'
        """,
        {"annee": annee},
    )
    en_gold = {
        r["id_cpro"]
        for r in fetch_all(engine, "select distinct id_cpro from gesec_facture_ligne where source like 'extract_pdf:%'")
    }
    rejetes = [r["id_cpro"] for r in succes if r["id_cpro"] not in en_gold]
    if not rejetes:
        return tableau
    montants = montant_factures(engine, annee)
    lignes_rows = fetch_all(
        engine,
        """
        select id_cpro, line_amount_excl_tax, line_amount_incl_tax, line_amount_vat
        from silver_extract_pdf_ligne
        where id_cpro = any(:ids)
        """,
        {"ids": rejetes},
    )
    lignes: dict[str, list[dict[str, Any]]] = {}
    for row in lignes_rows:
        lignes.setdefault(row["id_cpro"], []).append(row)
    fact_rows = fetch_all(
        engine,
        """
        select identifiant_chorus_pro, mt_ht, mt_ttc, montant_tva
        from gesec_facture
        where identifiant_chorus_pro = any(:ids)
        """,
        {"ids": rejetes},
    )
    factures = {
        r["identifiant_chorus_pro"]: TotauxFacture(mt_ht=r["mt_ht"], mt_ttc=r["mt_ttc"], montant_tva=r["montant_tva"])
        for r in fact_rows
    }
    compteurs: dict[str, list[float]] = {}
    for id_cpro in rejetes:
        totals = factures.get(id_cpro)
        lignes_facture = lignes.get(id_cpro, [])
        if totals is None:
            motif = "en-tête absent"
        elif not lignes_facture:
            motif = "sans lignes silver"
        else:
            motif = _motif_rejet(lignes_facture, totals)
        entry = compteurs.setdefault(motif, [0.0, 0.0])
        entry[0] += 1
        entry[1] += montants.get(id_cpro, 0.0)
    total = sum(v[0] for v in compteurs.values())
    for motif, (n, m) in sorted(compteurs.items(), key=lambda kv: kv[1][0], reverse=True):
        tableau.append([motif, int(n), pct(n, total), round(m, 2)])
    return tableau


def gm(engine: Engine, annee: str) -> dict[str, Any]:
    couverture = fetch_one(
        engine,
        """
        select
            count(*) filter (where budat_gm <> '') as budat,
            count(*) filter (where cpro_gm <> '') as cpro,
            count(*) filter (where pred_gm <> '') as pred,
            count(*) filter (where gm <> '') as arbitre,
            count(*) as total
        from gesec_meta_budat where annee = :annee
        """,
        {"annee": annee},
    )
    couverture_tableau: Tableau = [
        ["colonne", "lignes", "part"],
        ["budat_gm rempli", couverture["budat"], pct(couverture["budat"], couverture["total"])],
        ["cpro_gm rempli", couverture["cpro"], pct(couverture["cpro"], couverture["total"])],
        ["pred_gm rempli", couverture["pred"], pct(couverture["pred"], couverture["total"])],
        ["gm arbitré (non vide)", couverture["arbitre"], pct(couverture["arbitre"], couverture["total"])],
    ]

    eligibles = fetch_one(
        engine,
        """
        select
            (select count(distinct e.identifiant_chorus_pro) from gesec_facture e
                where exists (
                    select 1 from gesec_facture_ligne l where l.id_cpro = e.identifiant_chorus_pro
                )) as eligibles,
            (select count(*) from gesec_facture_gm_pred where gm_pred is not null) as predites
        """,
    )
    ugap_pred = fetch_one(
        engine,
        """
        select
            count(distinct id_cpro) as total,
            count(distinct id_cpro) filter (where pred_gm <> '') as avec_pred
        from gesec_meta_budat
        where est_ugap and annee = :annee and id_cpro is not null
        """,
        {"annee": annee},
    )

    cascade = fetch_all(
        engine,
        """
        select
            case when pred_gm <> '' then 'pred' when cpro_gm <> '' then 'cpro' else 'budat' end as source,
            count(*) as lignes,
            round(sum(montant), 2) as montant
        from gesec_meta_budat where annee = :annee group by 1 order by 2 desc
        """,
        {"annee": annee},
    )
    total_l = couverture["total"]
    cascade_tableau: Tableau = [["source", "lignes", "part_lignes", "montant_m"]]
    for r in cascade:
        cascade_tableau.append([r["source"], r["lignes"], pct(r["lignes"], total_l), en_millions(r["montant"])])

    accords = fetch_one(
        engine,
        """
        with f as (
            select
                bool_or(pred_gm <> '') as has_pred,
                bool_or(cpro_gm <> '') as has_cpro,
                bool_or(budat_gm <> '') as has_budat,
                bool_or(pred_gm <> '' and cpro_gm <> ''
                    and substring(cpro_gm from 1 for 2) = substring(pred_gm from 1 for 2)) as pred_cpro_dom,
                bool_or(pred_gm <> '' and cpro_gm <> ''
                    and substring(cpro_gm from 1 for 5) = substring(pred_gm from 1 for 5)) as pred_cpro_seg,
                bool_or(pred_gm <> '' and budat_gm <> ''
                    and substring(budat_gm from 1 for 2) = substring(pred_gm from 1 for 2)) as pred_budat_dom,
                bool_or(pred_gm <> '' and budat_gm <> ''
                    and substring(budat_gm from 1 for 5) = substring(pred_gm from 1 for 5)) as pred_budat_seg,
                bool_or(cpro_gm <> '' and budat_gm <> ''
                    and substring(budat_gm from 1 for 2) = substring(cpro_gm from 1 for 2)) as budat_cpro_dom,
                bool_or(cpro_gm <> '' and budat_gm <> ''
                    and substring(budat_gm from 1 for 5) = substring(cpro_gm from 1 for 5)) as budat_cpro_seg
            from gesec_meta_budat
            where annee = :annee and id_cpro is not null
            group by id_cpro
        )
        select
            count(*) filter (where has_pred and has_cpro) as n_pred_cpro,
            count(*) filter (where has_pred and has_cpro and pred_cpro_dom) as pred_cpro_dom,
            count(*) filter (where has_pred and has_cpro and pred_cpro_seg) as pred_cpro_seg,
            count(*) filter (where has_pred and has_budat) as n_pred_budat,
            count(*) filter (where has_pred and has_budat and pred_budat_dom) as pred_budat_dom,
            count(*) filter (where has_pred and has_budat and pred_budat_seg) as pred_budat_seg,
            count(*) filter (where has_cpro and has_budat) as n_budat_cpro,
            count(*) filter (where has_cpro and has_budat and budat_cpro_dom) as budat_cpro_dom,
            count(*) filter (where has_cpro and has_budat and budat_cpro_seg) as budat_cpro_seg
        from f
        """,
        {"annee": annee},
    )
    accords_tableau: Tableau = [
        ["paire", "factures", "accord_domaine", "part_domaine", "accord_segment", "part_segment"],
        [
            "prédiction vs CPRO",
            accords["n_pred_cpro"],
            accords["pred_cpro_dom"],
            pct(accords["pred_cpro_dom"], accords["n_pred_cpro"]),
            accords["pred_cpro_seg"],
            pct(accords["pred_cpro_seg"], accords["n_pred_cpro"]),
        ],
        [
            "prédiction vs BUDAT",
            accords["n_pred_budat"],
            accords["pred_budat_dom"],
            pct(accords["pred_budat_dom"], accords["n_pred_budat"]),
            accords["pred_budat_seg"],
            pct(accords["pred_budat_seg"], accords["n_pred_budat"]),
        ],
        [
            "BUDAT vs CPRO",
            accords["n_budat_cpro"],
            accords["budat_cpro_dom"],
            pct(accords["budat_cpro_dom"], accords["n_budat_cpro"]),
            accords["budat_cpro_seg"],
            pct(accords["budat_cpro_seg"], accords["n_budat_cpro"]),
        ],
    ]

    return {
        "couverture": couverture_tableau,
        "couverture_prediction": {
            "factures_eligibles": eligibles["eligibles"],
            "factures_predites": eligibles["predites"],
            "part": pct(eligibles["predites"], eligibles["eligibles"]),
            "ugap_total": ugap_pred["total"],
            "ugap_avec_pred": ugap_pred["avec_pred"],
            "ugap_part": pct(ugap_pred["avec_pred"], ugap_pred["total"]),
        },
        "cascade": cascade_tableau,
        "accords": accords_tableau,
    }


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def dump(value: Any, indent: int = 2) -> str:
    """Sérialise en JSON avec chaque ligne de tableau sur une seule ligne."""
    if isinstance(value, list) and value and isinstance(value[0], list):
        rows = ",\n".join(" " * indent + dumps(row) for row in value)
        return "[\n" + rows + "\n" + " " * (indent - 2) + "]"
    if isinstance(value, dict):
        items = ",\n".join(" " * indent + dumps(k) + ": " + dump(v, indent + 2) for k, v in value.items())
        return "{\n" + items + "\n" + " " * (indent - 2) + "}"
    return dumps(value)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=json_default)


def main() -> None:
    parser = argparse.ArgumentParser(description="Génère la synthèse BUDAT en JSON.")
    parser.add_argument(
        "env_var",
        help="Nom de la variable d'environnement contenant l'URL de la base (ex. PROD_DB_URL)",
    )
    parser.add_argument("annee", help="Année BUDAT à analyser (ex. 2025)")
    args = parser.parse_args()

    engine = create_engine(args.env_var)
    result = {
        "annee": args.annee,
        "couverture": couverture(engine, args.annee),
        "couverture_par_ministere": couverture_par_ministere(engine, args.annee),
        "restant_eclater_par_fournisseur": restant_eclater_par_fournisseur(engine, args.annee),
        "enrichissement_ugap": enrichissement_ugap(engine, args.annee),
        "extraction_pdf": extraction_pdf(engine, args.annee),
        "gm": gm(engine, args.annee),
    }
    sys.stdout.write(dump(result))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
