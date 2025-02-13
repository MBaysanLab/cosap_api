from django.contrib.auth.models import User
from django.http import Http404
from rest_framework import permissions


class OnlyAdminToList(permissions.BasePermission):
    """
    Custom permission that allows only admin users to access a list view
    """

    def has_permission(self, request, view):
        return view.action != "list" or request.user and request.user.is_staff


class IsOwnerOrDoesNotExist(permissions.BasePermission):
    """
    Custom permission that allows the user to see only the information they
    have access to. If a user tries to access something else, this will raise
    an Http404 exception.
    Admin users are allowed access regardless.
    """

    def has_object_permission(self, request, view, obj):
        if isinstance(obj, User):
            if obj == request.user or request.user.is_staff:
                return True
            else:
                raise Http404()

        return False
