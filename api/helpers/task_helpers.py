from common.utils import match_read_pairs
from ..celery_handlers.tasks import (
    cosap_annotation_task,
    cosap_dna_task,
    cosap_parse_project_data_task,
    cosap_parse_vcf_task,
)
from ..constants import (
    CosapDnaTaskInputs,
    FileExtensions,
    ProjectTypes,
    Sampletypes,
    ProjectStatus,
)
from ..models import Project, ProjectFiles
from .project_helpers import (
    get_project_algorithms,
    get_project_dir,
    get_project_files,
    get_project_type,
    set_project_status,
    set_project_stderr,
)


def submit_cosap_dna_task(project_id: int):
    """
    Takes a Project object and submits a COSAP DNA pipeline job to Celery.
    """

    project_type = get_project_type(project_id)
    normal_files = get_project_files(project_id, sample_type=Sampletypes.NORMAL.value)
    tumor_files = get_project_files(project_id, sample_type=Sampletypes.TUMOR.value)
    bed_file = get_project_files(
        project_id, file_type=FileExtensions.BED.value[0]
    ).first()

    try:
        normal_pairs = (
            match_read_pairs([file for file in normal_files])[0]
            if normal_files
            else None
        )
    except Exception as e:
        set_project_stderr(project_id, e)
        # Set project status to error
        set_project_status(project_id, ProjectStatus.FAILED.value)
        return

    if project_type == ProjectTypes.SOMATIC.value:
        try:
            tumor_pairs = match_read_pairs([file for file in tumor_files])
        except Exception as e:
            set_project_stderr(project_id, e)
            # Set project status to error
            set_project_status(project_id, ProjectStatus.FAILED.value)
            return

    algorithms = get_project_algorithms(project_id)
    workdir = get_project_dir(project_id)

    dna_task_input = {
        CosapDnaTaskInputs.ANALYSIS_TYPE.value: project_type,
        CosapDnaTaskInputs.WORKDIR.value: workdir,
        CosapDnaTaskInputs.NORMAL_SAMPLE.value: normal_pairs,
        CosapDnaTaskInputs.TUMOR_SAMPLES.value: (
            tumor_pairs if project_type == ProjectTypes.SOMATIC.value else None
        ),
        CosapDnaTaskInputs.BED_FILE.value: bed_file,
        CosapDnaTaskInputs.MAPPERS.value: algorithms[CosapDnaTaskInputs.MAPPERS.value],
        CosapDnaTaskInputs.VARIANT_CALLERS.value: algorithms[
            CosapDnaTaskInputs.VARIANT_CALLERS.value
        ],
        CosapDnaTaskInputs.ANNOTATION.value: algorithms[
            CosapDnaTaskInputs.ANNOTATION.value
        ],
    }

    results = cosap_dna_task(project_id, **dna_task_input)

    # Set project status to running
    set_project_status(project_id, ProjectStatus.RUNNING.value)
    return results


def submit_cosap_parse_project_data(project_id: int):
    """
    Submits a COSAP parse project data task to Celery.
    """

    workdir = get_project_dir(project_id)
    results = cosap_parse_project_data_task(workdir, project_id)

    return results


def submit_cosap_annotation_task(variants: list, project_id: int):
    """
    Submits a COSAP annotation task to Celery.
    """

    workdir = get_project_dir(project_id)
    results = cosap_annotation_task(variants, workdir, project_id)

    return results


def submit_vcf_parse_task(vcf_path: list, caller_type: str, sample_name: str, project_id: int):
    """
    Submits a COSAP annotation task to Celery.
    """

    results = cosap_parse_vcf_task(
        vcf_path=vcf_path, caller_type=caller_type, sample_name=sample_name, project_id=project_id
    )

    return results
