"""Client LLM OpenAI-compatible (Albert), sans Django."""

from __future__ import annotations

import json
import logging
import os
import random
import time
from copy import deepcopy
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any, cast

from openai import APIError, APIStatusError, OpenAI, omit
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONSchema

logger = logging.getLogger(__name__)


def _setting(name: str) -> str:
    """Lit un réglage Django (ALBERT_*) quand Django est configuré, sinon ""."""
    try:
        from django.conf import settings

        return getattr(settings, name, "") or ""
    except Exception:
        return ""


class LLMApiError(Exception):
    def __init__(self, message: str, *, code: str, details: Any):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details

    @classmethod
    def from_api_error(cls, e: APIError) -> LLMApiError:
        if isinstance(e, APIStatusError):
            code = f"HTTP_{e.status_code}"
            details = e.body
        else:
            code = f"ERROR_{e.__class__.__name__}"
            details = str(e)
        return cls(f"Api Error: {code} - {details}", code=code, details=details)


@dataclass
class LLMAskResult:
    content: str | dict
    usage: dict[str, int] | None = None


class LLMClient:
    """Client chat.completions compatible Albert / OpenAI."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        *,
        reasoning_effort: str | None = None,
    ):
        self.api_key = api_key or _setting("ALBERT_API_KEY") or os.environ.get("ALBERT_API_KEY") or ""
        self.base_url = base_url or _setting("ALBERT_BASE_URL") or os.environ.get("ALBERT_BASE_URL") or ""
        if not self.api_key or not self.base_url:
            raise RuntimeError("ALBERT_API_KEY et ALBERT_BASE_URL sont requis (env ou arguments)")
        self.timeout = timeout
        self.reasoning_effort = reasoning_effort
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout,
        )

    def ask_llm(
        self,
        messages: list[dict],
        model: str,
        response_format: dict | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        max_retries: int = 3,
        retry_delay: float = 60.0,
        retry_short_delay: float = 10.0,
    ) -> LLMAskResult:
        if not isinstance(messages, list) or not all(isinstance(x, dict) for x in messages):
            raise ValueError("`messages` should be a list of dicts")

        messages = deepcopy(messages)
        max_retries = max(0, max_retries)
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                extra_body = {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else None
                response = self.client.chat.completions.create(
                    model=model,
                    messages=cast(list[ChatCompletionMessageParam], messages),
                    temperature=temperature,
                    max_tokens=max_tokens if max_tokens is not None else omit,
                    response_format=cast(ResponseFormatJSONSchema, response_format) if response_format else omit,
                    extra_body=extra_body,
                )
                response_content = (response.choices[0].message.content or "").strip()
                try:
                    result: str | dict = json.loads(response_content) if response_format else response_content
                except JSONDecodeError as e:
                    messages.append({"role": "assistant", "content": response_content})
                    messages.append(
                        {
                            "role": "user",
                            "content": f"Complète et corrige le json. Erreur : {repr(e)}",
                        }
                    )
                    raise LLMApiError(
                        f"Api Error: JSON_DECODE_ERROR - {e!r}",
                        code="JSON_DECODE_ERROR",
                        details=repr(e),
                    ) from e

                usage = None
                if response.usage is not None:
                    usage = {
                        "prompt_tokens": response.usage.prompt_tokens or 0,
                        "completion_tokens": response.usage.completion_tokens or 0,
                    }
                return LLMAskResult(content=result, usage=usage)

            except LLMApiError as e:
                last_error = e
                code = e.code
            except APIError as e:
                last_error = LLMApiError.from_api_error(e)
                code = last_error.code
            except Exception as e:
                last_error = e
                code = f"ERROR_{type(e).__name__}"

            if attempt >= max_retries:
                break

            is_rate = "429" in code or "RATE" in code.upper()
            is_5xx = code.startswith("HTTP_5")
            if not (is_rate or is_5xx or code == "JSON_DECODE_ERROR"):
                break

            base_delay = retry_delay if is_rate else retry_short_delay
            wait_time = base_delay * (1 + 0.1 * random.random()) * (attempt + 1)
            logger.warning("%s, wait %.1fs before retry (%d/%d)", code, wait_time, attempt + 1, max_retries)
            time.sleep(wait_time)

        assert last_error is not None
        raise last_error
