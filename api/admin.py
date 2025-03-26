from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db import models
from django_drf_filepond.models import TemporaryUpload
from django_json_widget.widgets import JSONEditorWidget

from .models import *


class CustomUserAdmin(UserAdmin):
    # Fields to display in the list view
    list_display = (
        "email",
        "username",
        "is_email_verified",
        "is_staff",
        "is_active",
        "date_joined",
    )

    # Fields used for filtering in admin
    list_filter = ("is_email_verified", "is_staff", "is_active")

    # Fields used for searching
    search_fields = ("email", "username")

    # Fields shown when creating/editing a user
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_email_verified",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    # Fields shown when creating a new user
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "username",
                    "password1",
                    "password2",
                    "is_email_verified",
                    "is_staff",
                    "is_active",
                ),
            },
        ),
    )

    ordering = ("email",)


admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(Affiliation)
admin.site.register(File)
admin.site.register(Report)
admin.site.register(Action)
admin.site.register(VariantAnnotation)
admin.site.register(SmallVariant)
admin.site.register(SampleSmallVariant)
admin.site.register(ProjectFile)
admin.site.register(ProjectTask)
admin.site.register(ProjectSummary)
admin.site.register(ProjectQCSummary)
admin.site.register(SampleSmallVariantData)
admin.site.register(Sample)
admin.site.register(ProjectSample)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    formfield_overrides = {
        models.JSONField: {"widget": JSONEditorWidget},
    }
