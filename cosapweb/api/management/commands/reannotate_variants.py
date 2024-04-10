from django.core.management.base import BaseCommand
from ...models import SNV
from ...helpers.task_helpers import submit_cosap_annotation_task

class Command(BaseCommand):
    help = "Re-annotate all variants in the database."

    def handle(self, *args, **kwargs):
        self.stdout.write("Re-annotating all variants in the database.")

        variants = SNV.objects.all()
        variant_list = [
            {
                "CHROM": variant.location.split("_")[0],
                "POS": variant.location.split("_")[1],
                "REF": variant.ref,
                "ALT": variant.alt,
            }
            for variant in variants
        ]

        submit_cosap_annotation_task(variant_list)
