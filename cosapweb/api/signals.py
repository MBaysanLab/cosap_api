import os
import shutil
from pathlib import PurePosixPath

from django.conf import settings
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django_drf_filepond.models import TemporaryUpload, TemporaryUploadChunked
from rest_framework.authtoken.models import Token

from .constants import FileExtensions, ProjectStatus
from .helpers.model_helpers import get_updated_model_fields
from .helpers.project_helpers import get_project_dir, project_files_ready
from .helpers.task_helpers import (subbmit_cosap_parse_project_data,
                                   submit_cosap_annotation_task,
                                   submit_cosap_dna_task)
from .helpers.user_helpers import get_user_files_dir
from .models import Action, File, Project, Report


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


@receiver(post_delete, sender=Project)
def auto_delete_project_dir_on_delete(sender, instance, **kwargs):
    """
    Deletes project directory from filesystem
    when corresponding `Project` object is deleted.
    """
    project_dir = get_project_dir(instance)
    if os.path.isdir(project_dir):
        shutil.rmtree(project_dir)


@receiver(post_save, sender=File)
def auto_extract_file_extension(sender, instance, created, **kwargs):
    """
    Extracts file extension from file name.
    """

    if instance.name:
        path = PurePosixPath(instance.name)
        # Extrant suffix and remove leading dot
        suffixes = path.suffixes
        suffixes = [suffix[1:] for suffix in suffixes]

        extensions_dict = {
            member.name: member.value for member in FileExtensions.__members__.values()
        }
        for file_type, extensions in extensions_dict.items():
            if len(set(extensions).intersection(set(suffixes))) > 0:
                found_type = file_type
                break
            else:
                found_type = FileExtensions.UNKNOWN.value

        # Update file object to prevent signal loop
        File.objects.filter(id=instance.id).update(file_type=found_type)


@receiver(post_save, sender=Project)
@receiver(post_save, sender=File)
@receiver(post_save, sender=Report)
def auto_create_action(sender, instance, created, **kwargs):
    if not created:
        return

    if isinstance(instance, Project):
        action_type = "PC"
    elif isinstance(instance, File):
        action_type = "FU"
    elif isinstance(instance, Report):
        action_type = "RC"

    action_obj = Action.objects.create(
        associated_user=instance.user,
        action_type=action_type,
        action_detail=instance.__str__(),
    )
    action_obj.save()


@receiver(post_delete, sender=TemporaryUploadChunked)
def save_tmp_upload(sender, instance, **kwargs):
    """
    Waits for last post and saves temporary upload to the file system.
    """

    tmp_id = instance.upload_id
    tu = TemporaryUpload.objects.get(upload_id=tmp_id)
    upload_file_name = tu.upload_name

    fl = File.objects.get(uuid=tmp_id)

    permanent_file_path = os.path.join(
        get_user_files_dir(fl.user), f"{fl.id}_{upload_file_name}"
    )
    shutil.move(tu.get_file_path(), permanent_file_path)

    fl.name = upload_file_name
    fl.file = permanent_file_path
    fl.save()


# Submit COSAP DNA job when project is created and parse project data when project is updated.
@receiver(post_save, sender=Project)
def submit_cosap_dna_job(sender, instance, created, **kwargs):

    # Submit COSAP DNA job when project is created
    if created:
        if project_files_ready(instance.id):
            submit_cosap_dna_task(instance.id)


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

@receiver(post_save, sender=Project)
def submit_cosap_parse_project_data_job(sender, instance, created, **kwargs):
    """
    Creates project directory when a project is created.
    """
    if not created:
        updated_fields = get_updated_model_fields(Project, instance, ["status"])
        if "status" in updated_fields and instance.status == ProjectStatus.PARSING.value:
            subbmit_cosap_parse_project_data(instance.id)