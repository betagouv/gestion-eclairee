"""Orchestration extraction PDF4LLM + LLM et persistance bronze."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Literal

from django.conf import settings

from tqdm import tqdm

from gesec.data.classify_gm.llm import LLMClient
from gesec.data.extract_pdf.api_semaphore import init_api_semaphore, reset_api_semaphore
from gesec.data.extract_pdf.extract_llm import extract_lignes_from_text
from gesec.data.extract_pdf.ocr_lighton import LightonOcrClient
from gesec.data.extract_pdf.paths import (
    DEFAULT_MAX_WORKERS,
    EXTRACTION_LLM_TIMEOUT,
    EXTRACTION_MODEL,
    MAX_PAGES,
    PDF4LLM_MD_MAX_WORKERS,
    PROMPT_VERSION,
)
from gesec.data.extract_pdf.pdf4llm_extract import PdfMarkdownResult, build_lighton_ocr_client, extract_pdf_markdown
from gesec.data.extract_pdf.result_table import ensure_table, select_target_ids, upsert
from gesec.data.extract_pdf.schemas import (
    BronzeExtractPdf,
    PdfErrorType,
    PdfExtractionStatus,
)
from gesec.data.extract_pdf.selection import PdfCandidate, PdfSelection

logger = logging.getLogger(__name__)

ExtractionMode = Literal["new", "retry", "reprocess", "all"]


@dataclass
class ExtractSummary:
    mode: ExtractionMode
    dry_run: bool
    selected: int = 0
    success: int = 0
    failed: int = 0
    header_missing: int = 0
    no_pdf: int = 0
    no_lines: int = 0
    too_large: int = 0
    skipped_xml: int = 0
    pending: int = 0


def build_llm_client(*, extraction_model: str) -> LLMClient:
    reasoning_effort = "low" if extraction_model.startswith("gpt-oss") else None
    return LLMClient(
        api_key=settings.ALBERT_API_KEY,
        base_url=settings.ALBERT_BASE_URL,
        timeout=EXTRACTION_LLM_TIMEOUT,
        reasoning_effort=reasoning_effort,
    )


def select_targets(
    selection: PdfSelection,
    *,
    mode: ExtractionMode,
    error_types: Sequence[str] | None = None,
    id_filter: Sequence[str] | None = None,
) -> tuple[list[str], int]:
    inventory_ids = (
        set(selection.candidates) | set(selection.header_missing) | set(selection.no_pdf) | set(selection.parse_errors)
    )

    targets = select_target_ids(
        list(inventory_ids),
        mode=mode,
        error_types=error_types,
        id_filter=id_filter,
    )
    targets &= inventory_ids
    skipped_xml = len(set(id_filter or ()) & selection.xml_ids)
    targets -= selection.xml_ids
    return sorted(targets), skipped_xml


def _candidate_row(
    candidate: PdfCandidate,
    *,
    status: PdfExtractionStatus,
    content: dict | None = None,
    markdown: PdfMarkdownResult | None = None,
    error: str | None = None,
    error_type: PdfErrorType | None = None,
) -> BronzeExtractPdf:
    return BronzeExtractPdf(
        id_cpro=candidate.id_cpro,
        status=status,
        content=content,
        pdf_path=candidate.pdf_path,
        pdf_filename=candidate.pdf_filename,
        pdf_sha256=markdown.pdf_sha256 if markdown else None,
        markdown_path=markdown.markdown_path if markdown else None,
        markdown_sha256=markdown.markdown_sha256 if markdown else None,
        page_count=markdown.page_count if markdown else None,
        extraction_model=EXTRACTION_MODEL,
        prompt_version=PROMPT_VERSION,
        error_type=error_type,
        error=error,
    )


def _status_row(id_cpro: str, status: PdfExtractionStatus) -> BronzeExtractPdf:
    return BronzeExtractPdf(id_cpro=id_cpro, status=status)


def _failed_markdown(candidate: PdfCandidate, error: str, error_type: PdfErrorType) -> BronzeExtractPdf:
    return _candidate_row(candidate, status="failed", error=error, error_type=error_type)


def _safe_markdown(
    candidate: PdfCandidate,
    *,
    ocr_client: LightonOcrClient,
    force_refresh: bool,
    max_pages: int,
) -> PdfMarkdownResult:
    try:
        return extract_pdf_markdown(
            id_cpro=candidate.id_cpro,
            pdf_path=candidate.pdf_path,
            pdf_filename=candidate.pdf_filename,
            ocr_client=ocr_client,
            force_refresh=force_refresh,
            max_pages=max_pages,
        )
    except Exception as e:
        logger.exception("Préparation Markdown échouée pour %s", candidate.id_cpro)
        return PdfMarkdownResult(
            markdown="",
            duration_s=0.0,
            page_count=0,
            pdf_sha256=None,
            markdown_sha256=None,
            markdown_cached=False,
            markdown_path="",
            status="failed",
            error=repr(e),
            error_type="parse",
        )


def _run_llm(
    candidate: PdfCandidate,
    markdown: PdfMarkdownResult,
    *,
    llm_client: LLMClient,
    extraction_model: str,
) -> BronzeExtractPdf:
    if markdown.status is not None:
        return _candidate_row(
            candidate,
            status=markdown.status,
            markdown=markdown,
            error=markdown.error or None,
            error_type=markdown.error_type,
        )

    try:
        content, _usage = extract_lignes_from_text(
            llm_client,
            id_cpro=candidate.id_cpro,
            text=markdown.markdown,
            content_kind="markdown PyMuPDF4LLM",
            model=extraction_model,
        )
    except Exception as e:
        logger.exception("Extraction LLM échouée pour %s", candidate.id_cpro)
        return _candidate_row(
            candidate,
            status="failed",
            markdown=markdown,
            error=repr(e),
            error_type="llm",
        )

    lignes = content.get("lignes")
    if not isinstance(lignes, list):
        return _candidate_row(
            candidate,
            status="failed",
            content=content,
            markdown=markdown,
            error="Champ 'lignes' manquant ou invalide dans la réponse LLM",
            error_type="parse",
        )
    status: PdfExtractionStatus = "success" if lignes else "no_lines"
    return _candidate_row(candidate, status=status, content=content, markdown=markdown)


def _increment(summary: ExtractSummary, status: PdfExtractionStatus) -> None:
    if status == "success":
        summary.success += 1
    elif status == "failed":
        summary.failed += 1
    elif status == "header_missing":
        summary.header_missing += 1
    elif status == "no_pdf":
        summary.no_pdf += 1
    elif status == "no_lines":
        summary.no_lines += 1
    else:
        summary.too_large += 1


def _process_candidates(
    candidates: Sequence[PdfCandidate],
    *,
    summary: ExtractSummary,
    llm_client: LLMClient,
    ocr_client: LightonOcrClient,
    force_refresh: bool,
    max_pages: int,
    workers: int,
    md_workers: int,
    extraction_model: str,
) -> None:
    """Traite les candidats avec des fenêtres de tâches en vol bornées.

    Au plus `md_workers` préparations Markdown et `workers` extractions LLM sont
    en vol simultanément, plus `workers` Markdown prêts en attente d'un créneau
    LLM : la RAM suit ces bornes, pas le nombre de candidats.
    """
    candidate_iter = iter(candidates)
    backlog_limit = workers
    ensure_table()

    def record(result: BronzeExtractPdf) -> None:
        upsert(result, ensure=False)
        _increment(summary, result.status)

    def submit_markdown(pool: ThreadPoolExecutor) -> bool:
        if len(pending_llm) >= backlog_limit:
            return False
        try:
            candidate = next(candidate_iter)
        except StopIteration:
            return False
        future = pool.submit(
            _safe_markdown,
            candidate,
            ocr_client=ocr_client,
            force_refresh=force_refresh,
            max_pages=max_pages,
        )
        md_futures[future] = candidate
        return True

    def submit_llm(pool: ThreadPoolExecutor, candidate: PdfCandidate, markdown: PdfMarkdownResult) -> None:
        llm_futures[
            pool.submit(
                _run_llm,
                candidate,
                markdown,
                llm_client=llm_client,
                extraction_model=extraction_model,
            )
        ] = candidate

    md_futures: dict[Future[PdfMarkdownResult], PdfCandidate] = {}
    llm_futures: dict[Future[BronzeExtractPdf], PdfCandidate] = {}
    pending_llm: deque[tuple[PdfCandidate, PdfMarkdownResult]] = deque()

    with tqdm(total=len(candidates), desc="extract_pdf markdown") as md_progress:
        with ThreadPoolExecutor(max_workers=md_workers) as md_pool, ThreadPoolExecutor(max_workers=workers) as llm_pool:
            while True:
                while len(md_futures) < md_workers and submit_markdown(md_pool):
                    pass
                if not (md_futures or llm_futures or pending_llm):
                    break

                for future in [f for f in llm_futures if f.done()]:
                    llm_futures.pop(future)
                    record(future.result())

                while len(llm_futures) < workers and pending_llm:
                    candidate, markdown = pending_llm.popleft()
                    submit_llm(llm_pool, candidate, markdown)

                if md_futures:
                    done, _ = wait(md_futures, return_when=FIRST_COMPLETED)
                    for future in done:
                        candidate = md_futures.pop(future)
                        md_progress.update(1)
                        markdown = future.result()
                        if markdown.status is not None:
                            record(
                                _candidate_row(
                                    candidate,
                                    status=markdown.status,
                                    markdown=markdown,
                                    error=markdown.error or None,
                                    error_type=markdown.error_type,
                                )
                            )
                        else:
                            pending_llm.append((candidate, markdown))
                    continue

                wait(llm_futures, return_when=FIRST_COMPLETED)


def run_extract(
    *,
    selection: PdfSelection,
    mode: ExtractionMode,
    error_types: Sequence[str] | None = None,
    id_filter: Sequence[str] | None = None,
    limit: int | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    pdf4llm_md_workers: int | None = None,
    extraction_model: str = EXTRACTION_MODEL,
    max_pages: int = MAX_PAGES,
    force_refresh: bool = False,
    dry_run: bool = False,
) -> ExtractSummary:
    targets, skipped_xml = select_targets(
        selection,
        mode=mode,
        error_types=error_types,
        id_filter=id_filter,
    )

    summary = ExtractSummary(mode=mode, dry_run=dry_run, skipped_xml=skipped_xml)
    candidate_ids = [id_cpro for id_cpro in targets if id_cpro in selection.candidates]
    if limit is not None:
        candidate_ids = candidate_ids[: max(0, limit)]
    selected_ids = set(candidate_ids)
    summary.selected = len(targets)

    candidates: list[PdfCandidate] = []
    if not dry_run:
        ensure_table()

    for id_cpro in targets:
        candidate = selection.candidates.get(id_cpro)
        if candidate is not None:
            if id_cpro in selected_ids:
                candidates.append(candidate)
        elif id_cpro in selection.header_missing:
            summary.header_missing += 1
            if not dry_run:
                upsert(_status_row(id_cpro, "header_missing"), ensure=False)
        elif id_cpro in selection.parse_errors:
            summary.failed += 1
            if not dry_run:
                upsert(
                    BronzeExtractPdf(
                        id_cpro=id_cpro,
                        status="failed",
                        error_type="parse",
                        error=selection.parse_errors[id_cpro],
                    ),
                    ensure=False,
                )
        else:
            summary.no_pdf += 1
            if not dry_run:
                upsert(_status_row(id_cpro, "no_pdf"), ensure=False)

    if dry_run:
        summary.pending = len(candidates)
        return summary

    if not candidates:
        return summary

    workers = max(1, max_workers)
    md_workers = max(1, pdf4llm_md_workers or PDF4LLM_MD_MAX_WORKERS)
    llm_client = build_llm_client(extraction_model=extraction_model)
    ocr_client = build_lighton_ocr_client()
    init_api_semaphore(workers)
    try:
        _process_candidates(
            candidates,
            summary=summary,
            llm_client=llm_client,
            ocr_client=ocr_client,
            force_refresh=force_refresh,
            max_pages=max_pages,
            workers=workers,
            md_workers=md_workers,
            extraction_model=extraction_model,
        )
    finally:
        reset_api_semaphore()

    return summary
