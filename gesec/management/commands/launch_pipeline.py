from django.core.management.base import BaseCommand

from gesec.data.pipeline.launcher import launch_pipeline


class Command(BaseCommand):
    help = "Launch the pipeline"

    def handle(self, *args, **options):
        launch_pipeline()
        self.stdout.write("Ok.")
