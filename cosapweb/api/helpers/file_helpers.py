import os

from django.conf import settings
import warnings

def wait_file_update_complete(file_path: str, timeout: int = 1000) -> bool:
    """
    Waits for file to be updated.
    """
    import time

    start_time = time.time()
    while time.time() - start_time < timeout:
        if time.time() - os.path.getmtime(file_path) > 1:
            return True
        time.sleep(0.1)
    raise Exception("File upload not complete")
