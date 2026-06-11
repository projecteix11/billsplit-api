"""Fire-and-forget logging client using Axiom.

Sends events directly to Axiom in a daemon thread so the main request
is never blocked or failed by logging issues.
"""

import os
import threading
from datetime import datetime, timezone

import axiom_py

_client = None
_dataset = ""


def init() -> None:
    global _client, _dataset
    # Canonical names are AXIOM_TOKEN / AXIOM_DATASET; the VITE_-prefixed
    # variants are accepted because older deploy configs defined those.
    token = os.getenv("AXIOM_TOKEN", "") or os.getenv("VITE_AXIOM_TOKEN", "")
    _dataset = (
        os.getenv("AXIOM_DATASET", "")
        or os.getenv("VITE_AXIOM_DATASET", "")
        or "gobbly-management"
    )
    if token:
        _client = axiom_py.Client(token=token)
        print(f"[logging] Axiom logging ENABLED (dataset={_dataset})")
    else:
        print(
            "[logging] Axiom logging DISABLED — AXIOM_TOKEN is not set; "
            "all log events will be dropped"
        )


def _send(event: dict) -> None:
    if not _client:
        return
    try:
        if "_time" not in event and "timestamp" not in event:
            event["_time"] = datetime.now(timezone.utc).isoformat()
        _client.ingest_events(dataset=_dataset, events=[event])
    except Exception:
        pass  # logging must never break the application


def log_event(event: dict) -> None:
    """Queue an event to be sent in a background daemon thread."""
    threading.Thread(target=_send, args=(event,), daemon=True).start()
