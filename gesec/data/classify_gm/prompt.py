"""Utilitaires parsing réponses LLM."""

from __future__ import annotations

import json
from typing import Any


def parse_llm_content(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        return json.loads(content)
    raise TypeError(f"Réponse LLM inattendue: {type(content)}")
