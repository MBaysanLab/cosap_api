from django.test import TestCase
from django.test.signals import Signal

from .models import USER, Project
from .signals import submit_cosap_dna_job, submit_cosap_parse_project_data_job


class TestSignals(TestCase):
    def test_create_project_signal(self):
        """
        Test that the signal is sent when a project is created.
        """
        signal = Signal()
        signal.connect(submit_cosap_dna_job, sender=Project)
        project = Project.objects.first()
        signal.send(sender=Project, instance=project, created=True)

    def test_project_parse_signal(self):
        signal = Signal()
        signal.connect(submit_cosap_parse_project_data_job, sender=Project)
        project = Project.objects.first()
        signal.send(sender=Project, instance=project, created=False)
