"""Orchestration extraction PDF4LLM + LLM et persistance bronze."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
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
from gesec.data.extract_pdf.result_table import upsert
from gesec.data.extract_pdf.schemas import (
    ERROR_STATUSES,
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
    results: dict[str, BronzeExtractPdf],
    *,
    mode: ExtractionMode,
    error_types: Sequence[str] | None = None,
    id_filter: Sequence[str] | None = None,
) -> tuple[list[str], int]:
    inventory_ids = (
        set(selection.candidates) | set(selection.header_missing) | set(selection.no_pdf) | set(selection.parse_errors)
    )

    if mode == "new":
        targets = inventory_ids - results.keys()
    elif mode == "retry":
        targets = {id_cpro for id_cpro, row in results.items() if row.status in ERROR_STATUSES}
    elif mode == "reprocess":
        targets = inventory_ids & results.keys()
    else:
        targets = inventory_ids

    targets &= inventory_ids
    if error_types:
        allowed = set(error_types)
        targets = {
            id_cpro
            for id_cpro in targets
            if results.get(id_cpro, None)
            and (results[id_cpro].error_type in allowed or results[id_cpro].status in allowed)
        }
    if id_filter:
        targets &= set(id_filter)

    skipped_xml = len(targets & selection.xml_ids)
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
    llm_pool = ThreadPoolExecutor(max_workers=workers)
    llm_futures: list[Future[BronzeExtractPdf]] = []

    def record(result: BronzeExtractPdf) -> None:
        upsert(result)
        _increment(summary, result.status)

    try:
        with ThreadPoolExecutor(max_workers=md_workers) as md_pool:
            md_futures = {
                md_pool.submit(
                    _safe_markdown,
                    candidate,
                    ocr_client=ocr_client,
                    force_refresh=force_refresh,
                    max_pages=max_pages,
                ): candidate
                for candidate in candidates
            }
            for future in tqdm(as_completed(md_futures), total=len(md_futures), desc="extract_pdf markdown"):
                candidate = md_futures[future]
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
                    continue
                llm_futures.append(
                    llm_pool.submit(
                        _run_llm,
                        candidate,
                        markdown,
                        llm_client=llm_client,
                        extraction_model=extraction_model,
                    )
                )

        for future in tqdm(as_completed(llm_futures), total=len(llm_futures), desc="extract_pdf llm"):
            record(future.result())
    finally:
        llm_pool.shutdown(wait=True)


def run_extract(
    *,
    selection: PdfSelection,
    results: dict[str, BronzeExtractPdf],
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
        results,
        mode=mode,
        error_types=error_types,
        id_filter=id_filter,
    )
    if limit is not None:
        targets = targets[: max(0, limit)]

    summary = ExtractSummary(mode=mode, dry_run=dry_run, selected=len(targets), skipped_xml=skipped_xml)
    candidates: list[PdfCandidate] = []

    for id_cpro in targets:
        candidate = selection.candidates.get(id_cpro)
        if candidate is not None:
            candidates.append(candidate)
        elif id_cpro in selection.header_missing:
            summary.header_missing += 1
            if not dry_run:
                upsert(_status_row(id_cpro, "header_missing"))
        elif id_cpro in selection.parse_errors:
            summary.failed += 1
            if not dry_run:
                upsert(
                    BronzeExtractPdf(
                        id_cpro=id_cpro,
                        status="failed",
                        error_type="parse",
                        error=selection.parse_errors[id_cpro],
                    )
                )
        else:
            summary.no_pdf += 1
            if not dry_run:
                upsert(_status_row(id_cpro, "no_pdf"))

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
