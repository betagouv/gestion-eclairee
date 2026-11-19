from django.core.management.base import BaseCommand

from gesec.data.sync.sftp_ingest import ingest_sftp


class Command(BaseCommand):
    help = "Ingère les fichiers CSV/Excel du bucket SFTP dans la base data (une table par fichier/onglet)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Liste les fichiers à traiter sans écrire")

    def handle(self, *args, **options):
        stats = ingest_sftp(dry_run=options["dry_run"])
        self.stdout.write(f"Ok. {stats}")
