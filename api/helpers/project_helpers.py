import os

import warnings

from django.db.models import Q

from ..constants import (
    CosapDnaTaskInputs,
    ProjectAlgorithmKeys,
    ProjectTypes,
)
from ..models import (
    Project,
    ProjectFile,
    SampleSmallVariantData,
    SampleSmallVariant,
    ProjectSummary,
    Sample,
    ProjectSample,
    VariantAnnotation
)
from .file_helpers import wait_file_update_complete
from .user_helpers import get_user_dir


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


def get_primary_sample(project):
    """
    Get the primary sample for analysis based on project type.

    Args:
        project: Project instance

    Returns:
        Sample instance or None if not found

    Raises:
        ProjectSample.DoesNotExist: If no ProjectSample exists for the project
    """
    try:
        project_samples = ProjectSample.objects.get(project=project)
    except ProjectSample.DoesNotExist:
        raise

    if project.project_type == ProjectTypes.GERMLINE.value:
        sample = project_samples.samples.first()
        if not sample:
            return None

    elif project.project_type == ProjectTypes.SOMATIC.value:
        sample = project_samples.samples.filter(sample_type=Sample.TUMOR).first()
        if not sample:
            return None

    elif project.project_type == ProjectTypes.GERMLINE_TRIO.value:
        # Get the proband (child) sample that has mother or father relationships
        sample = project_samples.samples.filter(
            Q(mother__isnull=False) | Q(father__isnull=False)
        ).first()
        if not sample:
            return None

    else:
        return None

    return sample


def update_project_variant_stats(project_id):
    """
    Calculates variant stats for a project and saves them to database.
    """

    project_summary = get_or_create_project_summary(project_id)
    project = Project.objects.get(id=project_id)
    project_samples = ProjectSample.objects.get(project=project)

    number_of_significant_variants = 0
    number_of_vus = 0
    number_of_total_variants = 0
    for sample in project_samples.samples.all():
        sample_snvs = SampleSmallVariant.objects.get(sample=sample).variants.all()
        snv_variant_annotations = VariantAnnotation.objects.filter(
            variant__in=sample_snvs
        )
        significant_snvs = snv_variant_annotations.filter(
            Q(intervar_classification__icontains="strong")
            | Q(intervar_classification__icontains="potential")
            | Q(intervar_classification__icontains="pathogenic")
            | Q(cancervar_classification__icontains="strong")
            | Q(cancervar_classification__icontains="potential")
            | Q(cancervar_classification__icontains="pathogenic")
        )
        uncertain_snvs = snv_variant_annotations.filter(
            Q(intervar_classification__icontains="uncertain")
            | Q(cancervar_classification__icontains="uncertain")
        )
        number_of_significant_variants += significant_snvs.count()
        number_of_vus += uncertain_snvs.count()
        number_of_total_variants += sample_snvs.count()

    project_summary.number_of_significant_variants = number_of_significant_variants
    project_summary.number_of_vus = number_of_vus
    project_summary.number_of_variants = number_of_total_variants

    project_summary.save()


def get_project_samples(project_id, sample_type=None):
    """
    Returns project samples.
    """

    project = Project.objects.get(id=project_id)

    try:
        project_samples = ProjectSample.objects.get(project=project)
    except ProjectSample.DoesNotExist:
        raise Exception("Project samples do not exist.")

    if sample_type:
        samples = list(project_samples.samples.filter(sample_type=sample_type))
    else:
        samples = list(project_samples.samples.all())

    return samples


def get_project_files(project_id, file_type=None):
    project = Project.objects.get(id=project_id)
    try:
        project_file_obj = ProjectFile.objects.get(project=project)
    except ProjectFile.DoesNotExist:
        return None

    try:
        if file_type:
            files = list(project_file_obj.files.filter(file_type=file_type))
        else:
            files = list(project_file_obj.files.all())
    except ProjectFile.DoesNotExist:
        return None

    return files


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


def are_project_files_ready(project_id):
    """
    Waits for project files to be ready.
    """

    project = Project.objects.get(id=project_id)

    try:
        project_files = ProjectFile.objects.get(project=project)
    except ProjectFile.DoesNotExist:
        warnings.warn("The project does not have any files.")
        return False

    try:
        project_samples = ProjectSample.objects.get(project=project)
    except ProjectSample.DoesNotExist:
        warnings.warn("The project does not have any samples.")
        return False

    all_files = list(project_files.files.all()) + [
        sample.file for sample in project_samples.samples.all()
    ]

    return all([wait_file_update_complete(file.file.path) for file in all_files])


def update_project_summary(project_id, qc_results=None, msi_score=None):
    """
    Updates project summary with qc_results and msi_score.
    """

    project_summary = get_or_create_project_summary(project_id)

    if qc_results:
        project_summary.mapped_reads = qc_results["mapped_reads_percent"]
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
    try:
        project = Project.objects.get(id=project_id)
        project_snvs = SampleSmallVariant.objects.get(project=project)
        project_summary = ProjectSummary.objects.get(project=project)
        project_snv_data = SampleSmallVariantData.objects.get(project=project)

        project_snvs.delete()
        project_summary.delete()
        project_snv_data.delete()
    except Project.DoesNotExist:
        print(f"Project with id {project_id} does not exist.")
    except SampleSmallVariant.DoesNotExist:
        print(f"ProjectSNVs for project id {project_id} does not exist.")
    except ProjectSummary.DoesNotExist:
        print(f"ProjectSummary for project id {project_id} does not exist.")
    except SampleSmallVariantData.DoesNotExist:
        print(f"ProjectSNVData for project id {project_id} does not exist.")
    except Exception as e:
        print(f"An error occurred: {e}")


def add_sample_to_project(project_samples, sample_id):
    """
    Adds sample to project.
    """

    if not sample_id:
        return None

    sample = Sample.objects.get(uuid=sample_id)
    project_samples.samples.add(sample)
    return sample
