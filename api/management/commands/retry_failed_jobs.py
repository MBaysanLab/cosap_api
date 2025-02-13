from django.core.management.base import BaseCommand
from ...models import Project
from ...constants import ProjectStatus


class Command(BaseCommand):
    help = "Retry failed jobs."

    def handle(self, *args, **kwargs):
        self.stdout.write("Retrying failed jobs...")

        failed_projects = Project.objects.filter(status=ProjectStatus.FAILED.value)
        for project in failed_projects:
            project.status = ProjectStatus.PENDING.value
            project.save()
            self.stdout.write(f"Retrying job for project {project.id}...")

        self.stdout.write("Done.")
