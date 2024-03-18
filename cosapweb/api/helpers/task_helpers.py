from ...common.utils import match_read_pairs
from ..celery_handlers.tasks import (cosap_annotation_task, cosap_dna_task,
                                     cosap_parse_project_data_task)
from ..constants import (CosapDnaTaskInputs, FileExtensions, ProjectTypes,
                         Sampletypes)
from ..models import Project, ProjectFiles
from .project_helpers import (get_project_algorithms, get_project_dir,
                              get_project_files, get_project_type)


def submit_cosap_dna_task(project_id: int):
    """
    Takes a Project object and submits a COSAP DNA pipeline job to Celery.
    """

    normal_files = get_project_files(project_id, sample_type=Sampletypes.NORMAL.value)
    tumor_files = get_project_files(project_id, sample_type=Sampletypes.TUMOR.value)
    bed_file = get_project_files(
        project_id, file_type=FileExtensions.BED.value[0]
    ).first()

    normal_pairs = (
        match_read_pairs([file for file in normal_files])[0] if normal_files else None
    )
    tumor_pairs = match_read_pairs([file for file in tumor_files])

    algorithms = get_project_algorithms(project_id)
    workdir = get_project_dir(project_id)
    project_type = get_project_type(project_id)

    dna_task_input = {
        CosapDnaTaskInputs.ANALYSIS_TYPE.value: (
            "somatic" if project_type == ProjectTypes.SM.value else "germline"
        ),
        CosapDnaTaskInputs.WORKDIR.value: workdir,
        CosapDnaTaskInputs.NORMAL_SAMPLE.value: normal_pairs,
        CosapDnaTaskInputs.TUMOR_SAMPLES.value: tumor_pairs,
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

    return results


def subbmit_cosap_parse_project_data(project_id: int):
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
