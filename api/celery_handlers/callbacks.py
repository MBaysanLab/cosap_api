import json
import logging
import os
from functools import wraps
from tempfile import NamedTemporaryFile
from typing import Any

from cosap_api.celery import celery_app

from ..constants import ParseProjectResultsKeys, ProjectStatus
from ..helpers.project_helpers import (
    get_project_dir,
    set_project_status,
    update_project_summary,
    update_project_variant_stats,
    get_primary_sample
)
from ..helpers.sample_helpers import handle_parse_vcf_results_for_sample
from ..helpers.variant_helpers import (
    get_non_annotated_variants,
    handle_annotation_results,
)
from common.utils import read_message_file, write_message_file, delete_message_file

from ..models import Project, ProjectSample

logger = logging.getLogger(__name__)


def handle_task_errors(func):
    """Decorator to handle common task errors."""
    @wraps(func)
    def wrapper(result, **kwargs):
        try:
            return func(result, **kwargs)
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {str(e)}", 
                        extra={"error": str(e), "kwargs": kwargs})
            
            # Try to update project status if possible
            project_id = kwargs.get("project_id")
            if project_id:
                update_project_status(project_id, ProjectStatus.FAILED, 
                                    {"stderr": f"Callback error: {str(e)}"})
    return wrapper


def get_samples_project_id(sample_id: str) -> str:
    """
    Get the project ID for a given sample ID.

    Args:
        sample_id: The ID of the sample

    Returns:
        The project ID associated with the sample
    """
    try:
        project_sample = ProjectSample.objects.get(samples__id=sample_id)
        return project_sample.project.id
    except ProjectSample.DoesNotExist:
        logger.error(f"Sample {sample_id} does not exist.")
        return None

def update_project_status(
    project_id: str, status: ProjectStatus, result: dict[str, Any] = None
) -> None:
    """
    Update project status and output information.

    Args:
        project_id: The ID of the project to update
        status: The new status to set
        result: Dictionary containing stderr and stdout (optional)
    """
    if result is None:
        result = {}
        
    try:
        project = Project.objects.get(id=project_id)
        # Handle both enum and string values
        project.status = status.value if hasattr(status, 'value') else status
        project.stderr = result.get("stderr", "")
        project.stdout = result.get("stdout", "")
        project.save()

        logger.info(
            f"Updated project {project_id} status to {status.value if hasattr(status, 'value') else status}",
            extra={
                "project_id": project_id,
                "status": status.value if hasattr(status, 'value') else status,
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
            f"Error updating project: {str(e)}",
            extra={"error": str(e)},
        )


@celery_app.task
@handle_task_errors
def on_dna_pipeline_task_success(result, **kwargs):
    """
    Handles the results of the COSAP DNA pipeline task.
    """

    project_id = kwargs.get("project_id")
    if not project_id:
        logger.error("Missing project_id in task kwargs")
        return

    status = (
        ProjectStatus.COMPLETED
        if result.get("returncode") == 0
        else ProjectStatus.FAILED
    )
    update_project_status(project_id, status, result)


@celery_app.task
@handle_task_errors
def on_dna_pipeline_task_failure(result, **kwargs):
    """
    Handles the failure of the COSAP DNA pipeline task.
    """

    project_id = kwargs.get("project_id")
    if not project_id:
        logger.error("Missing project_id in task kwargs")
        return
        
    update_project_status(project_id, ProjectStatus.FAILED, result)


@celery_app.task
@handle_task_errors
def on_parse_task_success(result, **kwargs):
    """
    Handles the success of the parse project task.
    """

    project_id = kwargs.get("project_id")
    if not project_id:
        logger.error("Missing project_id in task kwargs")
        return
        
    try:
        variants_json = result.get(ParseProjectResultsKeys.VARIANTS.value)
        if not variants_json or not os.path.exists(variants_json):
            logger.error(f"Variants JSON file not found: {variants_json}")
            update_project_status(project_id, ProjectStatus.FAILED, 
                                {"stderr": "Variants JSON file not found"})
            return
            
        qc_results = result.get(ParseProjectResultsKeys.QC_RESULTS.value)
        msi_score = result.get(ParseProjectResultsKeys.MSI_SCORE.value)

        # Read variants using message file utility for consistency
        variants = read_message_file(variants_json)

        update_project_summary(project_id, qc_results, msi_score)
        primary_sample = get_primary_sample(Project.objects.get(id=project_id))
        if primary_sample:
            handle_parse_vcf_results_for_sample(variants, primary_sample.id)

        non_annotated_variants = get_non_annotated_variants(variants)
        if non_annotated_variants:
            from ..helpers.task_helpers import submit_cosap_annotation_task

            # Use message file utility for better file handling
            non_annotated_variants_path = write_message_file(non_annotated_variants)
            
            submit_cosap_annotation_task(non_annotated_variants_path, workdir=None, project_id=project_id)
            update_project_status(project_id, ProjectStatus.ANNOTATING, {})
        else:
            update_project_variant_stats(project_id)
            set_project_status(project_id, ProjectStatus.COMPLETED.value)
            
        # Clean up the original variants file
        delete_message_file(variants_json)
        
    except Exception as e:
        logger.error(f"Error processing parse task results: {str(e)}", 
                    extra={"project_id": project_id, "error": str(e)})
        update_project_status(project_id, ProjectStatus.FAILED, 
                            {"stderr": str(e)})


@celery_app.task
@handle_task_errors
def on_parse_task_failure(result, **kwargs):
    """
    Handles the failure of the parse project task.
    """

    project_id = kwargs.get("project_id")
    if not project_id:
        logger.error("Missing project_id in task kwargs")
        return
        
    update_project_status(project_id, ProjectStatus.FAILED, result)


@celery_app.task
@handle_task_errors
def on_parse_vcf_task_success(result, **kwargs):
    """
    Handles the success of the parse VCF task.
    """

    sample_id = kwargs.get("sample_id")
    if not sample_id:
        logger.error("Missing sample_id in task kwargs")
        return

    variants = read_message_file(result)
    handle_parse_vcf_results_for_sample(variants, sample_id)

    non_annotated_variants = get_non_annotated_variants(variants)

    if non_annotated_variants:
        from ..helpers.task_helpers import submit_cosap_annotation_task

        non_annotated_variants_path = write_message_file(non_annotated_variants)
        project_id = get_samples_project_id(sample_id)
        
        if project_id is None:
            logger.error(f"Cannot submit annotation task: no project found for sample {sample_id}")
            delete_message_file(non_annotated_variants_path)
            return
            
        submit_cosap_annotation_task(non_annotated_variants_path, workdir=None)
        update_project_status(project_id, ProjectStatus.ANNOTATING, {})
    else:
        delete_message_file(result)


@celery_app.task
@handle_task_errors
def on_parse_vcf_task_failure(result, **kwargs):
    """
    Handles the failure of the parse VCF task.
    """

    sample_id = kwargs.get("sample_id")
    if not sample_id:
        logger.error("Missing sample_id in task kwargs")
        return
        
    project_id = get_samples_project_id(sample_id)
    
    if project_id is None:
        logger.error(f"Cannot update project status: no project found for sample {sample_id}")
        return
        
    update_project_status(project_id, ProjectStatus.FAILED, result)


@celery_app.task
@handle_task_errors
def on_annotation_task_success(result, **kwargs):
    """
    Handles the results of the COSAP annotation task.
    """

    try:
        annotated_variants = read_message_file(result)
        handle_annotation_results(annotated_variants)
        
        project_id = kwargs.get("project_id")
        if project_id:
            update_project_status(project_id, ProjectStatus.COMPLETED, {})
    finally:
        # Always clean up the message file
        delete_message_file(result)


@celery_app.task
@handle_task_errors
def on_annotation_task_failure(result, **kwargs):
    """
    Handles the failure of the COSAP annotation task.
    """

    project_id = kwargs.get("project_id")
    if not project_id:
        logger.error("Missing project_id in task kwargs")
        return
        
    update_project_status(project_id, ProjectStatus.FAILED, result)
