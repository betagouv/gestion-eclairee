from django.core.management.base import BaseCommand

from gesec.data.pipeline.layer_3_gold.meta_budat import process_to_gold


class Command(BaseCommand):
    help = "Reconstruit la méta-table BUDAT gesec_meta_budat depuis le gold"

    def handle(self, *args, **options):
        process_to_gold()
        self.stdout.write("Ok.")
