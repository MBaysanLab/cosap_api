import os

from ...celery import celery_app
from ..constants import COSAPTasks
from .callbacks import (on_annotation_task_success,
                        on_dna_pipeline_task_complete, on_parse_success)


def cosap_dna_task(project_id, **kwargs):
    # Submit COSAP DNA pipeline job to Celery on a separate thread and wait for the result.

    task = celery_app.send_task(
        COSAPTasks.DNA_PIPELINE_TASK.value,
        kwargs=kwargs,
        link=on_dna_pipeline_task_complete.s(project_id=project_id),
        link_error=on_dna_pipeline_task_complete.s(project_id=project_id),
    )
    return task


def cosap_parse_project_data_task(path, project_id):
    """
    Sends parse project results to cosap worker and retrieve data as dict.
    """
    task = celery_app.send_task(
        COSAPTasks.PARSE_PROJECT_RESULTS.value,
        args=[path],
        link=on_parse_success.s(project_id=project_id),
    )
    return task


def cosap_annotation_task(variant_list: list, workdir: str, project_id: int = None):
    """
    Sends variant list to cosap worker and retrieve annotated variants as dict.
    """
    task = celery_app.send_task(
        COSAPTasks.ANNOTATION_TASK.value,
        args=[variant_list, workdir],
        link=on_annotation_task_success.s(project_id=project_id),
    )
    return task
