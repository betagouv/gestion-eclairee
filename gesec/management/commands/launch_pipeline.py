from django.core.management.base import BaseCommand

from gesec.data.pipeline.launcher import launch_pipeline


class Command(BaseCommand):
    help = "Launch the pipeline"

    def add_arguments(self, parser):
        parser.add_argument("--ministere", type=str, help="Ministère à traiter")

    def handle(self, *args, **options):
        launch_pipeline(ministere=options["ministere"])
        self.stdout.write("Ok.")
