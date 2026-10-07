"""Chemins et constantes par défaut du paquet gesec.data.classify_gm."""

from __future__ import annotations

from pathlib import Path
from typing import LiteralString, cast

PACKAGE_ROOT = Path(__file__).resolve().parent

SCHEMA_PATH = PACKAGE_ROOT / "schema.sql"

# Solution packagée unique : gpt-oss-120b, reasoning low, segenrich
DEFAULT_MODEL = "gpt-oss-120b"
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_LLM_TIMEOUT = 120.0
PACKAGED_STRATEGY = "hierarchy_gptoss_low_segenrich"


def load_ddl() -> LiteralString:
    """DDL de la table de résultats gesec_facture_gm_pred."""
    return cast(LiteralString, SCHEMA_PATH.read_text(encoding="utf-8"))
