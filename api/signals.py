import os
import shutil
from pathlib import PurePosixPath

from django.conf import settings
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver
from django_drf_filepond.models import TemporaryUpload, TemporaryUploadChunked
from rest_framework.authtoken.models import Token

from .constants import FileExtensions, ProjectStatus
from .helpers.model_helpers import get_updated_model_fields
from .helpers.project_helpers import get_project_dir, project_files_ready
from .helpers.task_helpers import (submit_cosap_parse_project_data,
                                   submit_cosap_annotation_task,
                                   submit_cosap_dna_task)
from .helpers.user_helpers import get_user_files_dir
from .models import Action, File, Project, Report
from common.utils import remove_dir

ACTION_TYPE_PROJECT_CREATED = "PC"
ACTION_TYPE_FILE_UPLOADED = "FU"
ACTION_TYPE_REPORT_CREATED = "RC"

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_auth_token(sender, instance=None, created=False, **kwargs):
    """
    Creates auth token when a user is created.
    """
    if created:
        Token.objects.create(user=instance)


@receiver(post_delete, sender=File)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    """
    Deletes file from filesystem
    when corresponding `File` object is deleted.
    """
    if instance.file:
        if os.path.isfile(instance.file.path):
            os.remove(instance.file.path)


@receiver(pre_delete, sender=Project)
def auto_delete_project_dir_on_delete(sender, instance, **kwargs):
    """
    Deletes project directory from filesystem
    when corresponding `Project` object is deleted.
    """
    project_dir = get_project_dir(instance.id)
    remove_dir(project_dir)


@receiver(post_save, sender=File)
def auto_extract_file_extension(sender, instance, created, **kwargs):
    """
    Extracts file extension from file name.
    """
    if instance.name:
        path = PurePosixPath(instance.name)
        suffixes = [suffix[1:] for suffix in path.suffixes]

        extensions_dict = {
            member.name: member.value for member in FileExtensions.__members__.values()
        }
        found_type = FileExtensions.UNKNOWN.value
        for file_type, extensions in extensions_dict.items():
            if set(extensions).intersection(suffixes):
                found_type = file_type
                break

        File.objects.filter(id=instance.id).update(file_type=found_type)


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
    except File.DoesNotExist:
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

    if instance.is_draft:
        return
    
    if created:
        if project_files_ready(instance.id):
            submit_cosap_dna_task(instance.id)


@receiver(post_save, sender=Project)
def submit_cosap_parse_project_data_job(sender, instance, created, **kwargs):
    """
    Submit COSAP parse project data job when project is updated.
    """
    if not created:
        updated_fields = get_updated_model_fields(Project, instance, ["status"])
        if "status" in updated_fields and instance.status == ProjectStatus.PARSING.value:
            submit_cosap_parse_project_data(instance.id)
        elif "status" in updated_fields and instance.status == ProjectStatus.PENDING.value:
            submit_cosap_dna_task(instance.id)