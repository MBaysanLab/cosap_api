import os
import re
from datetime import datetime

from celery.result import AsyncResult
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.template.loader import render_to_string
import shutil



def levenshtein(s1, s2):
    if len(s1) < len(s2):
        return levenshtein(s2, s1)

    # len(s1) >= len(s2)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = (
                previous_row[j + 1] + 1
            )  # j+1 instead of j since previous_row and current_row are one character longer
            deletions = current_row[j] + 1  # than s2
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def match_read_pairs(file_list: list) -> list[tuple]:
    """
    Takes list of file object returns paths of paired files as list of tuples.
    """

    file_obj_names = [(file, file.name) for file in file_list]

    file_obj_names = sorted(file_obj_names, key=lambda x: x[1])
    read_1 = []
    read_2 = []

    for file, file_name in file_obj_names:
        # Finds read 1 files
        pattern_r1 = r"^(.*?)(?:_1|R1|r1)\.(.*?)$"
        pattern_r2 = r"^(.*?)(?:_2|R2|r2)\.(.*?)$"

        match_r1 = re.match(pattern_r1, file_name)
        match_r2 = re.match(pattern_r2, file_name)

        if match_r1:
            read_1.append((file, file_name))
        elif match_r2:
            read_2.append((file, file_name))

    if len(read_1) != len(read_2):
        raise ValueError(f"Some pairs are missing. Current files are: {file_obj_names}")

    pair_list = list(zip(read_1, read_2))

    for pair in pair_list:
        if levenshtein(pair[0][1], pair[1][1]) != 1:
            raise ValueError(
                f"Some pairs are not matching. Current files are: {file_obj_names}"
            )

    pair_list = [(pair[0][0].file.path, pair[1][0].file.path) for pair in pair_list]
    if len(pair_list) == 0:
        raise ValueError(
            f"Fastq files cannot be paired. The filenames should be like: \
                sample_1.fastq.gz, sample_2.fastq.gz or sample_R1.fastq.gz, sample_R2.fastq.gz. Current files are: {file_obj_names}"
        )

    return pair_list


def get_relative_to_media_root(path):
    return os.path.relpath(path, settings.MEDIA_ROOT)


def create_chonky_filemap(dir, project_name):
    """
    Walks directory and returns Chonky file map and root folder id.
    """

    def get_stats(path):
        st = os.stat(path)
        return {
            "id": f"{st.st_dev}-{st.st_ino}",
            "size": st.st_size,
            "modDate": str(datetime.fromtimestamp(st.st_mtime)),
        }

    def walk(dir_path, root_dir_id, root_folder_name):
        for entry in os.scandir(dir_path):
            if entry.name.startswith("."):
                continue
            full_path = entry.path
            rel_path = get_relative_to_media_root(entry)
            parent_stats = get_stats(dir_path)
            parent_id = f"{parent_stats['id']}"
            stats = get_stats(full_path)
            file_id = f"{stats['id']}"

            if entry.is_dir():
                if file_id not in file_map:
                    file_map[file_id] = {
                        "id": file_id,
                        "name": entry.name,
                        "isDir": True,
                        "childrenIds": [],
                        "path": rel_path,
                    }

                    if file_id != parent_id:
                        file_map[file_id]["parentId"] = parent_id

                if parent_id not in file_map:
                    file_map[parent_id] = {
                        "id": parent_id,
                        "name": (
                            root_folder_name if parent_id == root_dir_id else entry.name
                        ),
                        "isDir": True,
                        "childrenIds": [file_id],
                        "path": rel_path,
                    }
                else:
                    file_map[parent_id]["childrenIds"].append(file_id)

                yield from walk(full_path, root_dir_id, root_folder_name)

            elif entry.is_file():
                if parent_id not in file_map:
                    file_map[parent_id] = {
                        "id": parent_id,
                        "name": (
                            root_folder_name if parent_id == root_dir_id else entry.name
                        ),
                        "isDir": True,
                        "childrenIds": [file_id],
                        "path": get_relative_to_media_root(dir_path),
                    }
                else:
                    file_map[parent_id]["childrenIds"].append(file_id)

                file_map[file_id] = {
                    "id": file_id,
                    "name": entry.name,
                    "parentId": parent_id,
                    "size": stats["size"],
                    "modDate": stats["modDate"],
                    "path": rel_path,
                }

                yield full_path

    if not os.path.exists(dir):
        return None

    root_dir = os.path.abspath(dir)
    root_dir_id = f"{os.stat(root_dir).st_dev}-{os.stat(root_dir).st_ino}"

    file_map = {}
    for _ in walk(root_dir, root_dir_id, project_name):
        pass

    return {"root_folder_id": root_dir_id, "file_map": file_map}


def convert_file_relative_path_to_absolute_path(file_path: str) -> str:
    """
    Converts relative path to absolute path.
    """
    return os.path.join(settings.MEDIA_ROOT, file_path)


def send_verification_email(user, verification_link):
    subject = 'Verify your email address'
    context = {
        'first_name': user.first_name,
        'verification_link': verification_link,
    }
    message = render_to_string('emails/verification_email.html', context)
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [user.email]
    
    send_mail(subject, message, from_email, recipient_list, html_message=message)

def remove_dir(directory):
    try:
        shutil.rmtree(directory, ignore_errors=True)
    except Exception as e:
        print(f"Error: {e}")
        # Try alternative method
        for root, dirs, files in os.walk(directory, topdown=False):
            for name in files:
                try:
                    os.unlink(os.path.join(root, name))
                except Exception as e:
                    print(f"Error removing file {name}: {e}")
            for name in dirs:
                try:
                    os.rmdir(os.path.join(root, name))
                except Exception as e:
                    print(f"Error removing directory {name}: {e}")
        os.rmdir(directory)