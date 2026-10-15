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
from decimal import Decimal
from typing import Any

import sqlalchemy
from sqlalchemy import Engine, text

Tableau = list[list[Any]]


def create_engine(env_var: str) -> Engine:
    db_url = os.environ.get(env_var)
    if db_url is None:
        raise ValueError(f"{env_var} environment variable is required")
    engine = sqlalchemy.create_engine(db_url.replace("postgres:", "postgresql+psycopg:"))
    return engine.execution_options(isolation_level="AUTOCOMMIT", postgresql_readonly=True)


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
    return {
        "tableau": tableau,
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
        "enrichissement_ugap": enrichissement_ugap(engine, args.annee),
        "gm": gm(engine, args.annee),
    }
    sys.stdout.write(dump(result))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
