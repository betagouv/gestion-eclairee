"""Orchestration de l'enrichissement GM du gold : table gesec_facture_gm_pred.

Étape indépendante du launcher : la classification mobilise un LLM externe,
coûteuse en latence. Elle se déclenche via `manage.py classify_gm`.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from django.conf import settings

from gesec.data.classify_gm.classify import DEFAULT_MAX_WORKERS, ClassifyMode, read_identifiants_csv
from gesec.data.classify_gm.classify_hierarchy import run_classify_hierarchical
from gesec.data.classify_gm.db import ensure_result_table, get_connection
from gesec.data.classify_gm.llm import LLMClient
from gesec.data.classify_gm.paths import (
    DEFAULT_LLM_TIMEOUT,
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    load_ddl,
)

logger = logging.getLogger(__name__)

TABLE_NAME = "gesec_facture_gm_pred"


def build_llm_client() -> LLMClient:
    return LLMClient(
        api_key=settings.ALBERT_API_KEY,
        base_url=settings.ALBERT_BASE_URL,
        timeout=DEFAULT_LLM_TIMEOUT,
        reasoning_effort=DEFAULT_REASONING_EFFORT,
    )


def process_to_gold(
    *,
    ministere: str | None = None,
    date_min: date | None = None,
    date_max: date | None = None,
    n: int = 100,
    seed: int | None = 42,
    mode: ClassifyMode = "new",
    max_workers: int = DEFAULT_MAX_WORKERS,
    model: str = DEFAULT_MODEL,
    identifiants_csv: str | Path | None = None,
    llm_client: LLMClient | None = None,
) -> list[dict]:
    """Classifie les factures du périmètre et upsert les prédictions dans la table gold.

    `identifiants_csv` cible un fichier d'identifiants Chorus Pro (prioritaire sur le
    tirage aléatoire `n` et les filtres de périmètre).
    """
    llm = llm_client or build_llm_client()
    identifiants = read_identifiants_csv(identifiants_csv) if identifiants_csv else None
    with get_connection() as conn:
        ensure_result_table(conn, load_ddl())
        return run_classify_hierarchical(
            conn,
            llm,
            n=n,
            seed=seed,
            model=model,
            mode=mode,
            identifiants=identifiants,
            ministere=ministere,
            date_min=date_min,
            date_max=date_max,
            max_workers=max_workers,
        )
