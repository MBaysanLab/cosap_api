from django.core.management.base import BaseCommand

from ...helpers.task_helpers import submit_vcf_parse_task
from ...models import USER, Project, Sample, ProjectSample


class Command(BaseCommand):
    help = "Imports a VCF file as project."

    def add_arguments(self, parser):
        parser.add_argument(
            "--vcf_path",
            type=str,
            help="Absolute path of VCF file in webapi container.",
        )
        parser.add_argument(
            "--sample_name", type=str, help="Sample name for parsing variants in vcf."
        )
        parser.add_argument(
            "--caller_type",
            type=str,
            help="Variant caller algoritmh used to generate the vcf. e.g. 'mutect2'",
        )
        parser.add_argument("--project_name", type=str, help="Name of the new project.")
        parser.add_argument(
            "--user_email",
            type=str,
            help="The email of the user to assign the project to.",
        )

    def handle(self, *args, **kwargs):
        self.stdout.write(
            f"Importing VCF file as project with name {kwargs['project_name']}."
        )

        # Get user
        user = USER.objects.get(email=kwargs["user_email"])

        # Create a new project
        project = Project.objects.create(
            user=user, name=kwargs["project_name"], is_draft=True
        )
        project.save()

        # Create Sample
        sample = Sample.objects.create()
        sample.save()

        # Create a project sample and link it to the project and sample
        project_sample = ProjectSample.objects.create(
            project=project,
        )
        project_sample.samples.add(sample)
        project_sample.save()

        # Submit the COSAP parse project data task
        submit_vcf_parse_task(
            vcf_path=kwargs["vcf_path"],
            caller_type=kwargs["caller_type"],
            sample_name=kwargs["sample_name"],
            sample_id=sample.id,
        )
