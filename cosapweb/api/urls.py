from django.urls import include, path, re_path
from rest_framework.authtoken import views as auth_views
from rest_framework.routers import DefaultRouter

from cosapweb.api import views

router = DefaultRouter()
router.register(r"users", views.UserViewSet, basename="user")
router.register(r"login", views.AuthTokenViewSet, basename="login")
router.register(r"register", views.RegisterViewSet, basename="register")
router.register(r"get_user", views.VerifyUserVeiwSet, basename="get_user")
router.register(r"projects", views.ProjectViewSet, basename="project")
router.register(r"actions", views.ActionViewSet, basename="action")
router.register(r"variants", views.ProjectSNVViewset, basename="project_variants")

urlpatterns = [
    path("", include(router.urls)),
    re_path(r"files/?$", views.FileViewSet.as_view({"get": "list", "post": "create"})),
    re_path(
        r"files/(?P<project_id>[0-9a-zA-Z]+)/?$",
        views.FileViewSet.as_view({"get": "list"}),
    ),
    re_path(
        r"^files/patch/(?P<chunk_id>[0-9a-zA-Z]{22})$",
        views.FileViewSet.as_view({"patch": "patch"}),
    ),
    re_path(
        r"file/(?P<b64_string>.+)/?$", views.FileViewSet.as_view({"get": "download"})
    ),
    path("change_password/", views.VerifyUserVeiwSet.as_view({"put": "update"})),
    re_path(r"igv/(?P<b64_string>.+)/?$", views.IGVDataView.as_view()),
]
