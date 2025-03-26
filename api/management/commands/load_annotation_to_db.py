import json

from django.core.management.base import BaseCommand

from ...models import SmallVariant, VariantAnnotation


class Command(BaseCommand):
    help = "Imports annotation from COSAP VariantMultipleAnnotator output to database."

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
        
        print(f"{len(data)} variants found in JSON file.")
        
        # Extract all variant_ids
        variant_ids = [variant["variant_id"] for variant in data]
        
        # Get existing variants in one query
        existing_variants = {
            v.variant_id: v for v in SmallVariant.objects.filter(variant_id__in=variant_ids)
        }
        
        # Prepare lists for bulk operations
        variants_to_create = []
        annotations_to_create = []
        variant_annotation_fields = {field.name for field in VariantAnnotation._meta.fields}
        
        # Process each variant
        for variant in data:
            variant_id = variant["variant_id"]
            
            # Check if variant exists, otherwise create it
            if variant_id in existing_variants:
                svar = existing_variants[variant_id]
            else:
                svar = SmallVariant(
                    variant_id=variant_id,
                    chrom=variant["chr"],
                    pos=variant["pos"],
                    ref=variant["ref"],
                    alt=variant["alt"],
                )
                variants_to_create.append(svar)
            
            # Prepare annotation
            cleaned_variant = {
                key: value
                for key, value in variant.items()
                if key in variant_annotation_fields
            }
            
            annotations_to_create.append(VariantAnnotation(variant=svar, **cleaned_variant))
        
        # Bulk create new variants
        if variants_to_create:
            SmallVariant.objects.bulk_create(variants_to_create)
        
        # Bulk create annotations
        # Note: We need to use batch_size to handle potential primary key issues
        batch_size = 1000
        for i in range(0, len(annotations_to_create), batch_size):
            batch = annotations_to_create[i:i+batch_size]
            VariantAnnotation.objects.bulk_create(batch)
        
        self.stdout.write(
            f"Successfully imported {len(data)} variants with annotations."
        )