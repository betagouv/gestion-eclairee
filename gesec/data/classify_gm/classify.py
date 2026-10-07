"""Échantillonnage des factures gold et écriture des prédictions GM.

La source est le gold Django : gesec_facture (en-têtes) et gesec_facture_ligne
(lignes). Les prédictions sont upsertées dans gesec_facture_gm_pred.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, LiteralString, cast

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

ClassifyMode = Literal["new", "reprocess", "all"]
DEFAULT_MAX_WORKERS = 5

_ENTETE_TABLE = "gesec_facture"
_LIGNE_TABLE = "gesec_facture_ligne"
_RESULT_TABLE = "gesec_facture_gm_pred"

_MODE_FILTER_SQL: dict[ClassifyMode, LiteralString] = {
    "new": cast(
        LiteralString,
        f"AND NOT EXISTS (SELECT 1 FROM {_RESULT_TABLE} p WHERE p.identifiant_chorus_pro = e.identifiant_chorus_pro)",
    ),
    "reprocess": cast(
        LiteralString,
        f"AND EXISTS (SELECT 1 FROM {_RESULT_TABLE} p WHERE p.identifiant_chorus_pro = e.identifiant_chorus_pro)",
    ),
    "all": "",
}


@dataclass
class FactureSample:
    identifiant_chorus_pro: str
    fournisseur_designation: str | None
    mt_ttc: Any
    gm: str | None
    lignes: list[dict[str, Any]]


def _build_filters(
    *,
    mode: ClassifyMode,
    require_gm: bool,
    exclude_fournisseurs: list[str] | None,
    ministere: str | None,
    date_min: date | None,
    date_max: date | None,
) -> tuple[sql.Composable, list[Any]]:
    clauses: list[sql.Composable] = []
    params: list[Any] = []
    if require_gm:
        clauses.append(sql.SQL("AND e.gm IS NOT NULL AND e.gm <> ''"))
    if mode != "all":
        clauses.append(sql.SQL(_MODE_FILTER_SQL[mode]))
    if ministere:
        clauses.append(sql.SQL("AND e.ministere = %s"))
        params.append(ministere)
    if date_min:
        clauses.append(sql.SQL("AND e.date_etat_courant >= %s"))
        params.append(date_min)
    if date_max:
        clauses.append(sql.SQL("AND e.date_etat_courant <= %s"))
        params.append(date_max)
    if exclude_fournisseurs:
        placeholders = sql.SQL(", ").join(sql.Placeholder() * len(exclude_fournisseurs))
        clauses.append(sql.SQL("AND LOWER(COALESCE(e.fournisseur_designation, '')) NOT IN ({})").format(placeholders))
        params.extend(f.strip().lower() for f in exclude_fournisseurs)
    return sql.SQL(" ").join(clauses), params


def sample_factures(
    conn: psycopg.Connection,
    n: int = 100,
    seed: int | None = 42,
    mode: ClassifyMode = "new",
    identifiants: list[str] | None = None,
    exclude_fournisseurs: list[str] | None = None,
    require_gm: bool = False,
    ministere: str | None = None,
    date_min: date | None = None,
    date_max: date | None = None,
) -> list[FactureSample]:
    if mode not in _MODE_FILTER_SQL:
        raise ValueError(f"mode invalide : {mode!r} (attendu : new|reprocess|all)")

    entete = sql.Identifier(_ENTETE_TABLE)
    ligne = sql.Identifier(_LIGNE_TABLE)
    with conn.cursor() as cur:
        if identifiants is not None:
            cur.execute(
                sql.SQL(
                    """
                    SELECT e.identifiant_chorus_pro,
                           e.fournisseur_designation,
                           e.mt_ttc,
                           e.gm
                    FROM {} e
                    WHERE e.identifiant_chorus_pro = ANY(%s)
                    ORDER BY e.identifiant_chorus_pro
                    """
                ).format(entete),
                (identifiants,),
            )
        else:
            filters, params = _build_filters(
                mode=mode,
                require_gm=require_gm,
                exclude_fournisseurs=exclude_fournisseurs,
                ministere=ministere,
                date_min=date_min,
                date_max=date_max,
            )
            params.append(n)
            if seed is not None:
                cur.execute("SELECT setseed(%s)", (float(seed % 1000) / 1000.0,))
            cur.execute(
                sql.SQL(
                    """
                    SELECT e.identifiant_chorus_pro,
                           e.fournisseur_designation,
                           e.mt_ttc,
                           e.gm
                    FROM {} e
                    WHERE EXISTS (
                        SELECT 1 FROM {} l WHERE l.id_cpro = e.identifiant_chorus_pro
                    )
                      {}
                    ORDER BY random()
                    LIMIT %s
                    """
                ).format(entete, ligne, filters),
                params,
            )
        headers = cur.fetchall()

    samples: list[FactureSample] = []
    with conn.cursor() as cur:
        for identifiant, fournisseur, mt_ttc, gm in headers:
            cur.execute(
                sql.SQL(
                    """
                    SELECT line_id, item_name, item_description, line_amount_incl_tax
                    FROM {}
                    WHERE id_cpro = %s
                    ORDER BY line_id NULLS LAST
                    """
                ).format(ligne),
                (identifiant,),
            )
            lignes = [
                {
                    "line_id": r[0],
                    "item_name": r[1],
                    "item_description": r[2],
                    "line_amount_incl_tax": r[3],
                }
                for r in cur.fetchall()
            ]
            samples.append(
                FactureSample(
                    identifiant_chorus_pro=identifiant,
                    fournisseur_designation=fournisseur,
                    mt_ttc=mt_ttc,
                    gm=gm,
                    lignes=lignes,
                )
            )
    return samples


def upsert_prediction(
    conn: psycopg.Connection,
    *,
    identifiant_chorus_pro: str,
    gm_pred: str,
    domaine: str | None,
    segment: str | None,
    raison: str,
    raw: dict[str, Any],
    model: str,
    latency_s: float | None,
) -> None:
    result = sql.Identifier(_RESULT_TABLE)
    entete = sql.Identifier(_ENTETE_TABLE)
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                INSERT INTO {} (
                    identifiant_chorus_pro, ministere, gm,
                    gm_pred, gm_pred_domaine, gm_pred_segment, gm_pred_raison,
                    gm_pred_raw, gm_pred_at, gm_pred_model, latency_s
                )
                SELECT e.identifiant_chorus_pro, e.ministere, e.gm,
                       %s, %s, %s, %s, %s, NOW(), %s, %s
                FROM {} e
                WHERE e.identifiant_chorus_pro = %s
                ON CONFLICT (identifiant_chorus_pro) DO UPDATE SET
                    ministere = EXCLUDED.ministere,
                    gm = EXCLUDED.gm,
                    gm_pred = EXCLUDED.gm_pred,
                    gm_pred_domaine = EXCLUDED.gm_pred_domaine,
                    gm_pred_segment = EXCLUDED.gm_pred_segment,
                    gm_pred_raison = EXCLUDED.gm_pred_raison,
                    gm_pred_raw = EXCLUDED.gm_pred_raw,
                    gm_pred_at = EXCLUDED.gm_pred_at,
                    gm_pred_model = EXCLUDED.gm_pred_model,
                    latency_s = EXCLUDED.latency_s
                """
            ).format(result, entete),
            (
                gm_pred,
                domaine,
                segment,
                raison,
                Jsonb(raw),
                model,
                latency_s,
                identifiant_chorus_pro,
            ),
        )
    conn.commit()
