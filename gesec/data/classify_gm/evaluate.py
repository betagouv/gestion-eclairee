"""Comparaison Gm (vérité terrain) vs Gm_pred sur gesec_facture_gm_pred."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import psycopg

from gesec.data.classify_gm.referential import NON_CLASSIFIE

RESULT_TABLE = "gesec_facture_gm_pred"


def gm_match(gm: str | None, gm_pred: str | None) -> bool:
    """OK si Gm_pred == Gm ou Gm_pred est un code feuille sous le segment Gm."""
    if not gm or not gm_pred or gm_pred == NON_CLASSIFIE:
        return False
    gm = gm.strip()
    gm_pred = gm_pred.strip()
    return gm_pred == gm or gm_pred.startswith(gm + ".")


@dataclass
class EvaluationReport:
    n_total: int
    n_ok: int
    errors: list[tuple[str, str, str]]
    confusion: Counter

    @property
    def accuracy(self) -> float | None:
        if self.n_total == 0:
            return None
        return self.n_ok / self.n_total


def evaluate_entete(conn: psycopg.Connection) -> EvaluationReport:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT identifiant_chorus_pro, gm, gm_pred
            FROM {RESULT_TABLE}
            WHERE gm_pred IS NOT NULL
              AND gm_pred <> ''
            ORDER BY gm_pred_at DESC NULLS LAST, identifiant_chorus_pro
            """
        )
        rows = cur.fetchall()

    n_ok = 0
    errors: list[tuple[str, str, str]] = []
    confusion: Counter = Counter()
    for identifiant, gm, gm_pred in rows:
        ok = gm_match(gm, gm_pred)
        if ok:
            n_ok += 1
        else:
            errors.append((identifiant, gm or "", gm_pred or ""))
            confusion[(gm or "?", gm_pred or "?")] += 1

    return EvaluationReport(
        n_total=len(rows),
        n_ok=n_ok,
        errors=errors,
        confusion=confusion,
    )


def format_report(report: EvaluationReport, max_errors: int = 20) -> str:
    lines: list[str] = []
    pct = f"{100.0 * report.accuracy:.1f}%" if report.accuracy is not None else "n/a"
    lines.append(f"Évalués : {report.n_total}")
    lines.append(f"OK      : {report.n_ok}")
    lines.append(f"Précision (match préfixe segment) : {pct}")
    if report.errors:
        lines.append("")
        lines.append(f"Erreurs (max {max_errors}) :")
        for identifiant, gm, gm_pred in report.errors[:max_errors]:
            lines.append(f"  {identifiant}: Gm={gm} vs Gm_pred={gm_pred}")
        if report.confusion:
            lines.append("")
            lines.append("Top confusions (gm → gm_pred) :")
            for (gm, gm_pred), count in report.confusion.most_common(10):
                lines.append(f"  {gm} → {gm_pred} : {count}")
    return "\n".join(lines)
