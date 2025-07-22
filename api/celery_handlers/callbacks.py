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
from ..metrics import (
    project_status_changes_total,
    cosap_dna_job_submissions_total,
    cosap_parse_job_submissions_total,
    cosap_annotation_job_submissions_total,
    file_processing_duration,
    cosap_job_duration,
    task_errors_total,
    cosap_queue_size,
    pending_jobs_count
)
import time

from ..models import Project, ProjectSample
from cosap_api.settings import ANNOTATE_VARIANTS

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
    project_id: str, status: ProjectStatus, result = None
) -> None:
    """
    Update project status and output information.

    Args:
        project_id: The ID of the project to update
        status: The new status to set
        result: Dictionary, string error message, or Celery result object
    """
    if result is None:
        result = {}
    
    # Handle different result types
    if isinstance(result, str):
        result_dict = {"stderr": result, "returncode": 1}
    elif hasattr(result, 'result') and hasattr(result, 'traceback'):
        # Celery task result object
        stderr_parts = []
        if result.result:
            stderr_parts.append(f"Error: {str(result.result)}")
        if result.traceback:
            stderr_parts.append(f"Traceback: {result.traceback}")
        
        result_dict = {
            "stderr": "\n".join(stderr_parts) if stderr_parts else "Task failed",
            "returncode": 1
        }
    elif isinstance(result, dict):
        result_dict = result
    else:
        result_dict = {"stderr": str(result), "returncode": 1}
    
    logger.info("Result dictionary for project update: %s", result_dict)
        
    try:
        project = Project.objects.get(id=project_id)
        old_status = project.status
        # Handle both enum and string values
        new_status = status.value if hasattr(status, 'value') else status
        project.status = new_status
        project.stderr = result_dict.get("stderr", "")
        project.stdout = result_dict.get("stdout", "")
        project.save()

        # Track status changes
        if old_status != new_status:
            project_status_changes_total.labels(
                from_status=old_status,
                to_status=new_status
            ).inc()

        logger.info(
            f"Updated project {project_id} status to {new_status}",
            extra={
                "project_id": project_id,
                "status": new_status,
                "returncode": result_dict.get("returncode"),
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
    start_time = time.time()
    
    project_id = kwargs.get("project_id")
    if not project_id:
        logger.error("Missing project_id in task kwargs")
        return

    status = (
        ProjectStatus.COMPLETED
        if result.get("returncode") == 0
        else ProjectStatus.FAILED
    )
    
    # Track DNA job completion with enhanced labels
    project_type = kwargs.get("project_type", "unknown")
    cosap_dna_job_submissions_total.labels(
        status='success' if status == ProjectStatus.COMPLETED else 'failed',
        project_type=project_type
    ).inc()
    
    # Track job duration
    duration = time.time() - start_time
    cosap_job_duration.labels(job_type='dna').observe(duration)
    
    update_project_status(project_id, status, result)


@celery_app.task
@handle_task_errors
def on_dna_pipeline_task_failure(task_id, **kwargs):
    """
    Handles the failure of the COSAP DNA pipeline task.
    """
    result = celery_app.AsyncResult(task_id)
    project_id = kwargs.get("project_id")
    if not project_id:
        logger.error("Missing project_id in task kwargs")
        return
    
    # Track DNA job failure
    cosap_dna_job_submissions_total.labels(status='failed').inc()
        
    update_project_status(project_id, ProjectStatus.FAILED, result)


@celery_app.task
@handle_task_errors
def on_parse_task_success(result, **kwargs):
    """
    Handles the success of the parse project task.
    """
    start_time = time.time()
    project_id = kwargs.get("project_id")
    
    try:
        # Track parse job success
        cosap_parse_job_submissions_total.labels(status='success').inc()
        
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
        
        # Track job duration
        duration = time.time() - start_time
        cosap_job_duration.labels(job_type='parse').observe(duration)
        
    except Exception as e:
        # Track errors for Grafana error dashboards
        task_errors_total.labels(task_type='parse', error_type=type(e).__name__).inc()
        cosap_parse_job_submissions_total.labels(status='failed').inc()
        
        logger.error(f"Error processing parse task results: {str(e)}", 
                    extra={"project_id": project_id, "error": str(e)})
        update_project_status(project_id, ProjectStatus.FAILED, 
                            {"stderr": str(e)})


@celery_app.task
@handle_task_errors
def on_parse_task_failure(task_id, **kwargs):
    """
    Handles the failure of the parse project task.
    """
    result = celery_app.AsyncResult(task_id)
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
        task_errors_total.labels(task_type='parse_vcf', error_type='MissingSampleId').inc()
        return

    project_id = None
    try:
        # Read variants from result file
        variants = read_message_file(result)
        if not variants:
            logger.warning(f"No variants found in result file for sample {sample_id}")
            return
            
        # Process variants for sample
        handle_parse_vcf_results_for_sample(variants, sample_id)
        
        # Get project ID
        project_id = get_samples_project_id(sample_id)
        if project_id is None:
            logger.error(f"Cannot update project status: no project found for sample {sample_id}")
            task_errors_total.labels(task_type='parse_vcf', error_type='ProjectNotFound').inc()
            return

        # Handle annotation if needed
        non_annotated_variants = get_non_annotated_variants(variants)
        
        if non_annotated_variants and ANNOTATE_VARIANTS:
            try:
                from ..helpers.task_helpers import submit_cosap_annotation_task

                non_annotated_variants_path = write_message_file(non_annotated_variants)
                
                # Track annotation job submission
                cosap_annotation_job_submissions_total.labels(status='submitted').inc()
                
                submit_cosap_annotation_task(non_annotated_variants_path, workdir=None, project_id=project_id)
                update_project_status(project_id, ProjectStatus.ANNOTATING, {})
                
            except Exception as e:
                logger.error(f"Failed to submit annotation task for project {project_id}: {str(e)}")
                cosap_annotation_job_submissions_total.labels(status='failed').inc()
                task_errors_total.labels(task_type='parse_vcf', error_type='AnnotationSubmissionFailed').inc()
                update_project_status(project_id, ProjectStatus.FAILED, {"stderr": f"Annotation submission failed: {str(e)}"})
        else:
            update_project_status(project_id, ProjectStatus.COMPLETED, {})
            
    except Exception as e:
        logger.error(f"Error in parse VCF success callback: {str(e)}", 
                    extra={"sample_id": sample_id, "project_id": project_id, "error": str(e)})
        task_errors_total.labels(task_type='parse_vcf', error_type=type(e).__name__).inc()
        
        if project_id:
            update_project_status(project_id, ProjectStatus.FAILED, {"stderr": f"Parse VCF callback error: {str(e)}"})
            
    finally:
        try:
            delete_message_file(result)
        except Exception as e:
            logger.warning(f"Failed to delete message file {result}: {str(e)}")


@celery_app.task
@handle_task_errors
def on_parse_vcf_task_failure(task_id, **kwargs):
    """
    Handles the failure of the parse VCF task.
    """

    result = celery_app.AsyncResult(task_id)
    sample_id = kwargs.get("sample_id")
    if not sample_id:
        logger.error("Missing sample_id in task kwargs")
        task_errors_total.labels(task_type='parse_vcf', error_type='MissingSampleId').inc()
        return
    
    try:
        project_id = get_samples_project_id(sample_id)
        if project_id is None:
            logger.error(f"Cannot update project status: no project found for sample {sample_id}")
            task_errors_total.labels(task_type='parse_vcf', error_type='ProjectNotFound').inc()
            return
            
        task_errors_total.labels(task_type='parse_vcf', error_type='TaskFailed').inc()
        update_project_status(project_id, ProjectStatus.FAILED, result)
        
    except Exception as e:
        logger.error(f"Error in parse VCF failure callback: {str(e)}", 
                    extra={"sample_id": sample_id, "error": str(e)})
        task_errors_total.labels(task_type='parse_vcf', error_type=type(e).__name__).inc()


@celery_app.task
@handle_task_errors
def on_annotation_task_success(result, **kwargs):
    """
    Handles the results of the COSAP annotation task.
    """
    project_id = kwargs.get("project_id")
    
    try:
        # Read and process annotation results
        annotated_variants = read_message_file(result)
        if not annotated_variants:
            logger.warning(f"No annotated variants found in result file for project {project_id}")
            cosap_annotation_job_submissions_total.labels(status='success').inc()
            if project_id:
                update_project_status(project_id, ProjectStatus.COMPLETED, {})
            return
            
        handle_annotation_results(annotated_variants)
        
        # Track successful annotation
        cosap_annotation_job_submissions_total.labels(status='success').inc()
        
        if project_id:
            update_project_status(project_id, ProjectStatus.COMPLETED, {})
            
    except Exception as e:
        logger.error(f"Error processing annotation results: {str(e)}", 
                    extra={"project_id": project_id, "error": str(e)})
        task_errors_total.labels(task_type='annotation', error_type=type(e).__name__).inc()
        cosap_annotation_job_submissions_total.labels(status='failed').inc()
        
        if project_id:
            update_project_status(project_id, ProjectStatus.FAILED, {"stderr": f"Annotation processing failed: {str(e)}"})
            
    finally:
        try:
            delete_message_file(result)
        except Exception as e:
            logger.warning(f"Failed to delete message file {result}: {str(e)}")


@celery_app.task
@handle_task_errors
def on_annotation_task_failure(task_id, **kwargs):
    """
    Handles the failure of the COSAP annotation task.
    """
    result = celery_app.AsyncResult(task_id)
    project_id = kwargs.get("project_id")
    if not project_id:
        logger.error("Missing project_id in task kwargs")
        task_errors_total.labels(task_type='annotation', error_type='MissingProjectId').inc()
        return
    
    try:
        task_errors_total.labels(task_type='annotation', error_type='TaskFailed').inc()
        cosap_annotation_job_submissions_total.labels(status='failed').inc()
        update_project_status(project_id, ProjectStatus.FAILED, result)
        
    except Exception as e:
        logger.error(f"Error in annotation failure callback: {str(e)}", 
                    extra={"project_id": project_id, "error": str(e)})
        task_errors_total.labels(task_type='annotation', error_type=type(e).__name__).inc()
