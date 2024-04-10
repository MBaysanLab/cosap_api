import os

from celery.result import AsyncResult
from django.db.models import Q

from ..constants import CosapDnaTaskInputs, ProjectAlgorithmKeys
from ..models import (
    SNV,
    Project,
    ProjectFiles,
    ProjectSNVs,
    ProjectSummary,
    ProjectTask,
    ProjectSNVData,
)
from .file_helpers import wait_file_update_complete
from .user_helpers import get_user_dir
from .variant_helpers import create_snv
import warnings


def set_project_status(project_id, status):
    """
    Checks project status and returns a list of variants.
    """

    Project.objects.filter(id=project_id).update(
        status=status,
    )

def set_project_stderr(project_id, stderr):
    """
    Sets project stderr.
    """

    Project.objects.filter(id=project_id).update(
        stderr=stderr,
    )

def get_project_dir(project_id):
    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        raise Exception("Project does not exist.")
    return os.path.join(get_user_dir(project.user), f"{project.id}_{project.name}")


def update_project_variant_stats(project_id):
    """
    Calculates variant stats for a project and saves them to database.
    """

    project_summary = get_or_create_project_summary(project_id)
    project = Project.objects.get(id=project_id)
    project_snvs = ProjectSNVs.objects.get(project=project)

    snvs = project_snvs.snvs.all()

    # Check if SNV's classification field contains "strong", "potential" or "pathogenic" and calculate the number of them.
    significant_snvs = snvs.filter(
        Q(intervar_classification__icontains="strong")
        | Q(intervar_classification__icontains="potential")
        | Q(intervar_classification__icontains="pathogenic")
        | Q(cancervar_classification__icontains="strong")
        | Q(cancervar_classification__icontains="potential")
        | Q(cancervar_classification__icontains="pathogenic")
    )
    uncertain_snvs = snvs.filter(
        Q(intervar_classification__icontains="uncertain")
        | Q(cancervar_classification__icontains="uncertain")
    )

    project_summary.number_of_significant_variants = len(significant_snvs)
    project_summary.number_of_vus = len(uncertain_snvs)
    project_summary.number_of_variants = len(snvs)

    project_summary.save()


def create_project_snvs(project_id, variant_list):
    """
    Takes a list of variants and submits annotation task to Celery.
    """

    project = Project.objects.get(id=project_id)
    project_snvs = ProjectSNVs.objects.get_or_create(project=project)[0]

    # Get snv list and create SNV objects. Check every field if they are in SNV model.
    for variant in variant_list:
        snv = create_snv(variant["variant_id"])
        project_snvs.snvs.add(snv)

        # Create ProjectSNVData object
        ProjectSNVData.objects.create(
            project=project,
            snv=snv,
            allele_frequency=variant.get("AF"),
            allele_depth=variant.get("AD"),
            read_depth=variant.get("DP"),
        )

    project_snvs.save()


def get_project_files(project_id, sample_type=None, file_type=None):

    project = Project.objects.get(id=project_id)
    try:
        project_file_obj = ProjectFiles.objects.get(project=project)
    except ProjectFiles.DoesNotExist:
        raise Exception("Project files are not ready.")

    if sample_type:
        project_files = project_file_obj.files.filter(sample_type=sample_type)
    elif file_type:
        project_files = project_file_obj.files.filter(file_type=file_type)
    else:
        project_files = project_file_obj.files.all()

    return project_files


def get_project_algorithms(project_id):
    """
    Returns project algorithms as a dict.
    """

    project = Project.objects.get(id=project_id)
    algorithms = project.algorithms

    return {
        CosapDnaTaskInputs.MAPPERS.value: algorithms[
            ProjectAlgorithmKeys.ALIGNER.value
        ],
        CosapDnaTaskInputs.VARIANT_CALLERS.value: algorithms[
            ProjectAlgorithmKeys.VARIANT_CALLER.value
        ],
        CosapDnaTaskInputs.ANNOTATION.value: algorithms[
            ProjectAlgorithmKeys.VARIANT_ANNOTATOR.value
        ],
    }


def get_project_type(project_id):
    """
    Returns project type.
    """

    project = Project.objects.get(id=project_id)
    return project.project_type


def project_files_ready(project_id):
    """
    Waits for project files to be ready.
    """

    project = Project.objects.get(id=project_id)

    try:
        project_files = ProjectFiles.objects.get(project=project)
    except ProjectFiles.DoesNotExist:
        warnings.warn("The project does not have any files.")
        return False
    
    return all([wait_file_update_complete(file.file.path) for file in project_files.files.all()])


def update_project_summary(project_id, qc_results=None, msi_score=None):
    """
    Updates project summary with qc_results and msi_score.
    """

    project_summary = get_or_create_project_summary(project_id)

    if qc_results:
        project_summary.mapped_reads = qc_results["percentage_aligned"]
        project_summary.mean_coverage = qc_results["mean_coverage"]

    project_summary.msi_score = msi_score

    project_summary.save()


def get_or_create_project_summary(project_id):
    """
    Returns project summary object.
    """

    project = Project.objects.get(id=project_id)
    project_summary = ProjectSummary.objects.get_or_create(project=project)[0]

    return project_summary

def remove_project_data_and_snvs(project_id):
    """
    Removes project data and snvs.
    """

    project = Project.objects.get(id=project_id)
    project_snvs = ProjectSNVs.objects.get(project=project)
    project_summary = ProjectSummary.objects.get(project=project)
    project_snv_data = ProjectSNVData.objects.get(project=project)

    project_snvs.delete()
    project_summary.delete()
    project_snv_data.delete()