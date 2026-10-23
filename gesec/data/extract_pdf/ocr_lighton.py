"""OCR Albert openweight-ocr (image → texte) pour pages PDF4LLM."""

from __future__ import annotations

from typing import Protocol

from gesec.data.classify_gm.llm import LLMClient
from gesec.data.extract_pdf.api_semaphore import api_slot
from gesec.data.extract_pdf.paths import OCR_MAX_TOKENS, OCR_MODEL


class OcrApiError(Exception):
    def __init__(self, message: str, *, details: str | None = None):
        super().__init__(message)
        self.details = details


class LightonOcrClient(Protocol):
    def ocr_image_data_uri(self, data_uri: str) -> str: ...


class OpenWeightOcrClient:
    def __init__(self, llm_client: LLMClient, *, model: str = OCR_MODEL):
        self.llm_client = llm_client
        self.model = model

    def ocr_image_data_uri(self, data_uri: str) -> str:
        with api_slot():
            result = self.llm_client.ask_llm(
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "image_url", "image_url": {"url": data_uri}}],
                    }
                ],
                model=self.model,
                temperature=0.0,
                max_tokens=OCR_MAX_TOKENS,
            )
        if not isinstance(result.content, str):
            raise OcrApiError("Réponse OCR inattendue (JSON)", details=repr(result.content))
        return result.content.strip()
