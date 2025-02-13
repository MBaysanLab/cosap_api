import os

from django.conf import settings


def get_user_dir(user):
    user_path = f"{user.id}_{user.email}"
    return os.path.join(settings.MEDIA_ROOT, user_path)


def get_user_files_dir(user):
    user_path = get_user_dir(user)
    user_files_path = os.path.join(user_path, "files")
    os.makedirs(user_files_path, exist_ok=True)
    return user_files_path
