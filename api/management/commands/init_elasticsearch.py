from django.core.management.base import BaseCommand
from api.documents import VariantAnnotationDocument


class Command(BaseCommand):
    help = "Initialize Elasticsearch indices"

    def handle(self, *args, **options):
        self.stdout.write("Creating Elasticsearch indices...")
        VariantAnnotationDocument.init()
        self.stdout.write(self.style.SUCCESS("Successfully created indices"))
