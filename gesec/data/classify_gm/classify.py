"""Échantillonnage des factures gold et écriture des prédictions GM.

La source est le gold Django : gesec_facture (en-têtes) et gesec_facture_ligne
(lignes). Les prédictions sont upsertées dans gesec_facture_gm_pred.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, LiteralString, cast

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

ClassifyMode = Literal["new", "reprocess", "all"]
DEFAULT_MAX_WORKERS = 5
DEFAULT_BATCH_SIZE = 500
_IDENTIFIANT_COLUMN = "identifiant_chorus_pro"

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


def read_identifiants_csv(path: str | Path) -> list[str]:
    """Lit les identifiants Chorus Pro d'un CSV (colonne `identifiant_chorus_pro`, sinon première)."""
    with Path(path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV vide ou sans en-tête : {path}")
        column = _IDENTIFIANT_COLUMN if _IDENTIFIANT_COLUMN in reader.fieldnames else reader.fieldnames[0]
        identifiants = [row[column].strip() for row in reader if row.get(column, "").strip()]
    if not identifiants:
        raise ValueError(f"Aucun identifiant lisible dans : {path}")
    return list(dict.fromkeys(identifiants))


def _fetch_headers(
    conn: psycopg.Connection,
    *,
    batch_size: int,
    after: str | None,
    mode: ClassifyMode,
    identifiants: list[str] | None,
    exclude_fournisseurs: list[str] | None,
    require_gm: bool,
    ministere: str | None,
    date_min: date | None,
    date_max: date | None,
) -> list[tuple]:
    entete = sql.Identifier(_ENTETE_TABLE)
    ligne = sql.Identifier(_LIGNE_TABLE)
    limit = sql.SQL("LIMIT %s")
    identifiants_filter = sql.SQL("")
    params: list[Any] = []
    if identifiants is not None:
        identifiants_filter = sql.SQL("AND e.identifiant_chorus_pro = ANY(%s)")
        params.append(identifiants)
    else:
        filters, filter_params = _build_filters(
            mode=mode,
            require_gm=require_gm,
            exclude_fournisseurs=exclude_fournisseurs,
            ministere=ministere,
            date_min=date_min,
            date_max=date_max,
        )
        identifiants_filter = filters
        params.extend(filter_params)
    keyset = sql.SQL("")
    if after is not None:
        keyset = sql.SQL("AND e.identifiant_chorus_pro > %s")
        params.append(after)
    params.append(batch_size)
    with conn.cursor() as cur:
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
                  {}
                ORDER BY e.identifiant_chorus_pro
                {}
                """
            ).format(entete, ligne, identifiants_filter, keyset, limit),
            params,
        )
        return cur.fetchall()


def _fetch_lignes(conn: psycopg.Connection, identifiant: str) -> list[dict[str, Any]]:
    ligne = sql.Identifier(_LIGNE_TABLE)
    with conn.cursor() as cur:
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
        return [
            {
                "line_id": r[0],
                "item_name": r[1],
                "item_description": r[2],
                "line_amount_incl_tax": r[3],
            }
            for r in cur.fetchall()
        ]


def iter_samples(
    conn: psycopg.Connection,
    *,
    n: int | None = None,
    mode: ClassifyMode = "new",
    identifiants: list[str] | None = None,
    exclude_fournisseurs: list[str] | None = None,
    require_gm: bool = False,
    ministere: str | None = None,
    date_min: date | None = None,
    date_max: date | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Iterator[FactureSample]:
    """Itère les factures du périmètre par lots (keyset), sans tout charger en mémoire.

    `n` plafonne le nombre de factures parcourues ; `None` couvre tout le périmètre.
    La pagination se fait par clé (`identifiant_chorus_pro`) pour rester déterministe
    et compatible avec l'écriture sur la même connexion.
    """
    if mode not in _MODE_FILTER_SQL:
        raise ValueError(f"mode invalide : {mode!r} (attendu : new|reprocess|all)")
    if batch_size < 1:
        raise ValueError(f"batch_size invalide : {batch_size!r} (attendu >= 1)")

    remaining = n
    after: str | None = None
    while remaining is None or remaining > 0:
        size = batch_size if remaining is None else min(batch_size, remaining)
        headers = _fetch_headers(
            conn,
            batch_size=size,
            after=after,
            mode=mode,
            identifiants=identifiants,
            exclude_fournisseurs=exclude_fournisseurs,
            require_gm=require_gm,
            ministere=ministere,
            date_min=date_min,
            date_max=date_max,
        )
        if not headers:
            return
        for identifiant, fournisseur, mt_ttc, gm in headers:
            yield FactureSample(
                identifiant_chorus_pro=identifiant,
                fournisseur_designation=fournisseur,
                mt_ttc=mt_ttc,
                gm=gm,
                lignes=_fetch_lignes(conn, identifiant),
            )
        if remaining is not None:
            remaining -= len(headers)
            if remaining <= 0:
                return
        if len(headers) < size:
            return
        after = headers[-1][0]


def count_samples(
    conn: psycopg.Connection,
    *,
    mode: ClassifyMode = "new",
    identifiants: list[str] | None = None,
    exclude_fournisseurs: list[str] | None = None,
    require_gm: bool = False,
    ministere: str | None = None,
    date_min: date | None = None,
    date_max: date | None = None,
) -> int:
    """Compte les factures éligibles du périmètre, avec les mêmes filtres que `iter_samples`."""
    if mode not in _MODE_FILTER_SQL:
        raise ValueError(f"mode invalide : {mode!r} (attendu : new|reprocess|all)")

    entete = sql.Identifier(_ENTETE_TABLE)
    ligne = sql.Identifier(_LIGNE_TABLE)
    effective_filters = sql.SQL("")
    params: list[Any] = []
    if identifiants is not None:
        effective_filters = sql.SQL("AND e.identifiant_chorus_pro = ANY(%s)")
        params.append(identifiants)
    else:
        effective_filters, filter_params = _build_filters(
            mode=mode,
            require_gm=require_gm,
            exclude_fournisseurs=exclude_fournisseurs,
            ministere=ministere,
            date_min=date_min,
            date_max=date_max,
        )
        params.extend(filter_params)
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                SELECT count(*)
                FROM {} e
                WHERE EXISTS (
                    SELECT 1 FROM {} l WHERE l.id_cpro = e.identifiant_chorus_pro
                )
                  {}
                """
            ).format(entete, ligne, effective_filters),
            params,
        )
        row = cur.fetchone()
        return int(row[0]) if row is not None else 0


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
