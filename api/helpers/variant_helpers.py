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


def get_non_annotated_variants(variant_list) -> list:
    """
    Takes a list of variants and returns a list of variant dict in format:
    [
        {
            "CHROM": "chr1",
            "POS": 12345,
            "REF": "A",
            "ALT": "T",
        },
        ...
    ]
    """

    variant_list = [convert_vcf_format_to_snv(variant) for variant in variant_list]
    variant_ids = [variant["variant_id"] for variant in variant_list]

    non_annotated = SmallVariant.objects.filter(
        variant_id__in=variant_ids, variantannotation__isnull=True
    )

    non_annotated_variants = [
        variant
        for variant in variant_list
        if variant["variant_id"] in non_annotated.values_list("variant_id", flat=True)
    ]

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
