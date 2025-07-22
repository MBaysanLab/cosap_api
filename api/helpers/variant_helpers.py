from ..constants import VCFHeaders
from ..models import VariantAnnotation, SmallVariant
import logging
from common.utils import safe_bulk_create

logger = logging.getLogger(__name__)


def convert_vcf_format_to_snv(variant_dict: dict) -> dict:

    variant_dict["variant_id"] = "_".join(
        [
            variant_dict[VCFHeaders.CHROM.value],
            str(variant_dict[VCFHeaders.POS.value]),
            variant_dict[VCFHeaders.REF.value],
            variant_dict[VCFHeaders.ALT.value],
        ],
    )

    return variant_dict


def get_non_annotated_variants(variant_list, batch_size=1000) -> list:
    """
    Takes a list of variants and returns a list of variant dict for non-annotated variants.
    Processes in batches to avoid memory issues.
    """
    if not variant_list:
        return []
    
    # Process in batches to avoid memory issues
    non_annotated_variants = []
    
    for i in range(0, len(variant_list), batch_size):
        batch = variant_list[i:i + batch_size]
        
        # Convert batch to SNV format
        batch_converted = [convert_vcf_format_to_snv(variant) for variant in batch]
        batch_variant_ids = [variant["variant_id"] for variant in batch_converted]
        
        # Get non-annotated variant IDs for this batch
        non_annotated_ids = set(
            SmallVariant.objects.filter(
                variant_id__in=batch_variant_ids, 
                variantannotation__isnull=True
            ).values_list("variant_id", flat=True)
        )
        
        # Filter batch variants
        batch_non_annotated = [
            variant for variant in batch_converted
            if variant["variant_id"] in non_annotated_ids
        ]
        
        non_annotated_variants.extend(batch_non_annotated)
        
        # Log progress for large datasets
        if len(variant_list) > 10000:
            logger.info(f"Processed batch {i//batch_size + 1}/{(len(variant_list)-1)//batch_size + 1}")
    
    return non_annotated_variants


def create_smallvariants_from_json_list(variant_list: list) -> None:
    """
    Create SmallVariant objects from a list of variant dictionaries.
    """
    for variant in variant_list:
        SmallVariant.objects.get_or_create(
            variant_id=variant["variant_id"],
            chrom=variant[VCFHeaders.CHROM.value],
            pos=variant[VCFHeaders.POS.value],
            ref=variant[VCFHeaders.REF.value],
            alt=variant[VCFHeaders.ALT.value],
        )


def handle_annotation_results(annotation_results: list) -> None:
    """
    Create VariantAnnotation objects from a list of annotation dictionaries.
    """
    # Extract all variant_ids
    variant_ids = [variant["variant_id"] for variant in annotation_results]

    # Get existing variants in one query
    existing_variants = {
        v.variant_id: v for v in SmallVariant.objects.filter(variant_id__in=variant_ids)
    }

    # Prepare lists for bulk operations
    variants_to_create = []
    annotations_to_create = []

    # Process each variant
    for i, variant in enumerate(annotation_results):
        variant_id = variant["variant_id"]

        # Check if variant exists, otherwise create it
        if variant_id in existing_variants:
            svar = existing_variants[variant_id]
        else:
            svar = SmallVariant(
                variant_id=variant_id,
                chrom=variant.get("chr"),
                pos=variant.get("pos"),
                ref=variant.get("ref"),
                alt=variant.get("alt"),
            )
            variants_to_create.append(svar)


        # Prepare annotation
        cleaned_variant = {}
        for key, value in variant.items():
            if key in [field.name for field in VariantAnnotation._meta.fields]:
                cleaned_variant[key] = value

        annotations_to_create.append(VariantAnnotation(variant=svar, **cleaned_variant))

    # Bulk create new variants
    if variants_to_create:
        safe_bulk_create(SmallVariant, variants_to_create, ignore_conflicts=True)

    # Bulk create new annotations
    if annotations_to_create:
        safe_bulk_create(VariantAnnotation, annotations_to_create, ignore_conflicts=True)
