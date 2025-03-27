import base64
import json
import mimetypes
import os
import re
import tempfile
from pathlib import Path
from urllib import request
from wsgiref.util import FileWrapper
import zipfile
from collections import defaultdict
import random

import pysam
from django.contrib.auth import get_user_model
from django.core import serializers as django_serializers
from django.db.models import Q
from django.db.models.query import QuerySet
from django.forms.models import model_to_dict
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.core.paginator import Paginator
from django_drf_filepond.parsers import PlainTextParser, UploadChunkParser
from django_drf_filepond.renderers import PlainTextRenderer
from django_drf_filepond.views import PatchView, ProcessView
from rest_framework import mixins, permissions, status, views, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action, api_view
from rest_framework.parsers import MultiPartParser
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from django.utils.http import urlsafe_base64_decode
from django.utils.encoding import force_str

from api import serializers
from api.models import (
    VariantAnnotation,
    Action,
    File,
    Project,
    ProjectFile,
    SampleSmallVariantData,
    SampleSmallVariant,
    ProjectSummary,
    ProjectQCSummary,
    ProjectTask,
    Sample,
    ProjectSample,
)
from api.permissions import IsOwnerOrDoesNotExist, OnlyAdminToList

from common.utils import (
    convert_file_relative_path_to_absolute_path,
    create_chonky_filemap,
    order_variants_by_acmg_severity,
    email_verification_token,
)
from .helpers.project_helpers import (
    get_project_dir,
    remove_project_data_and_snvs,
    add_sample_to_project,
)
from .constants import ProjectStatus, ProjectTypeAlgorithms, ProjectTypes
from .elasticsearch_queries import filter_variants_by_annotation
from logging import getLogger

USER = get_user_model()

logger = getLogger(__name__)


class UserViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    View to list (admins only), view and update user information.
    """

    permission_classes = [
        permissions.IsAuthenticated,
        IsOwnerOrDoesNotExist,
        OnlyAdminToList,
    ]

    lookup_field = "email"
    serializer_class = serializers.UserSerializer
    queryset = USER.objects.all()


class UserAuthViewSet(viewsets.ViewSet):
    """
    Viewset for managing authenticated user operations.

    This viewset handles token verification, password management, and email verification
    operations for existing users. It does not handle initial authentication (login)
    or user registration.

    Endpoints:
    - POST /auth/ - Verify a token and get user information
    - PUT /auth/ - Change a user's password
    - POST /auth/check_email_exists/ - Check if an email exists
    - GET /verify-email/<uidb64>/<token>/ - Verify a user's email with token
    - POST /auth/resend_verification/ - Resend verification email
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    serializer_class = serializers.UserSerializer
    queryset = USER.objects.all()

    def create(self, request):
        """
        Verify an authentication token and return user information.

        This endpoint accepts an Authorization header with a token and returns
        the associated user's information if the token is valid.

        Returns:
          200 OK with user data if token is valid
          404 Not Found if token is invalid or not provided
        """
        token = (
            request.headers["Authorization"].split()[1]
            if "Authorization" in request.headers
            else None
        )

        if token and Token.objects.filter(key=token).exists():
            user = Token.objects.get(key=token).user
            user_serializer = self.serializer_class(user)
            return Response(user_serializer.data, status=status.HTTP_200_OK)

        return Response(status=status.HTTP_404_NOT_FOUND)

    def update(self, request):
        """
        Change a user's password.

        Requires a valid token in the Authorization header and both old_password
        and new_password in the request data.

        Returns:
          200 OK if password changed successfully
          401 Unauthorized if old password is incorrect
          404 Not Found if token is invalid or not provided
        """
        request_token = (
            request.headers["Authorization"].split()[1]
            if "Authorization" in request.headers
            else None
        )

        if request_token and Token.objects.filter(key=request_token).exists():
            user = Token.objects.get(key=request_token).user
            if user.check_password(request.data["old_password"]):
                user.set_password(request.data["new_password"])
                user.save()
                return Response(status=status.HTTP_200_OK)
            else:
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        return Response(status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=["post"])
    def check_email_exists(self, request):
        """
        Check if an email address exists in the system.

        Accepts a POST request with an 'email' field and returns
        the email if it exists in the system.

        Returns:
          200 OK with email if it exists
          404 Not Found if email does not exist
          400 Bad Request if email is not provided
        """
        email = request.data.get("email")
        if not email:
            return Response(
                {"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        user = USER.objects.filter(email=email).first()
        if user:
            return Response({"email": user.email}, status=status.HTTP_200_OK)
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=["get"])
    def verify_email_token(self, request, uidb64=None, token=None):
        """
        Verify a user's email address using a secure token.

        This endpoint is accessed via an email verification link. It validates
        the provided token and user ID, then marks the user's email as verified.

        The token is time-limited and becomes invalid after use.

        Args:
            uidb64: Base64-encoded user ID
            token: Secure verification token

        Returns:
          200 OK if email verified successfully
          400 Bad Request if the verification link is invalid or expired
        """
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = get_user_model().objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, get_user_model().DoesNotExist):
            user = None

        if user is not None and email_verification_token.check_token(user, token):
            user.is_email_verified = True
            user.save()
            return Response(
                {"detail": "Email verified successfully"}, status=status.HTTP_200_OK
            )
        else:
            return Response(
                {"detail": "Invalid verification link"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=["post"])
    def resend_verification(self, request):
        """
        Resend verification email to a registered user.
        
        This endpoint accepts an email address and sends a new verification
        email with a fresh token if the user exists and is not already verified.
        
        Returns:
          200 OK if email was sent successfully
          400 Bad Request if email is already verified or not provided
          404 Not Found if user with provided email doesn't exist
        """
        email = request.data.get("email")
        if not email:
            return Response(
                {"error": "Email is required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            user = USER.objects.get(email=email)
            
            # Check if email is already verified
            if user.is_email_verified:
                return Response(
                    {"error": "Email is already verified"},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
            # Generate new verification link with secure token
            from django.urls import reverse
            from django.utils.http import urlsafe_base64_encode
            from django.utils.encoding import force_bytes
            from common.utils import email_verification_token, send_verification_email
            
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = email_verification_token.make_token(user)
            verification_link = reverse(
                "verify-email", kwargs={"uidb64": uid, "token": token}
            )
            
            # Send verification email
            send_verification_email(user, verification_link)
            
            return Response(
                {"detail": "Verification email sent successfully"}, 
                status=status.HTTP_200_OK
            )
            
        except USER.DoesNotExist:
            return Response(
                {"error": "User not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )


class AuthTokenViewSet(ObtainAuthToken, viewsets.ViewSet):
    """
    Viewset for obtaining authentication tokens (login).

    This viewset handles the initial authentication process. It accepts
    username/password credentials and returns an authentication token
    that can be used for subsequent requests.

    This viewset extends Django REST Framework's ObtainAuthToken class
    and adds email verification checking.

    Endpoints:
    - POST /api/token/ - Obtain an authentication token
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        """
        Authenticate a user and return an authentication token.

        Accepts username and password credentials and validates them.
        Also checks that the user's email is verified before issuing a token.

        Returns:
          200 OK with token if authentication succeeds
          400 Bad Request if credentials are invalid or email is not verified
        """
        serializer = self.serializer_class(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        token, created = Token.objects.get_or_create(user=user)
        return Response({"token": token.key})


class RegisterViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    """
    Viewset for registering new users.

    This viewset handles new user registration. It creates a new user record,
    sends a verification email, and returns an authentication token.

    Note that the returned token may not be usable for authentication
    until the user verifies their email address.

    Endpoints:
    - POST /api/register/ - Register a new user
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    queryset = USER.objects.all()
    serializer_class = serializers.RegistrationSerializer

    def create(self, request, *args, **kwargs):
        """
        Register a new user.

        Creates a new user record with the provided information and returns
        an authentication token. For non-guest users, this also sends a
        verification email that must be completed before the user can log in.

        Returns:
          200 OK with token if registration succeeds
          400 Bad Request if the registration data is invalid
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        user = USER.objects.get(id=serializer.instance.id)
        token = Token.objects.get(user=user)

        return Response({"token": token.key})


class ProjectViewSet(viewsets.ModelViewSet):
    """
    View to create, view, update and list projects where the requesting user is the creator or a collaborator.
    """

    permission_classes = [permissions.IsAuthenticated]

    queryset = Project.objects.order_by("-created_at")
    serializer_class = serializers.ProjectSerializer

    def get_queryset(self):
        """
        Get the list of items for this view.

        Overridden only to return projects where the requesting user
        is the creator of the project or a collaborator in the project.
        """
        queryset = self.queryset.all()
        if isinstance(queryset, QuerySet):
            user = self.request.user
            if user.is_superuser:
                return queryset
            queryset = queryset.filter(
                Q(user=user) | Q(collaborators=user) | Q(is_demo=True)
            )

        return queryset

    def create(self, request, *args, **kwargs):
        user = request.user
        project_type = request.POST.get("project_type")
        name = request.POST.get("name")

        # If project type is somatic or germline set predifined algorithms
        if project_type == ProjectTypes.SOMATIC.value:
            algorithms = ProjectTypeAlgorithms[ProjectTypes.SOMATIC.value].value
        elif project_type == ProjectTypes.GERMLINE.value:
            algorithms = ProjectTypeAlgorithms[ProjectTypes.GERMLINE.value].value
        else:
            algorithms = json.loads(request.POST.get("algorithms", "{}"))

        new_project = Project.objects.create(
            user=user,
            project_type=project_type,
            name=name,
            algorithms=algorithms,
            status=ProjectStatus.PENDING.value,
            is_draft=True,
        )

        # TODO: Get rid of hard coded keys and values
        normal_sample_id = request.POST.get("normal_sample_id")
        tumor_sample_id = request.POST.get("tumor_sample_id")
        child_sample_id = request.POST.get("child_sample_id")
        mother_sample_id = request.POST.get("mother_sample_id")
        father_sample_id = request.POST.get("father_sample_id")

        project_samples = ProjectSample.objects.create(project=new_project)

        if normal_sample_id:
            sample = Sample.objects.get(uuid=normal_sample_id)
            project_samples.samples.add(sample)

        if tumor_sample_id:
            sample = Sample.objects.get(uuid=tumor_sample_id)
            project_samples.samples.add(sample)

        if child_sample_id:
            child_sample = add_sample_to_project(project_samples, child_sample_id)

            mother_sample = add_sample_to_project(project_samples, mother_sample_id)
            if mother_sample:
                child_sample.mother = mother_sample
                child_sample.save()

            father_sample = add_sample_to_project(project_samples, father_sample_id)
            if father_sample:
                child_sample.father = father_sample
                child_sample.save()
        else:
            # No child, just add parents to the project
            add_sample_to_project(project_samples, mother_sample_id)
            add_sample_to_project(project_samples, father_sample_id)

        project_samples.save()

        bed_file_id = request.POST.get("bed_file_id")
        if bed_file_id:
            project_files = ProjectFile.objects.create(project=new_project)
            project_files.files.add(File.objects.get(uuid=bed_file_id))
            project_files.save()

        new_project.is_draft = False
        new_project.save()

        return HttpResponse(status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk):
        project = Project.objects.get(id=pk)

        project_metadata = {
            "name": project.name,
            "project_type": project.project_type,
            "status": project.status,
            "collaborators": ",".join(
                [col.email for col in project.collaborators.all()]
            ),
            "time": project.created_at,
        }

        summary = ProjectQCSummary.objects.filter(project=project).first()

        return Response(
            {
                "metadata": project_metadata,
                "qc_summary": model_to_dict(summary) if summary else None,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"])
    def rerun_project(self, request, pk=None):
        # Allow only superuser user that created or the project to rerun it
        if (
            request.user != Project.objects.get(id=pk).user
            and not request.user.is_superuser
        ):
            return HttpResponse(status=status.HTTP_401_UNAUTHORIZED)

        project = Project.objects.get(id=pk)

        # If the project is already running, skip rerunning
        if project.status == ProjectStatus.RUNNING.value:
            return HttpResponse(status=status.HTTP_200_OK)

        project.status = ProjectStatus.PENDING.value
        project.save()
        return HttpResponse(status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def delete_project(self, request, pk=None):
        # Allow only user that created the project to delete it
        if (
            request.user != Project.objects.get(id=pk).user
            and not request.user.is_superuser
        ):
            return HttpResponse(status=status.HTTP_401_UNAUTHORIZED)

        project = get_object_or_404(Project, pk=pk)
        project.delete()

        return HttpResponse(status=status.HTTP_200_OK)


class ProjectSNVViewset(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def retrieve(self, request, pk=None):
        try:
            project = Project.objects.get(id=pk)
        except Project.DoesNotExist:
            logger.error(f"Project with id {pk} does not exist")
            return Response(status=status.HTTP_404_NOT_FOUND)

        if project.project_type == ProjectTypes.GERMLINE.value:
            try:
                sample = (
                    ProjectSample.objects.get(project=project).samples.all().first()
                )
            except ProjectSample.DoesNotExist:
                logger.error(f"Germline sample for project with id {pk} does not exist")
                return Response(status=status.HTTP_404_NOT_FOUND)
        elif project.project_type == ProjectTypes.SOMATIC.value:
            try:
                sample = ProjectSample.objects.get(
                    project=project, sample_type=Sample.TUMOR
                )
            except ProjectSample.DoesNotExist:
                logger.error(f"Tumor sample for project with id {pk} does not exist")
                return Response(status=status.HTTP_404_NOT_FOUND)
        elif project.project_type == ProjectTypes.GERMLINE_TRIO.value:
            try:
                # Get the ProjectSamples instance for this project
                project_samples = ProjectSample.objects.filter(project=project).first()

                if not project_samples:
                    logger.error(f"No samples found for project with id {pk}")
                    return Response(status=status.HTTP_404_NOT_FOUND)

                # Get the proband (child) sample that has mother or father relationships
                sample = project_samples.samples.filter(
                    Q(mother__isnull=False) | Q(father__isnull=False)
                ).first()

                if not sample:
                    logger.error(
                        f"Proband sample for project with id {pk} does not exist"
                    )
                    return Response(status=status.HTTP_404_NOT_FOUND)

            except ProjectSample.DoesNotExist:
                logger.error(f"ProjectSamples for project with id {pk} does not exist")
                return Response(status=status.HTTP_404_NOT_FOUND)
        else:
            return Response(status=status.HTTP_404_NOT_FOUND)

        try:
            sample_small_variants = SampleSmallVariant.objects.get(
                sample=sample
            ).variants.all()
        except SampleSmallVariant.DoesNotExist:
            logger.error(
                f"SampleSmallVariants for sample with id {sample.id} does not exist"
            )
            return Response(status=status.HTTP_404_NOT_FOUND)

        # Get query parameters
        page = request.GET.get("page", 1)
        page_size = request.GET.get("page_size", 25)
        filters = (
            request.GET.get("filters", "").split(",")
            if request.GET.get("filters")
            else []
        )

        # Get filtered variants
        variant_annotations = VariantAnnotation.objects.filter(
            variant__in=sample_small_variants, vep_pick=True
        )
        variant_annotations_ids = variant_annotations.values_list("id", flat=True)

        if filters:
            variant_annotations = filter_variants_by_annotation(
                filters, list(variant_annotations_ids)
            )

        # Sort the variants based on intervar_classification from most severe to least severe
        # Most severe: 'Pathogenic', 'Likely pathogenic', 'Uncertain significance', 'Likely benign', 'Benign'
        variant_annotations = order_variants_by_acmg_severity(variant_annotations)

        paginator = Paginator(variant_annotations, page_size)

        page_variants = []
        for snv in paginator.get_page(page):
            variant_dict = model_to_dict(snv, exclude=["variant"])
            try:
                sample_snv_data = SampleSmallVariantData.objects.get(
                    variant=snv.variant, sample=sample
                )
                variant_dict["sample_specific"] = model_to_dict(sample_snv_data)
            except SampleSmallVariantData.DoesNotExist:
                variant_dict["sample_specific"] = {}

            variant_dict["pedigree"] = defaultdict(dict)
            if sample.mother:
                try:
                    mother_snv_data = SampleSmallVariantData.objects.get(
                        variant=snv.variant, sample=sample.mother
                    )
                    variant_dict["pedigree"]["mother"] = model_to_dict(mother_snv_data)
                except SampleSmallVariantData.DoesNotExist:
                    variant_dict["pedigree"]["mother"]
            if sample.father:
                try:
                    father_snv_data = SampleSmallVariantData.objects.get(
                        variant=snv.variant, sample=sample.father
                    )
                    variant_dict["pedigree"]["father"] = model_to_dict(father_snv_data)
                except SampleSmallVariantData.DoesNotExist:
                    variant_dict["pedigree"]["father"]

            variant_dict["variant"] = model_to_dict(snv.variant)
            page_variants.append(variant_dict)

        # Convert out of range float values to string. 3.4e38 is the maximum value for float32
        for variant in page_variants:
            for key, value in variant.items():
                if isinstance(value, float) and not (-3.4e38 < value < 3.4e38):
                    variant[key] = str(value)

        return Response({"snvs": page_variants, "total": paginator.count})


class IGVDataView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def ranged_data_response(self, range_header, path):
        if not range_header:
            return None
        m = re.search(r"(\d+)-(\d*)", range_header)
        if not m:
            return "Error: unexpected range header syntax: {}".format(range_header)

        size = os.path.getsize(path)
        offset = int(m.group(1))
        length = int(m.group(2) or size) - offset + 1

        data = None
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read(length)

        response = HttpResponse(
            data,
            headers={
                "Content-Range": f"bytes {offset}-{offset + length - 1}/{size}",
            },
            content_type="application/octet-stream",
        )
        response.status_code = 206

        return response

    def get(self, request, b64_string):
        decoded_path = base64.b64decode(b64_string).decode("utf-8")

        if decoded_path.endswith(".bai"):
            return FileViewSet().download(request, b64_string)

        file_path = convert_file_relative_path_to_absolute_path(decoded_path)

        if not os.path.exists(file_path):
            raise Http404

        range_header = request.headers.get("Range")
        return self.ranged_data_response(range_header, file_path)


class ActionViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    queryset = Action.objects.order_by("-created_at")
    serializer_class = serializers.ActionSerializer

    def get_queryset(self):
        """
        Get the list of items for this view.

        Overridden to only return projects where the requesting user
        is the creator of the project or a collaborator in the project.
        """
        queryset = self.queryset

        if isinstance(queryset, QuerySet):
            user = self.request.user
            queryset = queryset.filter(Q(associated_user=user))
        return queryset


class SampleViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        samples = Sample.objects.filter(user=request.user)
        return Response(
            [
                {
                    "id": sample.id,
                    "name": sample.name,
                    "sample_type": sample.sample_type,
                }
                for sample in samples
            ]
        )

    def create(self, request):
        sample_name = request.data.get("sample_name")
        sample_type = request.data.get("sample_type")
        sample_files_ids = request.data.get("file_ids")

        if not sample_files_ids:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        sample = Sample.objects.create(
            name=sample_name,
            sample_type=sample_type,
            user=request.user,
        )
        for file in sample_files_ids:
            sample.files.add(File.objects.get(uuid=file))
        sample.save()

        return Response(str(sample.uuid))


class FileViewSet(ProcessView, PatchView, viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = (MultiPartParser, UploadChunkParser)
    renderer_classes = (PlainTextRenderer, JSONRenderer)

    def list(self, request, project_id=None):
        return_type = request.GET.get("return_type")
        sample_type = (
            request.GET.get("sample_type").upper()
            if request.GET.get("sample_type")
            else None
        )
        file_type = (
            request.GET.get("file_type").upper()
            if request.GET.get("file_type")
            else None
        )

        if return_type and (return_type == "projectFileMap"):
            project = Project.objects.get(id=project_id)

            if not project:
                return Response(status=status.HTTP_404_NOT_FOUND)

            project_dir = get_project_dir(project_id)
            files = create_chonky_filemap(project_dir, project.name)
            return Response(files)

        if sample_type:
            files = File.objects.filter(
                (Q(user=request.user) | Q(is_demo=True)), Q(sample_type=sample_type)
            )
            files = {
                files[i].uuid: f"{i+1} - {files[i].name}" for i in range(len(files))
            }
            return Response(files)

        if file_type:
            files = File.objects.filter(
                (Q(user=request.user) | Q(is_demo=True)), Q(file_type=file_type)
            )
            files = {
                files[i].uuid: f"{i+1} - {files[i].name}" for i in range(len(files))
            }
            return Response(files)

        files = [
            file.filename
            for file in File.objects.filter(Q(user=request.user) | Q(is_demo=True))
        ]
        return Response(files)

    def create(self, request, *args, **kwargs):
        if request.FILES.get("file"):
            filename = request.FILES.get("file").name
            file = request.FILES.get("file")
            user = request.user
            f = File.objects.create(name=filename, user=user, file=file)
            f.save()
            return Response(str(f.uuid))
        else:
            response = super().post(request, *args, **kwargs)
            if response.status_code == 200:
                temp_id = response.data
                f = File.objects.create(
                    user=request.user,
                    uuid=temp_id,
                    is_draft=True,
                )
            return response

    def download(self, request, b64_string):
        try:
            decoded_path = base64.b64decode(b64_string).decode("utf-8")
            file_path = convert_file_relative_path_to_absolute_path(decoded_path)
        except Exception as e:
            return HttpResponse(status=status.HTTP_404_NOT_FOUND)

        if not os.path.exists(file_path):
            raise Http404

        # If the requested path is a directory, create a zip file and return it
        if os.path.isdir(file_path):
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=True) as temp_zip:
                with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(file_path):
                        for file in files:
                            zipf.write(
                                os.path.join(root, file),
                                os.path.relpath(os.path.join(root, file), file_path),
                            )

                response = StreamingHttpResponse(
                    FileWrapper(
                        open(temp_zip.name, "rb"),
                    ),
                    content_type="application/zip",
                )
                response["Content-Length"] = os.path.getsize(temp_zip.name)
                response["Content-Disposition"] = (
                    f"attachment; filename={os.path.basename(file_path)}.zip"
                )
                return response

        filename = os.path.basename(file_path)
        response = StreamingHttpResponse(
            FileWrapper(
                open(file_path, "rb"),
            ),
            content_type="application/octet-stream",
        )
        response["Content-Length"] = os.path.getsize(file_path)
        response["Content-Disposition"] = f"attachment; filename={filename}"
        return response

    def patch(self, request, *args, **kwargs):
        return super().patch(request, *args, **kwargs)
