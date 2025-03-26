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
from ..models import Project, ProjectFile
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
    sample_data = get_sample_files_for_project_type(project_id, project_type)
    if sample_data is None:
        logger.error("Failed to get sample data for project.")
        return

    for sample_id in sample_data:
        for vcf_file in sample_data[sample_id][FileExtensions.VCF.name]:
            logger.info(f"Submitting VCF parse task for sample {sample_id}")
            # Submit VCF parse task
            submit_vcf_parse_task(
                vcf_path=vcf_file,
                sample_name=None,
                caller_type=None,
                sample_id=sample_id,
            )

    # # Create task inputs for FASTQ analysis
    # task_inputs = create_dna_task_inputs(project_id, project_type, sample_data)

    # # Submit task based on project type
    # submit_dna_tasks(project_id, project_type, task_inputs)

    # # Set project status to running
    # set_project_status(project_id, ProjectStatus.RUNNING.value)


def get_sample_files_for_project_type(project_id: int, project_type: str):
    """
    Validates and retrieves sample data for the given project type.
    Returns None if validation fails, otherwise returns sample data.
    """
    if project_type == ProjectTypes.GERMLINE.value:
        return get_germline_samples(project_id)
    elif project_type == ProjectTypes.SOMATIC.value:
        return get_somatic_samples(project_id)
    elif project_type == ProjectTypes.GERMLINE_TRIO.value:
        return get_trio_sample_files(project_id)
    else:
        logger.error(f"Invalid project type: {project_type}")
        set_project_status(project_id, ProjectStatus.FAILED.value)
        return None


def get_germline_samples(project_id: int):
    """
    Retrieves normal sample files for germline analysis.
    """
    all_samples = get_project_samples(project_id)
    if len(all_samples) == 0:
        set_project_stderr(project_id, "No samples found. Please provide samples.")
        set_project_status(project_id, ProjectStatus.FAILED.value)

        return None

    sample_files = defaultdict(lambda: defaultdict(list))
    for sample in all_samples:
        sample_files[sample.id][sample.get_sample_file_type()].extend(
            [file.file.path for file in sample.files.all()]
        )

    return sample_files


def get_somatic_samples(project_id: int):
    """
    Retrieves tumor and normal sample files for somatic analysis.
    """
    all_samples = get_project_samples(project_id)
    if len(all_samples) == 0:
        set_project_stderr(project_id, "No samples found. Please provide samples.")
        set_project_status(project_id, ProjectStatus.FAILED.value)

        return None

    sample_files = defaultdict(lambda: defaultdict(list))
    for sample in all_samples:
        sample_files[sample.id][sample.get_sample_file_type()].extend(
            [file.file.path for file in sample.files.all()]
        )


def get_trio_sample_files(project_id: int):
    """
    Retrieves trio sample files (child, mother, father) for germline trio analysis.
    """
    all_samples = get_project_samples(project_id)
    if len(all_samples) == 0:
        set_project_stderr(project_id, "No samples found. Please provide samples.")
        set_project_status(project_id, ProjectStatus.FAILED.value)

        return None

    sample_files = defaultdict(lambda: defaultdict(list))
    for sample in all_samples:
        sample_files[sample.id][sample.get_sample_file_type()].extend(
            [file.file.path for file in sample.files.all()]
        )

    return sample_files


def create_dna_task_inputs(project_id: int, project_type: str, sample_data):
    """
    Creates task input dictionary for DNA analysis.
    """
    bed_file = get_project_files(project_id, FileExtensions.BED.value)[0].file.path
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

    if project_type in [ProjectTypes.GERMLINE.value, ProjectTypes.SOMATIC.value]:
        base_inputs.update(
            {
                CosapDnaTaskInputs.NORMAL_SAMPLE.value: sample_data.get("normal_pair"),
                CosapDnaTaskInputs.TUMOR_SAMPLES.value: sample_data.get("tumor_pair"),
            }
        )
        return base_inputs
    elif project_type == ProjectTypes.GERMLINE_TRIO.value:
        # For trio, we'll return a list of task inputs, one for each family member
        trio_inputs = []
        for member_pair in [
            sample_data.get("child_pair"),
            sample_data.get("father_pair"),
            sample_data.get("mother_pair"),
        ]:
            member_input = base_inputs.copy()
            member_input.update(
                {
                    CosapDnaTaskInputs.NORMAL_SAMPLE.value: member_pair,
                    CosapDnaTaskInputs.TUMOR_SAMPLES.value: None,
                }
            )
            trio_inputs.append(member_input)
        return trio_inputs

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


def submit_cosap_annotation_task(variants: list, workdir: int):
    """
    Submits a COSAP annotation task to Celery.
    """

    results = cosap_annotation_task(variants, workdir)

    return results


def submit_vcf_parse_task(
    vcf_path: list,
    caller_type: str,
    sample_id: int,
    sample_name: str = None,
):
    """
    Submits a COSAP annotation task to Celery.
    """

    results = cosap_parse_vcf_task(
        vcf_path=vcf_path,
        caller_type=caller_type,
        sample_name=sample_name,
        sample_id=sample_id,
    )

    return results
