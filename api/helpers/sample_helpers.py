from ..models import Sample, SampleSmallVariantData, SmallVariant, SampleSmallVariant
from common.utils import is_fastq_pair, safe_bulk_create
from ..constants import FileExtensions, VCFHeaders


def get_sample_fastq_pairs(sample_id):
    """
    Returns the fastq pairs of the sample.
    """
    sample = Sample.objects.get(id=sample_id)
    sample_files = sample.files.all()
    fastq_files = [f for f in sample_files if f.file_type == FileExtensions.FASTQ.name]

    if len(fastq_files) == 2 and is_fastq_pair(
        fastq_files[0].name, fastq_files[1].name
    ):
        return (fastq_files[0].file.path, fastq_files[1].file.path)
    return None


def handle_parse_vcf_results_for_sample(variant_list, sample_id):
    """
    Create SmallVariant objects from a list of variant dictionaries.
    """
    sample = Sample.objects.get(id=sample_id)

    # Create variant_id to full variant info mapping
    variant_map = {}
    for v in variant_list:
        chrom = v[VCFHeaders.CHROM.value]
        pos = v[VCFHeaders.POS.value]
        ref = v[VCFHeaders.REF.value]
        alt = v[VCFHeaders.ALT.value]
        af = v.get(VCFHeaders.AF.value, None)
        ad = v.get(VCFHeaders.AD.value, None)
        dp = v.get(VCFHeaders.DP.value, None)
        gt = v.get(VCFHeaders.GT.value, None)
        variant_id = f"{chrom}_{pos}_{ref}_{alt}"
        variant_map[variant_id] = {
            VCFHeaders.CHROM.value: chrom,
            VCFHeaders.POS.value: pos,
            VCFHeaders.REF.value: ref,
            VCFHeaders.ALT.value: alt,
            VCFHeaders.AF.value: af,
            VCFHeaders.AD.value: ad,
            VCFHeaders.DP.value: dp,
            VCFHeaders.GT.value: gt,
        }

    variant_ids = list(variant_map.keys())

    # Get existing variant IDs in a single query
    existing_variant_ids = set(
        SmallVariant.objects.filter(variant_id__in=variant_ids).values_list(
            "variant_id", flat=True
        )
    )

    # Find only the new variants that need to be created
    new_variant_ids = [vid for vid in variant_ids if vid not in existing_variant_ids]

    variants_to_create = []
    for vid in new_variant_ids:
        v = variant_map[vid]
        variants_to_create.append(
            SmallVariant(
                variant_id=vid,
                chrom=v[VCFHeaders.CHROM.value],
                pos=v[VCFHeaders.POS.value],
                ref=v[VCFHeaders.REF.value],
                alt=v[VCFHeaders.ALT.value],
            )
        )

    safe_bulk_create(SmallVariant, variants_to_create, ignore_conflicts=True)

    # Get actually created variants to identify failed ones
    successfully_created_variant_ids = set(
        SmallVariant.objects.filter(variant_id__in=variant_ids).values_list(
            "variant_id", flat=True
        )
    )

    # Remove failed variants from variant_map to avoid issues downstream
    failed_variant_ids = set(variant_ids) - successfully_created_variant_ids
    for failed_vid in failed_variant_ids:
        variant_map.pop(failed_vid, None)

    # Get or create the sample-variants relationship in one operation
    sample_small_variants, _ = SampleSmallVariant.objects.get_or_create(sample=sample)

    # Add only successfully created variants to the sample
    sample_small_variants.variants.add(
        *SmallVariant.objects.filter(variant_id__in=successfully_created_variant_ids)
    )

    # Create the SampleSmallVariantData objects - now only for valid variants
    data_to_create = []
    for vid in (
        variant_map.keys()
    ):  # variant_map now only contains successfully created variants
        data_to_create.append(
            SampleSmallVariantData(
                sample=sample,
                variant=SmallVariant.objects.get(variant_id=vid),
                allele_frequency=variant_map[vid][VCFHeaders.AF.value],
                allele_depth=variant_map[vid][VCFHeaders.AD.value],
                read_depth=variant_map[vid][VCFHeaders.DP.value],
                genotype=variant_map[vid][VCFHeaders.GT.value],
            )
        )
    safe_bulk_create(SampleSmallVariantData, data_to_create, ignore_conflicts=True)
