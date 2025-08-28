from django.contrib import admin
from django.urls import include, path
from api.views import health_check

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("django_prometheus.urls")),
    path("api-auth/", include("rest_framework.urls", namespace="rest_framework")),
    path("", include("api.urls")),
    path('health/', health_check, name='health_check'),
]
