"""Fire-and-forget logging client.

Sends events to the Logging API in a daemon thread so the main request
is never blocked or failed by logging issues.
"""

import os
import threading

import requests

_LOGGING_URL = ""
_API_KEY = ""
_TIMEOUT = 5


def init() -> None:
    global _LOGGING_URL, _API_KEY
    _LOGGING_URL = os.getenv("LOGGING_API_URL", "").rstrip("/")
    _API_KEY = os.getenv("LOGGING_API_KEY", "")


def _send(event: dict) -> None:
    if not _LOGGING_URL or not _API_KEY:
        return
    try:
        requests.post(
            f"{_LOGGING_URL}/api/v1/events/ingest",
            json=event,
            headers={"X-API-Key": _API_KEY, "Content-Type": "application/json"},
            timeout=_TIMEOUT,
        )
    except Exception:
        pass  # logging must never break the application


def log_event(event: dict) -> None:
    """Queue an event to be sent in a background daemon thread."""
    threading.Thread(target=_send, args=(event,), daemon=True).start()
