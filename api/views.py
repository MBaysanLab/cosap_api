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

from api import serializers
from api.models import (VariantAnnotation, Action, File, Project, ProjectFiles,
                                 ProjectSmallVariantData, ProjectSmallVariants, ProjectSummary,
                                 ProjectTask)
from api.permissions import IsOwnerOrDoesNotExist, OnlyAdminToList

from common.utils import (convert_file_relative_path_to_absolute_path,
                            create_chonky_filemap)
from .helpers.project_helpers import get_project_dir, remove_project_data_and_snvs
from .constants import ProjectStatus, ProjectTypeAlgorithms, ProjectTypes

USER = get_user_model()


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


class VerifyUserVeiwSet(viewsets.ViewSet):
    """
    View to verify user with token and get email.
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    serializer_class = serializers.UserSerializer
    queryset = USER.objects.all()

    def create(self, request):
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
        Change password
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
    def verify_email(self, request):
        email = request.data.get("email")
        if not email:
            return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)

        user = USER.objects.filter(email=email).first()
        if user:
            return Response({"email": user.email}, status=status.HTTP_200_OK)
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

class AuthTokenViewSet(ObtainAuthToken, viewsets.ViewSet):
    """
    View to get auth token given username and password.
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        if not user.is_email_verified:
            return Response({"error": "Email not verified. Please verify your email to log in."}, status=status.HTTP_400_BAD_REQUEST)
        token, created = Token.objects.get_or_create(user=user)
        return Response({"token": token.key})


class RegisterViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    """
    View to register a user (also logs the user in).
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    queryset = USER.objects.all()
    serializer_class = serializers.RegistrationSerializer

    def create(self, request, *args, **kwargs):
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
        
        # If project type is somatic or germline set predifined algorithms
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

        normal_file_ids = json.loads(request.POST.get("normal_files", "[]"))
        tumor_file_ids = json.loads(request.POST.get("tumor_files", "[]"))
        bed_file_ids = json.loads(request.POST.get("bed_files", "[]"))

        project_files = ProjectFiles.objects.create(project=new_project)

        for file_id in normal_file_ids:
            file = File.objects.get(uuid=file_id)
            project_files.files.add(file)

        for file_id in tumor_file_ids:
            file = File.objects.get(uuid=file_id)
            project_files.files.add(file)

        for file_id in bed_file_ids:
            file = File.objects.get(uuid=file_id)
            project_files.files.add(file)

        project_files.save()

        new_project.is_draft = False
        new_project.save()

        return HttpResponse(status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk):
        project = Project.objects.get(id=pk)

        project_metadata = {
            "name": project.name,
            "status": project.status,
            "collaborators": ",".join(
                [col.email for col in project.collaborators.all()]
            ),
            "time": project.created_at,
        }

        summary = ProjectSummary.objects.get(project=project)

        return Response(
            {
                "metadata": project_metadata,
                "summary": model_to_dict(summary) if summary else None,
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

        # If the project is already running, skip rerunning
        if project.status == ProjectStatus.RUNNING.value:
            return HttpResponse(status=status.HTTP_200_OK)
        
        project.status = ProjectStatus.PENDING.value
        project.save()

        # Remove project data and snvs
        remove_project_data_and_snvs(pk)

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
            return Response(status=status.HTTP_404_NOT_FOUND)

        try:
            project_snvs = ProjectSmallVariants.objects.get(project=project)
        except ProjectSmallVariants.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        
        page = request.GET.get("page")
        paginator = Paginator(project_snvs.snvs.all(), 25)

        all_variants = []
        for snv in paginator.get_page(page):
            variant_dict = model_to_dict(snv)
            try:
                variant_dict["af"] = ProjectSmallVariantData.objects.get(
                    project=project, snv=snv
                ).allele_frequency
                variant_dict["ad"] = ProjectSmallVariantData.objects.get(
                    project=project, snv=snv
                ).allele_depth

                # Internal variant frequency is the number of projects that have the variant over the total number of projects
                internal_freq = ProjectSmallVariantData.objects.filter(
                    snv=snv
                ).count() / Project.objects.count()
                variant_dict["user_case_frequency"] = f"{internal_freq:.2f}"

            except Exception as e:
                continue

            all_variants.append(variant_dict)

        # Convert out of range float values to string
        for variant in all_variants:
            for key, value in variant.items():
                if isinstance(value, float) and not (-3.4e+38 < value < 3.4e+38):
                    variant[key] = str(value)
        return Response({"snvs": all_variants, "total": paginator.count})


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
            sample_type = request.POST.get("sample_type")
            file = request.FILES.get("file")
            user = request.user
            f = File.objects.create(
                name=filename, user=user, file=file, sample_type=sample_type
            )
            f.save()
            return Response(str(f.uuid))
        else:
            response = super().post(request, *args, **kwargs)
            if response.status_code == 200:
                temp_id = response.data
                sample_type = request.POST.get("sample_type")
                f = File.objects.create(
                    user=request.user, uuid=temp_id, sample_type=sample_type, is_draft=True
                )
            return response

    def download(self, request, b64_string):
        decoded_path = base64.b64decode(b64_string).decode("utf-8")
        file_path = convert_file_relative_path_to_absolute_path(decoded_path)

        if not os.path.exists(file_path):
            raise Http404
        
        # If the requested path is a directory, create a zip file and return it
        if os.path.isdir(file_path):
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=True) as temp_zip:
                with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(file_path):
                        for file in files:
                            zipf.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), file_path))

                response = StreamingHttpResponse(
                    FileWrapper(
                        open(temp_zip.name, "rb"),
                    ),
                    content_type="application/zip",
                )
                response["Content-Length"] = os.path.getsize(temp_zip.name)
                response["Content-Disposition"] = f"attachment; filename={os.path.basename(file_path)}.zip"
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
