import os
import re
import shutil
from datetime import datetime

from celery.result import AsyncResult
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q, Case, When, IntegerField
from django.db import transaction, DataError, models
from django.template.loader import render_to_string
import json
from tempfile import NamedTemporaryFile
from logging import getLogger

logger = getLogger(__name__)


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


def is_fastq_pair(pair1: str, pair2: str) -> bool:
    """
    Check if two fastq filenames represent a valid pair.

    Typical fastq pair naming conventions include:
    - sample_R1.fastq.gz and sample_R2.fastq.gz
    - sample_1.fastq.gz and sample_2.fastq.gz
    - sample_forward.fastq.gz and sample_reverse.fastq.gz

    Args:
        pair1: Filename of the first fastq file
        pair2: Filename of the second fastq file

    Returns:
        True if the files appear to be proper pairs, False otherwise
    """
    # Common patterns for paired-end naming
    r1_patterns = ["_R1", "_1", "_forward", "_read1"]
    r2_patterns = ["_R2", "_2", "_reverse", "_read2"]

    # Check if pairs have the same base name
    found_pair = False

    for r1, r2 in zip(r1_patterns, r2_patterns):
        # Check if pair1 has R1 pattern and pair2 has matching R2 pattern
        if r1 in pair1 and r2 in pair2:
            # Get the parts before and after the pattern
            base1 = pair1.split(r1)[0]
            base2 = pair2.split(r2)[0]

            # If the base names match, it's a valid pair
            if base1 == base2:
                found_pair = True
                break

        # Check the reverse (pair1 has R2, pair2 has R1)
        elif r2 in pair1 and r1 in pair2:
            base1 = pair1.split(r2)[0]
            base2 = pair2.split(r1)[0]

            if base1 == base2:
                found_pair = True
                break

    return found_pair


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
    subject = "Verify your email address"
    context = {
        "first_name": user.first_name,
        "verification_link": verification_link,
    }
    message = render_to_string("emails/verification_email.html", context)
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
    finally:
        print(f"Removed {directory}")


def order_variants_by_acmg_severity(queryset):
    """
    Orders a variant queryset by ACMG classification severity
    """
    return queryset.annotate(
        severity_order=Case(
            When(intervar_classification="Pathogenic", then=1),
            When(intervar_classification="Likely pathogenic", then=2),
            When(intervar_classification="Uncertain significance", then=3),
            When(intervar_classification="Likely benign", then=4),
            When(intervar_classification="Benign", then=5),
            default=6,
            output_field=IntegerField(),
        )
    ).order_by("severity_order", "gene_symbol")


def write_message_file(data):
    """Write data to a file in the shared mounted directory."""

    tmp_file = NamedTemporaryFile(
        suffix=".json", dir=settings.MEDIA_TMP, delete=False, mode="w"
    )
    with tmp_file as f:
        if isinstance(data, (dict, list)):
            json.dump(data, f)
        else:
            f.write(str(data))
    return tmp_file.name


def read_message_file(filepath):
    """Read data from a file in the shared mounted directory."""
    if not os.path.exists(filepath):
        return None

    with open(filepath, "r") as f:
        try:
            data = json.load(f)
            logger.info(f"Loaded JSON from file {filepath}.")
            return data
        except json.JSONDecodeError:
            logger.info(f"Failed to load JSON from file {filepath}.")
            # If not JSON, return as string
            f.seek(0)
            return f.read()


def delete_message_file(filepath):
    """Delete a file from the shared mounted directory."""
    if os.path.exists(filepath):
        os.remove(filepath)


def safe_bulk_create(
    model_class, objects_to_create, batch_size=1000, ignore_conflicts=False
):
    """
    A generalized bulk_create function that handles field length validation and error reporting.

    Args:
        model_class (Model): The Django model class
        objects_to_create (list): List of model instances to create
        batch_size (int): Size of batches for creation
        ignore_conflicts (bool): Whether to ignore unique constraint conflicts

    Returns:
        tuple: (created_objects_count, invalid_objects)
    """
    if not objects_to_create:
        return 0, []

    # Get field information from model
    varchar_fields = {}
    for field in model_class._meta.fields:
        if isinstance(field, models.CharField):
            varchar_fields[field.name] = field.max_length

    # Validate field lengths before bulk creation
    invalid_objects = []
    valid_objects = []

    for obj in objects_to_create:
        has_invalid_field = False
        invalid_fields = []

        # Check string field lengths
        for field_name, max_length in varchar_fields.items():
            value = getattr(obj, field_name, None)
            if isinstance(value, str) and len(value) > max_length:
                has_invalid_field = True
                invalid_fields.append(
                    {
                        "field": field_name,
                        "actual_length": len(value),
                        "max_length": max_length,
                        "value_preview": (
                            value[:50] + "..." if len(value) > 50 else value
                        ),
                    }
                )

        if has_invalid_field:
            invalid_objects.append({"object": obj, "invalid_fields": invalid_fields})
        else:
            valid_objects.append(obj)

    # Report invalid objects
    for invalid in invalid_objects:
        obj = invalid["object"]
        obj_id = getattr(obj, "id", None) or getattr(obj, "pk", None) or str(obj)
        logger.error(f"Invalid object found: {obj_id}")

        for field_info in invalid["invalid_fields"]:
            logger.error(
                f"Field '{field_info['field']}' exceeds max length: "
                f"{field_info['actual_length']} > {field_info['max_length']}"
            )
            logger.error(f"Value preview: {field_info['value_preview']}")

    # Bulk create valid objects in batches
    created_count = 0

    try:
        with transaction.atomic():
            for i in range(0, len(valid_objects), batch_size):
                batch = valid_objects[i : i + batch_size]
                try:
                    created_objects = model_class.objects.bulk_create(
                        batch, ignore_conflicts=ignore_conflicts
                    )
                    created_count += len(created_objects)
                except DataError as e:
                    logger.error(f"Error in batch {i//batch_size}: {e}")
                    raise  # Raise the exception to rollback the transaction

    except DataError:
        # Fall back to creating records individually to identify problematic records
        for i in range(0, len(valid_objects), batch_size):
            batch = valid_objects[i : i + batch_size]
            for j, obj in enumerate(batch):
                try:
                    obj.save()
                    created_count += 1
                except DataError as e:
                    logger.error(f"Error in record {i+j}: {e}")
                    # Print all string field values for this record
                    for field_name, max_length in varchar_fields.items():
                        value = getattr(obj, field_name, None)
                        if isinstance(value, str):
                            logger.info(
                                f" Field '{field_name}': length={len(value)}, max={max_length}"
                            )
                            if len(value) > max_length:
                                logger.info(f" Value preview: {value[:50]}...")

    except Exception as e:
        logger.error(f"Transaction failed: {str(e)}")
        raise

    return created_count, invalid_objects
