import os



def wait_file_update_complete(file_path: str, timeout: int = 1000) -> bool:
    """
    Waits for file update to complete by detecting when file
    modifications have stopped for at least 1 second.

    Args:
        file_path: Path to the file being monitored
        timeout: Maximum wait time in seconds

    Returns:
        True if file update completed

    Raises:
        Exception if timeout is reached before update completes
    """
    import time

    start_time = time.time()
    last_modified = os.path.getmtime(file_path)

    while time.time() - start_time < timeout:
        current_modified = os.path.getmtime(file_path)

        if current_modified > last_modified:
            # File was modified, update our timestamp
            last_modified = current_modified
        elif time.time() - last_modified > 1:
            # File hasn't been modified for over 1 second
            return True

        time.sleep(0.1)

    raise Exception("File update not complete within timeout period")
