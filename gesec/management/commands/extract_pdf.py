from typing import get_args

from django.core.management.base import BaseCommand, CommandError

from gesec.data.extract_pdf.paths import (
    DEFAULT_CONCURRENCY_PDF4LLM,
    DEFAULT_WORKERS_EXTRACT,
    DEFAULT_WORKERS_MD,
    EXTRACTION_MODEL,
    MAX_PAGES,
)
from gesec.data.extract_pdf.run import run_extract
from gesec.data.extract_pdf.schemas import ERROR_STATUSES, PdfErrorType
from gesec.data.extract_pdf.selection import scan_inventory


class Command(BaseCommand):
    help = "Extraction structurée de factures PDF non DEMAT (PDF4LLM + LLM Albert)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            type=str,
            choices=["new", "retry", "reprocess", "all"],
            default="new",
            help=(
                "new : factures jamais tentées ; retry : erreurs existantes ; "
                "reprocess : toutes les lignes existantes ; all : tout (défaut : new)"
            ),
        )
        parser.add_argument(
            "--error-type",
            type=str,
            action="append",
            choices=(*get_args(PdfErrorType), *ERROR_STATUSES),
            default=None,
            help="Avec --mode retry, limite aux types d'erreur ou statuts donnés (répétable)",
        )
        parser.add_argument("--limit", type=int, default=None, help="Nombre max de candidats extractibles à traiter")
        parser.add_argument(
            "--max-pages",
            type=int,
            default=MAX_PAGES,
            help=f"Marque too_large au-delà de N pages (défaut : {MAX_PAGES})",
        )
        parser.add_argument(
            "--id-cpro",
            type=str,
            action="append",
            default=None,
            help="Limite à un ou plusieurs id_cpro (répétable)",
        )
        parser.add_argument(
            "--force-ocr",
            action="store_true",
            help="Ignore le cache Markdown S3 et relance PDF4LLM/OCR",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compte les factures par statut sans appel OCR/LLM ni écriture",
        )
        parser.add_argument(
            "--workers-md",
            type=int,
            default=DEFAULT_WORKERS_MD,
            help="Parallélisme des workers Markdown (défaut : 5)",
        )
        parser.add_argument(
            "--workers-extract",
            type=int,
            default=DEFAULT_WORKERS_EXTRACT,
            help="Parallélisme des appels LLM d'extraction (défaut : 5)",
        )
        parser.add_argument(
            "--concurrency-pdf4llm",
            type=int,
            default=DEFAULT_CONCURRENCY_PDF4LLM,
            help="Parallélisme des extractions PDF4LLM natives, CPU-bound (défaut : 1)",
        )
        parser.add_argument(
            "--extraction-model",
            type=str,
            default=EXTRACTION_MODEL,
            help="Modèle Albert pour l'extraction des lignes (défaut : gpt-oss-120b)",
        )

    def handle(self, *args, **options):
        mode = options["mode"]
        if options["error_type"] and mode != "retry":
            raise CommandError("--error-type n'est utilisable qu'avec --mode retry")

        try:
            summary = run_extract(
                selection=scan_inventory(),
                mode=mode,
                error_types=options["error_type"],
                id_filter=options["id_cpro"],
                limit=options["limit"],
                workers_md=options["workers_md"],
                workers_extract=options["workers_extract"],
                concurrency_pdf4llm=options["concurrency_pdf4llm"],
                extraction_model=options["extraction_model"],
                max_pages=options["max_pages"],
                force_refresh=options["force_ocr"] or mode in ("reprocess", "all"),
                dry_run=options["dry_run"],
            )
        except ValueError as e:
            raise CommandError(str(e)) from e

        self.stdout.write(
            f"mode={summary.mode} dry_run={summary.dry_run} sélectionnées={summary.selected} "
            f"en_attente={summary.pending} succès={summary.success} échecs={summary.failed} "
            f"no_pdf={summary.no_pdf} no_lines={summary.no_lines} too_large={summary.too_large}"
        )
