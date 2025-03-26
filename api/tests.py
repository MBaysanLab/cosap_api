from django.test import TestCase
from django.test.signals import Signal
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import USER, Project
from .signals import submit_cosap_dna_job


class TestSignals(TestCase):
    def test_create_project_signal(self):
        """
        Test that the signal is sent when a project is created.
        """
        signal = Signal()
        signal.connect(submit_cosap_dna_job, sender=Project)

        if Project.objects.first() is None:
            raise Exception("No project found, please create a project first.")

        project = Project.objects.first()
        signal.send(sender=Project, instance=project, created=True)


class TestEmailVerification(APITestCase):
    def setup(self):
        self.user = USER.objects.create_user(
            email="test@example.com",
            password="password",
            first_name="Test",
            last_name="User",
        )
        self.verification_url = reverse("verify-email")

    def test_verify_email(self):
        response = self.client.post(self.verification_url, {"email": self.user.email})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.user.email)

    def test_verify_email_user_not_found(self):
        response = self.client.post(
            self.verification_url, {"email": "nonexistent@example.com"}
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "User not found")
