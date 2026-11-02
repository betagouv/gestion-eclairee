"""Limite globale des extractions PDF4LLM natives (CPU-bound)."""

from __future__ import annotations

import threading
from contextlib import contextmanager

_pdf4llm_semaphore: threading.Semaphore | None = None


def init_pdf4llm_semaphore(max_concurrent: int) -> None:
    global _pdf4llm_semaphore
    _pdf4llm_semaphore = threading.Semaphore(max(1, max_concurrent))


def reset_pdf4llm_semaphore() -> None:
    global _pdf4llm_semaphore
    _pdf4llm_semaphore = None


@contextmanager
def pdf4llm_slot():
    if _pdf4llm_semaphore is None:
        yield
        return
    _pdf4llm_semaphore.acquire()
    try:
        yield
    finally:
        _pdf4llm_semaphore.release()
