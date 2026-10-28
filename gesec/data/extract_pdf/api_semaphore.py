"""Limite globale de requêtes Albert concurrentes (OCR + extraction LLM)."""

from __future__ import annotations

import threading
from contextlib import contextmanager

_api_semaphore: threading.Semaphore | None = None


def init_api_semaphore(max_concurrent: int) -> None:
    global _api_semaphore
    _api_semaphore = threading.Semaphore(max(1, max_concurrent))


def reset_api_semaphore() -> None:
    global _api_semaphore
    _api_semaphore = None


@contextmanager
def api_slot():
    if _api_semaphore is None:
        yield
        return
    _api_semaphore.acquire()
    try:
        yield
    finally:
        _api_semaphore.release()
