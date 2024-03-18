from ...celery import celery_app
from ..constants import ParseProjectResultsKeys, ProjectStatus
from ..helpers.project_helpers import (
    create_project_snvs,
    update_project_summary,
    update_project_variant_stats,
    set_project_status,
)
from ..helpers.variant_helpers import get_non_annotated_variants, update_snv
from ..models import Project


@celery_app.task
def on_dna_pipeline_task_complete(result, **kwargs):
    """
    Handles the results of the COSAP DNA pipeline task.
    """

    project_id = kwargs.get("project_id")

    # Update the project status to "DNA pipeline completed".
    if result["returncode"] == 0:
        project = Project.objects.get(id=project_id)
        project.status = ProjectStatus.PARSING.value
        project.stderr = result["stderr"]
        project.stdout = result["stdout"]
        project.save()

    else:
        project = Project.objects.get(id=project_id)
        project.status = ProjectStatus.FAILED.value
        project.stderr = result["stderr"]
        project.stdout = result["stdout"]
        project.save()


@celery_app.task
def on_parse_success(result, **kwargs):
    """
    Handles the results of the parse project task.
    Checks if the variants are present in the database and if not, submits an annotation task.
    Saves the qc_results and msi_score to the database.
    """

    project_id = kwargs.get("project_id")
    variants = result[ParseProjectResultsKeys.VARIANTS.value]
    qc_results = result[ParseProjectResultsKeys.QC_RESULTS.value]
    msi_score = result[ParseProjectResultsKeys.MSI_SCORE.value]

    update_project_summary(project_id, qc_results, msi_score)

    missing_variants = get_non_annotated_variants(variants)

    create_project_snvs(project_id, variants)

    if missing_variants:
        from ..helpers.task_helpers import submit_cosap_annotation_task

        submit_cosap_annotation_task(missing_variants, project_id)
    else:
        update_project_variant_stats(project_id)
        set_project_status(project_id, ProjectStatus.COMPLETED.value)


@celery_app.task
def on_annotation_task_success(result, **kwargs):
    """
    Handles the results of the COSAP annotation task.
    """

    variants = result
    for variant in variants:
        snv = update_snv(variant)
        snv.save()

    if kwargs.get("project_id"):
        update_project_variant_stats(kwargs.get("project_id"))
        set_project_status(kwargs.get("project_id"), ProjectStatus.COMPLETED.value)
