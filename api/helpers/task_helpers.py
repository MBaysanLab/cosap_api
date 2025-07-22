from collections import defaultdict

from ..celery_handlers.tasks import (
    cosap_annotation_task,
    cosap_dna_task,
    cosap_parse_project_data_task,
    cosap_parse_vcf_task,
)
from ..constants import (
    CosapDnaTaskInputs,
    FileExtensions,
    ProjectStatus,
    ProjectTypes,
    Sampletypes,
)
from ..models import Project, ProjectFile, Sample, SampleReferenceGenome
from .project_helpers import (
    get_project_algorithms,
    get_project_dir,
    get_project_files,
    get_project_type,
    set_project_status,
    set_project_stderr,
    get_project_samples,
)
from .sample_helpers import get_sample_fastq_pairs
from logging import getLogger

logger = getLogger(__name__)


def submit_cosap_dna_task(project_id: int):
    """
    Takes a Project object and submits a COSAP DNA pipeline job to Celery.
    """
    project_type = get_project_type(project_id)
    logger.info(f"Submitting COSAP DNA task for project {project_id}")
    # Validate and get sample data based on project type
    sample_data = get_sample_files(project_id)
    if sample_data is None:
        logger.error("Failed to get sample data for project.")
        return

    fastq_pairs = defaultdict(list)
    for sample_id in sample_data:
        if sample_data[sample_id]["file_type"] == FileExtensions.VCF.name:
            # If the sample is a VCF file, we need to parse it
            logger.info(f"Submitting VCF parse task for sample {sample_id}")

            sample = Sample.objects.get(id=sample_id)
            reference_genome = SampleReferenceGenome.objects.get(sample=sample).reference_genome
            submit_vcf_parse_task(
                vcf_path=sample_data[sample_id]["files"],
                sample_name=None,
                caller_type=None,
                sample_id=sample_id,
                reference_genome=reference_genome,
            )

        elif sample_data[sample_id]["file_type"] == FileExtensions.FASTQ.name:
            if sample_data[sample_id]["sample_type"] == Sampletypes.NORMAL.value:
                normal_pair = sample_data[sample_id]["files"]
                fastq_pairs["normal_pairs"].append(normal_pair)
            elif sample_data[sample_id]["sample_type"] == Sampletypes.TUMOR.value:
                tumor_pair = sample_data[sample_id]["files"]
                fastq_pairs["tumor_pairs"].append(tumor_pair)

    # Create task inputs for FASTQ analysis
    if project_type == ProjectTypes.GERMLINE_TRIO.value:
        # For trio, submit all normal samples separately
        for normal_pair in fastq_pairs["normal_pairs"]:
            task_inputs = create_dna_task_inputs(
                project_id, project_type, {"normal_pair": normal_pair}
            )
            # Submit task
            submit_dna_tasks(project_id, project_type, task_inputs)
    else:
        if len(fastq_pairs) > 0:
            # For somatic or germline, submit all normal samples together
            normal_pairs = fastq_pairs.get("normal_pairs", [])
            tumor_pairs = fastq_pairs.get("tumor_pairs", [])
            task_inputs = create_dna_task_inputs(
                project_id,
                project_type,
                {
                    "normal_pair": normal_pairs,
                    "tumor_pair": tumor_pairs,
                },
            )
            # Submit task
            submit_dna_tasks(project_id, project_type, task_inputs)

    set_project_status(project_id, ProjectStatus.RUNNING.value)


def get_sample_files(project_id: int):
    """
    Retrieves trio sample files (child, mother, father) for germline trio analysis.
    """
    all_samples = get_project_samples(project_id)
    if len(all_samples) == 0:
        set_project_stderr(project_id, "No samples found. Please provide samples.")
        set_project_status(project_id, ProjectStatus.FAILED.value)

        return None

    sample_files = defaultdict(lambda: defaultdict(dict))
    for sample in all_samples:
        sample_files[sample.id]["sample_type"] = sample.sample_type
        sample_files[sample.id]["file_type"] = sample.get_sample_file_type()

        # Get VCF files
        if sample.get_sample_file_type() == FileExtensions.VCF.name:
            sample_files[sample.id]["files"] = sample.files.first().file.path

        # Get FASTQ files
        elif sample.get_sample_file_type() == FileExtensions.FASTQ.name:
            fastq_pair = get_sample_fastq_pairs(sample.id)
            if fastq_pair:
                sample_files[sample.id]["files"] = fastq_pair
            else:
                set_project_stderr(
                    project_id,
                    f"Sample {sample.id} has an invalid FASTQ pair.",
                )
                set_project_status(project_id, ProjectStatus.FAILED.value)
                return None

    return sample_files


def create_dna_task_inputs(project_id: int, project_type: str, fastq_pairs):
    """
    Creates task input dictionary for DNA analysis.
    """
    try:
        bed_file = get_project_files(project_id, FileExtensions.BED.name)[0].file.path
    except Exception as e:
        bed_file = None

    algorithms = get_project_algorithms(project_id)
    workdir = get_project_dir(project_id)

    # Create base inputs
    base_inputs = {
        CosapDnaTaskInputs.ANALYSIS_TYPE.value: project_type,
        CosapDnaTaskInputs.WORKDIR.value: workdir,
        CosapDnaTaskInputs.BED_FILE.value: bed_file,
        CosapDnaTaskInputs.MAPPERS.value: algorithms[CosapDnaTaskInputs.MAPPERS.value],
        CosapDnaTaskInputs.VARIANT_CALLERS.value: algorithms[
            CosapDnaTaskInputs.VARIANT_CALLERS.value
        ],
        CosapDnaTaskInputs.ANNOTATION.value: algorithms[
            CosapDnaTaskInputs.ANNOTATION.value
        ],
    }

    base_inputs.update(
        {
            CosapDnaTaskInputs.NORMAL_SAMPLE.value: fastq_pairs.get("normal_pair"),
            CosapDnaTaskInputs.TUMOR_SAMPLES.value: fastq_pairs.get("tumor_pair"),
        }
    )

    return base_inputs


def submit_dna_tasks(project_id: int, project_type: str, task_inputs):
    """
    Submits DNA analysis task(s) to Celery.
    """
    if project_type == ProjectTypes.GERMLINE_TRIO.value:
        # For trio, submit a task for each family member
        for input_data in task_inputs:
            cosap_dna_task(project_id, **input_data)
    else:
        # For germline/somatic, submit a single task
        cosap_dna_task(project_id, **task_inputs)


def submit_cosap_parse_project_data(project_id: int):
    """
    Submits a COSAP parse project data task to Celery.
    """

    workdir = get_project_dir(project_id)
    results = cosap_parse_project_data_task(workdir, project_id)

    return results


def submit_cosap_annotation_task(variants: list, workdir: int, **kwargs):
    """
    Submits a COSAP annotation task to Celery.
    """

    results = cosap_annotation_task(variants, workdir, **kwargs)

    return results


def submit_vcf_parse_task(
    vcf_path: list,
    caller_type: str,
    sample_id: int,
    sample_name: str = None,
    reference_genome: str = "hg38",
):
    """
    Submits a COSAP annotation task to Celery.
    """

    results = cosap_parse_vcf_task(
        vcf_path=vcf_path,
        caller_type=caller_type,
        sample_name=sample_name,
        sample_id=sample_id,
        reference_genome=reference_genome,
    )

    return results
