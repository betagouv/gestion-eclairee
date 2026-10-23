"""Appels LLM d'extraction structurée."""

from __future__ import annotations

import logging
from typing import Any

from gesec.data.classify_gm.llm import LLMClient
from gesec.data.classify_gm.prompt import parse_llm_content
from gesec.data.extract_pdf.api_semaphore import api_slot
from gesec.data.extract_pdf.paths import EXTRACTION_MODEL
from gesec.data.extract_pdf.prompt import (
    SYSTEM_PROMPT_EXTRACTION,
    build_text_user_prompt,
    response_format_lignes,
)
from gesec.data.extract_pdf.schemas import ExtractedFacture, ExtractedLigne

logger = logging.getLogger(__name__)


def _parse_extraction(content: Any) -> ExtractedFacture:
    data = parse_llm_content(content)
    raw_lignes = data.get("lignes")
    if not isinstance(raw_lignes, list):
        raise ValueError("Champ 'lignes' manquant ou invalide dans la réponse LLM")
    lignes = [ExtractedLigne.model_validate(item) for item in raw_lignes]
    raw_objet = data.get("objet_facture")
    objet_facture: str | None
    if raw_objet is None:
        objet_facture = None
    elif isinstance(raw_objet, str):
        stripped = raw_objet.strip()
        objet_facture = stripped or None
    else:
        objet_facture = str(raw_objet).strip() or None
    return ExtractedFacture(objet_facture=objet_facture, lignes=lignes)


def extract_lignes_from_text(
    llm_client: LLMClient,
    *,
    id_cpro: str,
    text: str,
    content_kind: str = "texte extrait du PDF",
    model: str = EXTRACTION_MODEL,
) -> tuple[ExtractedFacture, dict[str, int] | None]:
    with api_slot():
        result = llm_client.ask_llm(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_EXTRACTION},
                {
                    "role": "user",
                    "content": build_text_user_prompt(id_cpro=id_cpro, content=text, content_kind=content_kind),
                },
            ],
            model=model,
            response_format=response_format_lignes(),
            temperature=0.0,
        )
    return _parse_extraction(result.content), result.usage
