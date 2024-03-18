from ..constants import VCFHeaders
from ..models import SNV


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
    Takes a list of variants and returns a list of variants that are not in the database.
    """

    variant_list = [convert_vcf_format_to_snv(variant) for variant in variant_list]
    variant_ids = [variant["variant_id"] for variant in variant_list]
    snv_ids = SNV.objects.filter(variant_id__in=variant_ids, is_annotated = True).values_list(
        "variant_id", flat=True
    )

    absent_variants = [
        variant for variant in variant_list if variant["variant_id"] not in snv_ids
    ]

    return absent_variants if len(absent_variants) > 0 else None


def create_snv(variant_id: str) -> SNV:

    snv = SNV.objects.get_or_create(variant_id=variant_id)[0]
    return snv


def update_snv(variant_dict: dict) -> SNV:
    snv = SNV.objects.get(variant_id=variant_dict["variant_id"])
    snv_attributes = SNV.__dict__.keys()

    for key in snv_attributes:
        if key in variant_dict.keys():
            setattr(snv, key, variant_dict[key])
    snv.is_annotated = True
    snv.save()

    return snv
