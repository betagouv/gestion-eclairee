from datetime import date

from django.core.management.base import BaseCommand

from gesec.data.classify_gm.gold import process_to_gold


class Command(BaseCommand):
    help = "Classe les factures du gold par GM (LLM) et écrit gesec_facture_gm_pred"

    def add_arguments(self, parser):
        parser.add_argument("--ministere", type=str, help="Filtre ministère")
        parser.add_argument("--date-min", type=date.fromisoformat, help="Date de début (date_etat_courant)")
        parser.add_argument("--date-max", type=date.fromisoformat, help="Date de fin (date_etat_courant)")
        parser.add_argument("--n", type=int, default=100, help="Nombre de factures à classifier")
        parser.add_argument(
            "--identifiants-csv",
            type=str,
            help="CSV d'identifiants Chorus Pro à classifier (prioritaire sur --n et les filtres)",
        )
        parser.add_argument("--mode", choices=("new", "reprocess", "all"), default="new")
        parser.add_argument("--workers", type=int, default=None, help="Nombre de workers LLM")

    def handle(self, *args, **options):
        kwargs = {
            "ministere": options["ministere"],
            "date_min": options["date_min"],
            "date_max": options["date_max"],
            "n": options["n"],
            "mode": options["mode"],
            "identifiants_csv": options["identifiants_csv"],
        }
        if options["workers"] is not None:
            kwargs["max_workers"] = options["workers"]

        results = process_to_gold(**kwargs)
        n_err = sum(1 for r in results if r["error"])
        n_done = sum(1 for r in results if r["gm_pred"])
        self.stdout.write(f"Classifiées : {n_done}/{len(results)} (erreurs : {n_err}, mode={options['mode']})")
