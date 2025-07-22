import os
import shutil
from pathlib import PurePosixPath

from django.conf import settings
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver
from django_drf_filepond.models import TemporaryUpload, TemporaryUploadChunked
from rest_framework.authtoken.models import Token

from common.utils import remove_dir

from .constants import FileExtensions, ProjectStatus
from .helpers.model_helpers import get_updated_model_fields
from .helpers.project_helpers import get_project_dir, are_project_files_ready
from .helpers.task_helpers import (
    submit_cosap_annotation_task,
    submit_cosap_dna_task,
    submit_cosap_parse_project_data,
)
from .helpers.user_helpers import get_user_files_dir
from .models import Action, File, Project, Report
from .metrics import (
    user_creation_total,
    project_creation_total,
    file_upload_total,
    report_creation_total,
    cosap_dna_job_submissions_total,
    cosap_parse_job_submissions_total,
    project_status_changes_total,
    project_deletion_total,
    file_deletion_total,
    temp_upload_completion_total,
    active_projects_count,
)
import logging

ACTION_TYPE_PROJECT_CREATED = "PC"
ACTION_TYPE_FILE_UPLOADED = "FU"
ACTION_TYPE_REPORT_CREATED = "RC"

logger = logging.getLogger(__name__)

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_auth_token(sender, instance=None, created=False, **kwargs):
    """
    Creates auth token when a user is created.
    """
    if created:
        Token.objects.create(user=instance)
        # Increment user creation metric
        user_creation_total.inc()


@receiver(post_delete, sender=File)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    """
    Deletes file from filesystem
    when corresponding `File` object is deleted.
    """
    if instance.file:
        if os.path.isfile(instance.file.path):
            os.remove(instance.file.path)
    
    # Increment file deletion metric
    file_deletion_total.inc()


@receiver(pre_delete, sender=Project)
def auto_delete_project_dir_on_delete(sender, instance, **kwargs):
    """
    Deletes project directory from filesystem
    when corresponding `Project` object is deleted.
    """
    project_dir = get_project_dir(instance.id)
    remove_dir(project_dir)
    
    # Increment project deletion metric
    project_deletion_total.inc()
    
    # Update active projects count - use actual project_type values
    project_type = instance.project_type if instance.project_type else 'unknown'
    active_projects_count.labels(project_type=project_type).set(Project.objects.filter(is_draft=False).count())


@receiver(post_save, sender=Project)
@receiver(post_save, sender=File)
@receiver(post_save, sender=Report)
def auto_create_action(sender, instance, created, **kwargs):
    if not created:
        return

    action_type = {
        Project: ACTION_TYPE_PROJECT_CREATED,
        File: ACTION_TYPE_FILE_UPLOADED,
        Report: ACTION_TYPE_REPORT_CREATED,
    }.get(type(instance))

    if action_type:
        Action.objects.create(
            associated_user=instance.user,
            action_type=action_type,
            action_detail=str(instance),
        )

    # Update metrics based on instance type
    if isinstance(instance, Project):
        status = 'draft' if instance.is_draft else 'active'
        user_type = 'admin' if instance.user.is_staff else 'regular'
        project_creation_total.labels(status=status, user_type=user_type).inc()
        # Update active projects count - use actual project_type values
        project_type = instance.project_type if instance.project_type else 'unknown'
        active_projects_count.labels(project_type=project_type).set(Project.objects.filter(is_draft=False).count())
    elif isinstance(instance, File):
        file_ext = instance.name.split('.')[-1] if instance.name and '.' in instance.name else 'unknown'
        # Determine file type based on extension
        file_type = 'vcf' if file_ext.lower() in ['vcf'] else 'fastq' if file_ext.lower() in ['fastq', 'fq'] else 'other'
        file_upload_total.labels(file_extension=file_ext, file_type=file_type).inc()
    elif isinstance(instance, Report):
        report_type = 'standard'  # You may want to determine this based on actual report type
        report_creation_total.labels(report_type=report_type).inc()


@receiver(post_delete, sender=TemporaryUploadChunked)
def save_tmp_upload(sender, instance, **kwargs):
    """
    Waits for last post and saves temporary upload to the file system.
    """
    tmp_id = instance.upload_id
    tu, created = TemporaryUpload.objects.get_or_create(upload_id=tmp_id)
    upload_file_name = tu.upload_name

    try:
        fl = File.objects.get(uuid=tmp_id)
        permanent_file_path = os.path.join(
            get_user_files_dir(fl.user), f"{fl.id}_{upload_file_name}"
        )
        shutil.move(tu.get_file_path(), permanent_file_path)

        fl.name = upload_file_name
        fl.file = permanent_file_path
        fl.is_draft = False
        fl.save()
        
        # Increment successful temp upload completion
        temp_upload_completion_total.labels(status='success').inc()
    except File.DoesNotExist:
        # Increment failed temp upload completion
        temp_upload_completion_total.labels(status='failure').inc()
        pass


@receiver(post_save, sender=Project)
def create_project_dir(sender, instance, created, **kwargs):
    """
    Creates project directory when a project is created.
    """
    if created:
        project_dir = get_project_dir(instance.id)
        if not os.path.isdir(project_dir):
            os.makedirs(project_dir)


@receiver(post_save, sender=Project)
def create_project_summary(sender, instance, created, **kwargs):
    """
    Creates project summary when a project is created.
    """
    if created:
        from .models import ProjectSummary

        ProjectSummary.objects.create(project=instance)


# Submit COSAP DNA job when project is created.
@receiver(post_save, sender=Project)
def submit_cosap_dna_job(sender, instance, created, **kwargs):
    # Submit COSAP DNA job when project is created
    logger.info(f"Project {instance.id} created. Submitting COSAP DNA job.")
    if instance.is_draft:
        return

    if created:
        if are_project_files_ready(instance.id):
            submit_cosap_dna_task(instance.id)
            # Increment successful DNA job submission - use actual project_type values
            project_type = instance.project_type if instance.project_type else 'unknown'
            cosap_dna_job_submissions_total.labels(status='submitted', project_type=project_type).inc()
        else:
            logger.info(
                f"Project {instance.id} files are not ready. Skipping COSAP DNA job."
            )
            # Increment skipped DNA job submission - use actual project_type values
            project_type = instance.project_type if instance.project_type else 'unknown'
            cosap_dna_job_submissions_total.labels(status='skipped', project_type=project_type).inc()


@receiver(post_save, sender=Project)
def submit_cosap_parse_project_data_job(sender, instance, created, **kwargs):
    """
    Submit COSAP parse project data job when project is updated.
    """
    if not created:
        updated_fields = get_updated_model_fields(Project, instance, ["status"])
        if (
            "status" in updated_fields
            and instance.status == ProjectStatus.PARSING.value
        ):
            submit_cosap_parse_project_data(instance.id)
            # Increment parse job submission
            cosap_parse_job_submissions_total.labels(status='success').inc()
            
            # Track status change
            old_status = getattr(instance, '_original_status', 'unknown')
            project_status_changes_total.labels(
                from_status=old_status, 
                to_status=ProjectStatus.PARSING.value
            ).inc()
        elif (
            "status" in updated_fields
            and instance.status == ProjectStatus.PENDING.value
        ):
            submit_cosap_dna_task(instance.id)
            # Increment DNA job submission - use actual project_type values
            project_type = instance.project_type if instance.project_type else 'unknown'
            cosap_dna_job_submissions_total.labels(status='submitted', project_type=project_type).inc()
            
            # Track status change
            old_status = getattr(instance, '_original_status', 'unknown')
            project_status_changes_total.labels(
                from_status=old_status, 
                to_status=ProjectStatus.PENDING.value
            ).inc()


@receiver(post_save, sender=Project)
def track_project_status_changes(sender, instance, created, **kwargs):
    """
    Track project status changes for metrics.
    """
    if not created and hasattr(instance, '_original_status'):
        old_status = instance._original_status
        new_status = instance.status
        if old_status != new_status:
            project_status_changes_total.labels(
                from_status=old_status, 
                to_status=new_status
            ).inc()
