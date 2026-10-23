from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from gesec.data.extract_pdf.paths import (
    DEFAULT_MAX_WORKERS,
    EXTRACTION_MODEL,
    MAX_PAGES,
    PDF4LLM_MD_MAX_WORKERS,
    PDF4LLM_OCR_BACKEND,
    PDF4LLM_OCR_BACKENDS,
)
from gesec.data.extract_pdf.run import run_extract


class Command(BaseCommand):
    help = "Extraction structurée de factures PDF non DEMAT (PDF4LLM + LLM Albert)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--factures-dir",
            type=str,
            default=None,
            help="Répertoire des PDF (sinon EXTRACT_PDF_DATA_ROOT/factures)",
        )
        parser.add_argument(
            "--ocr-dir",
            type=str,
            default=None,
            help="Cache markdown (sinon EXTRACT_PDF_DATA_ROOT/facture_ocr)",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=None,
            help="CSV de sortie (sinon EXTRACT_PDF_DATA_ROOT)",
        )
        parser.add_argument("--limit", type=int, default=None, help="Nombre max de PDF à traiter")
        parser.add_argument(
            "--max-pages",
            type=int,
            default=MAX_PAGES,
            help=f"Ignore les PDF de plus de N pages (défaut : {MAX_PAGES})",
        )
        parser.add_argument(
            "--id-cpro",
            type=str,
            action="append",
            default=None,
            help="Limite à un ou plusieurs id_cpro (répétable)",
        )
        parser.add_argument(
            "--force-markdown",
            action="store_true",
            help="Ignore le cache markdown (facture_ocr/pdf4llm)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Liste les PDF et écrit les timings sans appels OCR/LLM",
        )
        parser.add_argument("--run-id", type=str, default=None, help="Identifiant d'exécution pour les CSV")
        parser.add_argument(
            "--workers",
            type=int,
            default=DEFAULT_MAX_WORKERS,
            help="Parallélisme LLM Albert (défaut : 5)",
        )
        parser.add_argument(
            "--pdf4llm-md-workers",
            type=int,
            default=PDF4LLM_MD_MAX_WORKERS,
            help="Parallélisme markdown PDF4LLM (défaut : min(4, CPU))",
        )
        parser.add_argument(
            "--pdf4llm-ocr-backend",
            type=str,
            default=PDF4LLM_OCR_BACKEND,
            choices=PDF4LLM_OCR_BACKENDS,
            help="lighton (routage pymupdf4llm + openweight-ocr) ou tesseract (défaut : lighton)",
        )
        parser.add_argument(
            "--extraction-model",
            type=str,
            default=EXTRACTION_MODEL,
            help="Modèle Albert pour l'extraction des lignes (défaut : gpt-oss-120b)",
        )

    def handle(self, *args, **options):
        try:
            summary = run_extract(
                factures_dir=Path(options["factures_dir"]) if options["factures_dir"] else None,
                ocr_dir=Path(options["ocr_dir"]) if options["ocr_dir"] else None,
                output_dir=Path(options["output_dir"]) if options["output_dir"] else None,
                limit=options["limit"],
                force_markdown=options["force_markdown"],
                dry_run=options["dry_run"],
                run_id=options["run_id"],
                max_workers=options["workers"],
                pdf4llm_md_workers=options["pdf4llm_md_workers"],
                extraction_model=options["extraction_model"],
                id_cpro_filter=options["id_cpro"],
                pdf4llm_ocr_backend=options["pdf4llm_ocr_backend"],
                max_pages=options["max_pages"],
            )
        except ValueError as e:
            raise CommandError(str(e)) from e

        self.stdout.write(
            f"run_id={summary.run_id} pdfs={summary.pdf_count} ignorés_pages={summary.skipped_pdf_count} "
            f"lignes={summary.ligne_rows} entêtes={summary.entete_rows} timings={summary.timings_rows}"
        )
        self.stdout.write(f"Lignes : {summary.lignes_csv}")
        self.stdout.write(f"Entêtes : {summary.entete_csv}")
        self.stdout.write(f"Timings : {summary.timings_csv}")
