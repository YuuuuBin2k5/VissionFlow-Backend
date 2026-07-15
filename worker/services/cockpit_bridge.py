import os
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any
import requests

# Base URL of the Cockpit Gateway API. Can be set via environment variable.
COCKPIT_API_BASE_URL: str = os.getenv("COCKPIT_API_BASE_URL", "http://localhost:8000").rstrip("/")
COCKPIT_SERVICE_TOKEN: str = os.getenv("COCKPIT_SERVICE_TOKEN", "")

# Initialize a ThreadPoolExecutor with a small worker pool for handling network requests.
# This ensures that API calls are non-blocking and will not delay the MoviePy video rendering loop.
_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="cockpit_bridge")


def _execute_post_request(url: str, payload: Dict[str, Any]) -> None:
    """
    Helper function to execute an HTTP POST request synchronously with a 0.5s timeout.
    Catches all network exceptions and handles them silently to maintain system stability.
    """
    try:
        response = requests.post(url, json=payload, headers={"X-Worker-Service-Token": COCKPIT_SERVICE_TOKEN}, timeout=0.5)
        if response.status_code not in (200, 201):
            print(f"[Cockpit Bridge] Warning: POST {url} returned status code {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[Cockpit Bridge] Error: Failed to POST to {url}. Reason: {e}")


def _execute_patch_request(url: str, payload: Dict[str, Any]) -> None:
    """
    Helper function to execute an HTTP PATCH request synchronously with a 0.5s timeout.
    Catches all network exceptions and handles them silently to maintain system stability.
    """
    try:
        response = requests.patch(url, json=payload, headers={"X-Worker-Service-Token": COCKPIT_SERVICE_TOKEN}, timeout=0.5)
        if response.status_code not in (200, 204):
            print(f"[Cockpit Bridge] Warning: PATCH {url} returned status code {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[Cockpit Bridge] Error: Failed to PATCH to {url}. Reason: {e}")


def dispatch_log_to_cockpit(level: str, msg: str) -> None:
    """
    Sends a system log message to the Cockpit Gateway asynchronously.
    This function is thread-safe and non-blocking.

    Parameters:
    - level (str): The level of the log ('INFO', 'SUCCESS', 'WARN', 'CRITICAL').
    - msg (str): The message content of the log.
    """
    url = f"{COCKPIT_API_BASE_URL}/api/v1/logs/inject"
    payload = {
        "level": level,
        "msg": msg
    }
    # Submit request to ThreadPoolExecutor to run in background
    _executor.submit(_execute_post_request, url, payload)


def update_task_progress(task_id: str, status: str, progress: int) -> None:
    """
    Updates the task progress state on the Cockpit Kanban board asynchronously.
    This function is thread-safe and non-blocking.

    Parameters:
    - task_id (str): The ID of the video rendering task.
    - status (str): The current status/stage ('SCRIPT', 'ASSET', 'AUDIO', 'COMPOSITING', 'READY').
    - progress (int): An integer representing the percentage completion (0-100).
    """
    url = f"{COCKPIT_API_BASE_URL}/api/v1/tasks/{task_id}/progress"
    payload = {
        "status": status,
        "progress": progress
    }
    # Submit request to ThreadPoolExecutor to run in background
    _executor.submit(_execute_patch_request, url, payload)
