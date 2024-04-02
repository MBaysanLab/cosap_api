import os
import uuid

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django_countries.fields import CountryField
from rest_framework.authtoken.models import Token


class CustomUserManager(UserManager):
    def create_user(self, username=None, email=None, password=None, **extra_fields):
        return super(CustomUserManager, self).create_user(
            username, email, password, **extra_fields
        )

    def create_superuser(
        self, username=None, email=None, password=None, **extra_fields
    ):
        return super(CustomUserManager, self).create_superuser(
            username, email, password, **extra_fields
        )

    def _create_user(self, username, email, password, **extra_fields):
        email = self.normalize_email(email)
        GlobalUserModel = apps.get_model(
            self.model._meta.app_label, self.model._meta.object_name
        )
        username = GlobalUserModel.normalize_username(username)
        user = self.model(username=username, email=email, **extra_fields)
        user.password = make_password(password)
        user.save(using=self._db)
        return user


class CustomUser(AbstractUser):
    email = models.EmailField(
        ("email address"), unique=True
    )  # changes email to unique and blank to false
    username = models.CharField(max_length=50, null=True)

    objects = CustomUserManager()

    REQUIRED_FIELDS = []
    USERNAME_FIELD = "email"


USER = get_user_model()


class Project(models.Model):

    SOMATIC = "SOMATIC"
    GERMLINE = "GERMLINE"
    PROJECT_TYPE_CHOICES = [(SOMATIC, "somatic"), (GERMLINE, "germline")]

    COMPLETED = "COMPLETED"
    RUNNING = "RUNNING"
    PARSING = "PARSING"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    PROJECT_STATUS_CHOICES = [
        (PENDING, "pending"),
        (COMPLETED, "completed"),
        (RUNNING, "running"),
        (CANCELLED, "cancelled"),
        (FAILED, "failed"),
        (PARSING, "parsing"),
    ]

    user = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL)
    collaborators = models.ManyToManyField(USER, related_name="projects", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    project_type = models.CharField(choices=PROJECT_TYPE_CHOICES, max_length=256)
    name = models.CharField(max_length=256)
    status = models.CharField(choices=PROJECT_STATUS_CHOICES, max_length=256)
    progress = models.SmallIntegerField(default=0)
    stdout = models.TextField(null=True, blank=True)
    stderr = models.TextField(null=True, blank=True)
    algorithms = models.JSONField(default=dict)
    is_demo = models.BooleanField(default=False)
    is_draft = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.id} - {self.name}"


class ProjectSummary(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    mapped_reads = models.FloatField(null=True, blank=True)
    mean_coverage = models.FloatField(null=True, blank=True)
    number_of_variants = models.IntegerField(null=True, blank=True)
    number_of_significant_variants = models.IntegerField(null=True, blank=True)
    number_of_vus = models.IntegerField(null=True, blank=True)
    msi_score = models.FloatField(null=True, blank=True)
    cnv_count = models.IntegerField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.project.name} summary"


class SNV(models.Model):
    variant_id = models.CharField(max_length=256)
    location = models.CharField(max_length=256)
    ref = models.CharField(max_length=256)
    alt = models.CharField(max_length=256)
    gene_id = models.CharField(max_length=256, null=True, blank=True)
    gene_symbol = models.CharField(max_length=256, null=True, blank=True)
    function = models.TextField(max_length=256, null=True, blank=True)
    consequence = models.TextField(max_length=256, null=True, blank=True)
    coding_consequece = models.TextField(max_length=256, null=True, blank=True)
    impact = models.TextField(max_length=256, null=True, blank=True)
    feature = models.TextField(max_length=256, null=True, blank=True)
    feature_type = models.TextField(max_length=256, null=True, blank=True)
    hgvsg = models.CharField(max_length=256, null=True, blank=True)
    hgvsc = models.CharField(max_length=256, null=True, blank=True)
    hgvsp = models.CharField(max_length=256, null=True, blank=True)
    mane_select = models.CharField(max_length=256, null=True, blank=True)
    intervar_classification = models.CharField(max_length=256, null=True, blank=True)
    cancervar_classification = models.CharField(max_length=256, null=True, blank=True)
    gnomad_af = models.FloatField(null=True, blank=True)
    aa_change = models.TextField(max_length=256, null=True, blank=True)
    existing_variation = models.CharField(max_length=256, null=True, blank=True)
    sift_score = models.CharField(max_length=256, null=True, blank=True)
    polyphen_score = models.CharField(max_length=256, null=True, blank=True)
    interpro_domain = models.TextField(max_length=256, null=True, blank=True)
    clinvar_classification = models.TextField(max_length=256, null=True, blank=True)
    clinical_significance = models.TextField(max_length=256, null=True, blank=True)
    cosmic_id = models.CharField(max_length=256, null=True, blank=True)
    evidence = models.TextField(max_length=256, null=True, blank=True)
    orpha_number = models.CharField(max_length=256, null=True, blank=True)
    orpha_info = models.TextField(max_length=256, null=True, blank=True)
    is_annotated = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.variant_id

    def save(self, *args, **kwargs):
        self.location = "_".join(
            [self.variant_id.split("_")[0], str(self.variant_id.split("_")[1])]
        )
        super(SNV, self).save(*args, **kwargs)

class ProjectSNVs(models.Model):
    project = models.ForeignKey(Project, null=True, on_delete=models.CASCADE)
    snvs = models.ManyToManyField(SNV)

    def __str__(self) -> str:
        return f"{self.project.id}_{self.project.name} - snvs"


class ProjectSNVData(models.Model):
    project = models.ForeignKey(Project, null=True, on_delete=models.CASCADE)
    snv = models.ForeignKey(SNV, null=True, on_delete=models.SET_NULL)
    allele_frequency = models.FloatField(null=True, blank=True)
    allele_depth = models.IntegerField(null=True, blank=True)
    read_depth = models.IntegerField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.project.id}_{self.project.name} - snv data"


class SV(models.Model):
    pass


class ProjectSV(models.Model):
    pass


class CNV(models.Model):
    pass


class ProjectCNV(models.Model):
    pass


class GeneFusion(models.Model):
    pass


class ProjectGeneFusion(models.Model):
    pass


def user_directory_path(instance, filename):
    return os.path.join(f"{instance.user.id}_{instance.user.email}", "files", filename)


class File(models.Model):

    TUMOR = "TUMOR"
    NORMAL = "NORMAL"
    SAMPLE_TYPES = [(TUMOR, "tumor"), (NORMAL, "normal")]

    user = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL)
    uuid = models.CharField(max_length=256, default=uuid.uuid4, editable=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=256, blank=True, null=True)
    file_type = models.CharField(max_length=64, blank=True, null=True)
    sample_type = models.CharField(
        choices=SAMPLE_TYPES, null=True, blank=True, max_length=256
    )
    file = models.FileField(upload_to=user_directory_path, max_length=256)
    is_demo = models.BooleanField(default=False)
    is_draft = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.id}-{self.name}"

    def save(self, *args, **kwargs):
        if not self.name:
            self.name = self.file.name
        super(File, self).save(*args, **kwargs)


class ProjectFiles(models.Model):
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True)
    files = models.ManyToManyField(File)

    def __str__(self):
        if self.project:
            return f"{self.project.name}_files"
        else:
            return f"{self.id}_files"


class Report(models.Model):
    user = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=256)
    report_type = models.CharField(max_length=256)

    def __str__(self):
        return self.name


class Affiliation(models.Model):
    associated_users = models.ManyToManyField(USER, related_name="affiliations")
    name = models.CharField(max_length=256)
    country = CountryField(blank=True)
    address = models.CharField(blank=True, max_length=256)

    def __str__(self):
        return self.name


class Action(models.Model):

    PROJECT_CREATION = "PC"
    FILE_UPLOAD = "FU"
    REPORT_CREATION = "RC"
    ACTION_TYPES = [
        (PROJECT_CREATION, "project_creation"),
        (FILE_UPLOAD, "file_upload"),
        (REPORT_CREATION, "report_creation"),
    ]

    associated_user = models.ForeignKey(
        USER, blank=True, null=True, on_delete=models.CASCADE, related_name="actions"
    )
    action_type = models.CharField(choices=ACTION_TYPES, max_length=2)
    action_detail = models.CharField(max_length=256, null=True, blank=True)
    created_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.action_type}_{self.action_detail}"

    class Meta:
        ordering = ["created_at"]


class ProjectTask(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    task_id = models.CharField(max_length=256)

    def __str__(self):
        return f"{self.project.name} - task_id:{self.task_id}"
