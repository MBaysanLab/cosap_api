from django.core.management.base import BaseCommand
from ...models import SmallVariant, VariantAnnotation
import json


class Command(BaseCommand):
    help = "Imports a COSAP output dir as project."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json_path",
            type=str,
            help="Absolute path of JSON file of COSAP VariantMultipleAnnotator output in webapi container.",
        )

    def handle(self, *args, **kwargs):
        self.stdout.write(
            f"Importing Annotation from {kwargs['json_path']} to database..."
        )

        with open(kwargs["json_path"], "r") as f:
            data = json.load(f)

        for variant in data:
            svar, _ = SmallVariant.objects.get_or_create(
                variant_id=variant["variant_id"],
            )

            VariantAnnotation.objects.update_or_create(
                variant=svar,
                defaults=variant,
            )