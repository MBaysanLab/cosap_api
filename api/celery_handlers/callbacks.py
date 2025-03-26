import json
import logging
import os
from tempfile import NamedTemporaryFile
from typing import Any

from cosap_api.celery import celery_app

from ..constants import ParseProjectResultsKeys, ProjectStatus
from ..helpers.project_helpers import (
    create_project_snvs,
    get_project_dir,
    set_project_status,
    update_project_summary,
    update_project_variant_stats,
)
from ..helpers.sample_helpers import handle_parse_vcf_results_for_sample
from ..helpers.variant_helpers import (
    get_non_annotated_variants,
    handle_annotation_results,
)
from common.utils import read_message_file, write_message_file, delete_message_file

from ..models import Project, ProjectSample

logger = logging.getLogger(__name__)


def update_samples_project_status(
    sample_id: str, status: ProjectStatus, result: dict[str, Any]
) -> None:
    """
    Update project status and output information.

    Args:
        project_id: The ID of the project to update
        status: The new status to set
        result: Dictionary containing stderr and stdout
    """
    try:
        project_id = (
            ProjectSample.objects.filter(samples__sample_id__iexact=sample_id)
            .values_list("project_id", flat=True)
            .first()
        )
        project = Project.objects.get(id=project_id)
        project.status = status.value
        project.stderr = result.get("stderr", "")
        project.stdout = result.get("stdout", "")
        project.save()

        logger.info(
            f"Updated project {project_id} status to {status.value}",
            extra={
                "project_id": project_id,
                "status": status.value,
                "returncode": result.get("returncode"),
            },
        )
    except Project.DoesNotExist:
        logger.error(
            f"Failed to update project {project_id}: Project not found",
            extra={"project_id": project_id},
        )
    except Exception as e:
        logger.error(
            f"Error updating project {project_id}: {str(e)}",
            extra={"project_id": project_id, "error": str(e)},
        )


@celery_app.task
def on_dna_pipeline_task_success(result, **kwargs):
    """
    Handles the results of the COSAP DNA pipeline task.
    """

    project_id = kwargs.get("project_id")

    status = (
        ProjectStatus.COMPLETED
        if result.get("returncode") == 0
        else ProjectStatus.FAILED
    )
    update_samples_project_status(project_id, status, result)


@celery_app.task
def on_dna_pipeline_task_failure(result, **kwargs):
    """
    Handles the failure of the COSAP DNA pipeline task.
    """

    project_id = kwargs.get("project_id")
    update_samples_project_status(project_id, ProjectStatus.FAILED, result)


@celery_app.task
def on_parse_task_success(result, **kwargs):
    """
    Handles the success of the parse project task.
    """

    project_id = kwargs.get("project_id")
    variants_json = result.get(ParseProjectResultsKeys.VARIANTS.value)
    qc_results = result.get(ParseProjectResultsKeys.QC_RESULTS.value)
    msi_score = result.get(ParseProjectResultsKeys.MSI_SCORE.value)

    with open(variants_json, "r") as v_json:
        variants = json.load(v_json)

    update_project_summary(project_id, qc_results, msi_score)
    create_project_snvs(project_id, variants)

    non_annotated_variants = get_non_annotated_variants(variants)
    if non_annotated_variants:
        from ..helpers.task_helpers import submit_cosap_annotation_task

        workdir = os.path.dirname(variants_json)
        with NamedTemporaryFile(
            mode="w", delete=False, suffix=".json", dir=workdir
        ) as f:
            json.dump(non_annotated_variants, f)
            json_path = f.name

        submit_cosap_annotation_task(json_path, project_id)
    else:
        update_project_variant_stats(project_id)
        set_project_status(project_id, ProjectStatus.COMPLETED.value)


@celery_app.task
def on_parse_task_failure(result, **kwargs):
    """
    Handles the failure of the parse project task.
    """

    project_id = kwargs.get("project_id")
    update_samples_project_status(project_id, ProjectStatus.FAILED, result)


@celery_app.task
def on_parse_vcf_task_success(result, **kwargs):

    sample_id = kwargs.get("sample_id")

    variants = read_message_file(result)
    handle_parse_vcf_results_for_sample(variants, sample_id)

    non_annotated_variants = get_non_annotated_variants(variants)

    if non_annotated_variants:
        from ..helpers.task_helpers import submit_cosap_annotation_task

        non_annotated_variants_path = write_message_file(non_annotated_variants)
        submit_cosap_annotation_task(non_annotated_variants_path, workdir=None)
        update_samples_project_status(sample_id, ProjectStatus.ANNOTATING.value)
    else:
        delete_message_file(result)


@celery_app.task
def on_parse_vcf_task_failure(result, **kwargs):
    """
    Handles the failure of the parse VCF task.
    """

    sample_id = kwargs.get("sample_id")
    update_samples_project_status(sample_id, ProjectStatus.FAILED, result)


@celery_app.task
def on_annotation_task_success(result, **kwargs):
    """
    Handles the results of the COSAP annotation task.
    """

    annotated_variants = read_message_file(result)

    handle_annotation_results(annotated_variants)
    # delete_message_file(result)
    update_samples_project_status(
        kwargs.get("project_id"), ProjectStatus.COMPLETED, result
    )


@celery_app.task
def on_annotation_task_failure(result, **kwargs):
    """
    Handles the failure of the COSAP annotation task.
    """

    project_id = kwargs.get("project_id")
    update_samples_project_status(project_id, ProjectStatus.FAILED, result)
