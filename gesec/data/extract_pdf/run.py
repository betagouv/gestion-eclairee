"""Orchestration extraction PDF4LLM + LLM."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings

from tqdm import tqdm

from gesec.data.classify_gm.llm import LLMClient
from gesec.data.extract_pdf.api_semaphore import init_api_semaphore, reset_api_semaphore
from gesec.data.extract_pdf.extract_llm import extract_lignes_from_text
from gesec.data.extract_pdf.io_csv import write_entete_rows, write_ligne_rows, write_timings_rows
from gesec.data.extract_pdf.paths import (
    DEFAULT_MAX_WORKERS,
    ENTETE_CSV_NAME,
    EXTRACTION_LLM_TIMEOUT,
    EXTRACTION_MODEL,
    LIGNES_CSV_NAME,
    MAX_PAGES,
    PDF4LLM_MD_MAX_WORKERS,
    PDF4LLM_OCR_BACKEND,
    PDF4LLM_OCR_BACKENDS,
    TIMINGS_CSV_NAME,
    resolve_data_paths,
)
from gesec.data.extract_pdf.pdf4llm_extract import (
    Pdf4llmOcrBackend,
    Pdf4llmWorkerJob,
    pdf4llm_markdown_cache_path,
    pdf4llm_markdown_worker,
)
from gesec.data.extract_pdf.pdf_utils import (
    list_pdf_paths,
    page_count,
    parse_id_cpro,
    skip_too_many_pages_error,
)
from gesec.data.extract_pdf.schemas import (
    EnteteCsvRow,
    ExtractedFacture,
    ExtractTimings,
    LigneCsvRow,
    TimingsCsvRow,
)

logger = logging.getLogger(__name__)


@dataclass
class ExtractSummary:
    run_id: str
    pdf_count: int
    ligne_rows: int
    entete_rows: int
    timings_rows: int
    skipped_pdf_count: int
    lignes_csv: Path
    entete_csv: Path
    timings_csv: Path


@dataclass(frozen=True)
class _ExtractJob:
    pdf_path: Path
    id_cpro: str
    pdf_filename: str


@dataclass
class _ExtractJobResult:
    job: _ExtractJob
    facture: ExtractedFacture
    timings: ExtractTimings


def build_llm_client(*, extraction_model: str) -> LLMClient:
    reasoning_effort = "low" if extraction_model.startswith("gpt-oss") else None
    return LLMClient(
        api_key=settings.ALBERT_API_KEY,
        base_url=settings.ALBERT_BASE_URL,
        timeout=EXTRACTION_LLM_TIMEOUT,
        reasoning_effort=reasoning_effort,
    )


def default_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]


def _run_llm_step(
    job: _ExtractJob,
    *,
    markdown: str,
    duration_md_s: float,
    llm_client: LLMClient,
    extraction_model: str,
    md_error: str,
    markdown_cached: bool,
) -> _ExtractJobResult:
    timings = ExtractTimings(page_count=page_count(job.pdf_path))
    timings.duration_text_or_render_s = duration_md_s
    timings.ocr_cached = markdown_cached
    facture = ExtractedFacture()
    if md_error:
        timings.error = md_error
        timings.duration_total_s = duration_md_s
        return _ExtractJobResult(job=job, facture=facture, timings=timings)

    try:
        t_llm = time.perf_counter()
        facture, usage = extract_lignes_from_text(
            llm_client,
            id_cpro=job.id_cpro,
            text=markdown,
            content_kind="markdown PyMuPDF4LLM",
            model=extraction_model,
        )
        timings.duration_llm_s = round(time.perf_counter() - t_llm, 3)
        timings.llm_usage = usage
    except Exception as e:
        logger.exception("Extraction LLM échouée pour %s", job.id_cpro)
        timings.error = repr(e)
        facture = ExtractedFacture()
    timings.duration_total_s = round(duration_md_s + timings.duration_llm_s, 3)
    return _ExtractJobResult(job=job, facture=facture, timings=timings)


def _run_jobs_pipelined(
    jobs: list[_ExtractJob],
    *,
    ocr_dir: Path,
    force_markdown: bool,
    llm_client: LLMClient,
    extraction_model: str = EXTRACTION_MODEL,
    md_workers: int,
    llm_workers: int,
    pdf4llm_ocr_backend: Pdf4llmOcrBackend = PDF4LLM_OCR_BACKEND,
) -> list[_ExtractJobResult]:
    if not jobs:
        return []

    md_workers = max(1, md_workers)
    llm_workers = max(1, llm_workers)
    results: list[_ExtractJobResult] = []

    md_executor: type[ProcessPoolExecutor] | type[ThreadPoolExecutor]
    if pdf4llm_ocr_backend == "tesseract":
        md_executor = ProcessPoolExecutor
    else:
        md_executor = ThreadPoolExecutor

    with md_executor(max_workers=md_workers) as md_pool:
        with ThreadPoolExecutor(max_workers=llm_workers) as llm_pool:
            md_future_to_job = {
                md_pool.submit(
                    pdf4llm_markdown_worker,
                    Pdf4llmWorkerJob(
                        pdf_path_str=str(job.pdf_path),
                        cache_path_str=str(pdf4llm_markdown_cache_path(ocr_dir, job.id_cpro)),
                        force_refresh=force_markdown,
                        ocr_backend=pdf4llm_ocr_backend,
                    ),
                ): job
                for job in jobs
            }
            llm_futures = []
            for md_future in tqdm(
                as_completed(md_future_to_job),
                total=len(md_future_to_job),
                desc="extract_pdf markdown",
            ):
                job = md_future_to_job[md_future]
                md_result = md_future.result()
                llm_futures.append(
                    llm_pool.submit(
                        _run_llm_step,
                        job,
                        markdown=md_result.markdown,
                        duration_md_s=md_result.duration_s,
                        llm_client=llm_client,
                        extraction_model=extraction_model,
                        md_error=md_result.error,
                        markdown_cached=md_result.markdown_cached,
                    )
                )
            for llm_future in tqdm(as_completed(llm_futures), total=len(llm_futures), desc="extract_pdf llm"):
                results.append(llm_future.result())

    return results


def run_extract(
    *,
    factures_dir: Path | str | None = None,
    ocr_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
    limit: int | None = None,
    force_markdown: bool = False,
    dry_run: bool = False,
    run_id: str | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    pdf4llm_md_workers: int | None = None,
    extraction_model: str = EXTRACTION_MODEL,
    id_cpro_filter: Sequence[str] | None = None,
    pdf4llm_ocr_backend: Pdf4llmOcrBackend = PDF4LLM_OCR_BACKEND,
    max_pages: int = MAX_PAGES,
) -> ExtractSummary:
    factures_path, ocr_path, output_path = resolve_data_paths(
        factures_dir=factures_dir,
        ocr_dir=ocr_dir,
        output_dir=output_dir,
    )
    run = run_id or default_run_id()
    workers = max(1, max_workers)
    md_workers = max(1, pdf4llm_md_workers or PDF4LLM_MD_MAX_WORKERS)
    if pdf4llm_ocr_backend not in PDF4LLM_OCR_BACKENDS:
        raise ValueError(f"pdf4llm_ocr_backend inconnu : {pdf4llm_ocr_backend!r}")

    pdf_paths = list_pdf_paths(factures_path)
    if id_cpro_filter:
        allowed = set(id_cpro_filter)
        pdf_paths = [p for p in pdf_paths if parse_id_cpro(p.name) in allowed]
    if limit is not None:
        pdf_paths = pdf_paths[: max(0, limit)]

    lignes_csv = output_path / LIGNES_CSV_NAME
    entete_csv = output_path / ENTETE_CSV_NAME
    timings_csv = output_path / TIMINGS_CSV_NAME

    ligne_rows: list[LigneCsvRow] = []
    entete_rows: list[EnteteCsvRow] = []
    timings_rows: list[TimingsCsvRow] = []

    jobs: list[_ExtractJob] = []
    skipped_pdf_count = 0
    page_limit = max(1, max_pages)
    for pdf_path in pdf_paths:
        id_cpro = parse_id_cpro(pdf_path.name)
        pdf_pages = page_count(pdf_path)
        if pdf_pages > page_limit:
            skipped_pdf_count += 1
            skip_error = skip_too_many_pages_error(page_count=pdf_pages, max_pages=page_limit)
            timings_rows.append(
                TimingsCsvRow(
                    run_id=run,
                    id_cpro=id_cpro,
                    pdf_filename=pdf_path.name,
                    duration_ocr_s=0.0,
                    duration_text_or_render_s=0.0,
                    duration_llm_s=0.0,
                    duration_total_s=0.0,
                    page_count=pdf_pages,
                    ocr_cached=False,
                    error=skip_error,
                    llm_prompt_tokens=None,
                    llm_completion_tokens=None,
                    extraction_model=extraction_model,
                )
            )
            continue
        jobs.append(
            _ExtractJob(
                pdf_path=pdf_path,
                id_cpro=id_cpro,
                pdf_filename=pdf_path.name,
            )
        )

    if dry_run:
        for job in jobs:
            timings_rows.append(
                TimingsCsvRow(
                    run_id=run,
                    id_cpro=job.id_cpro,
                    pdf_filename=job.pdf_filename,
                    duration_ocr_s=0.0,
                    duration_text_or_render_s=0.0,
                    duration_llm_s=0.0,
                    duration_total_s=0.0,
                    page_count=page_count(job.pdf_path),
                    ocr_cached=False,
                    error="",
                    llm_prompt_tokens=None,
                    llm_completion_tokens=None,
                    extraction_model=extraction_model,
                )
            )
    else:
        llm_client = build_llm_client(extraction_model=extraction_model)
        init_api_semaphore(workers)
        try:
            results = _run_jobs_pipelined(
                jobs,
                ocr_dir=ocr_path,
                force_markdown=force_markdown,
                llm_client=llm_client,
                extraction_model=extraction_model,
                md_workers=md_workers,
                llm_workers=workers,
                pdf4llm_ocr_backend=pdf4llm_ocr_backend,
            )
        finally:
            reset_api_semaphore()

        for result in results:
            job = result.job
            timings = result.timings
            timings_rows.append(
                TimingsCsvRow.from_timings(
                    run_id=run,
                    id_cpro=job.id_cpro,
                    pdf_filename=job.pdf_filename,
                    timings=timings,
                    extraction_model=extraction_model,
                )
            )
            if not timings.error:
                entete_rows.append(
                    EnteteCsvRow.from_extraction(
                        run_id=run,
                        id_cpro=job.id_cpro,
                        pdf_filename=job.pdf_filename,
                        facture=result.facture,
                    )
                )
                for ligne in result.facture.lignes:
                    ligne_rows.append(
                        LigneCsvRow.from_extraction(
                            run_id=run,
                            id_cpro=job.id_cpro,
                            pdf_filename=job.pdf_filename,
                            ligne=ligne,
                        )
                    )

    write_ligne_rows(lignes_csv, ligne_rows)
    write_entete_rows(entete_csv, entete_rows)
    write_timings_rows(timings_csv, timings_rows)

    return ExtractSummary(
        run_id=run,
        pdf_count=len(pdf_paths),
        ligne_rows=len(ligne_rows),
        entete_rows=len(entete_rows),
        timings_rows=len(timings_rows),
        skipped_pdf_count=skipped_pdf_count,
        lignes_csv=lignes_csv,
        entete_csv=entete_csv,
        timings_csv=timings_csv,
    )
