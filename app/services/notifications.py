import httpx

from app.db import supabase


def broadcast_notification(
    title: str,
    description: str | None = None,
    notification_type: str = "system_alert",
    params: dict | None = None,
) -> None:
    """Send a realtime broadcast notification to all connected frontend clients."""
    payload = {
        "type": notification_type,
        "titleKey": title,
    }
    if description:
        payload["descriptionKey"] = description
    if params:
        payload["params"] = params

    resp = httpx.post(
        f"{supabase.get_base_url()}/realtime/v1/api/broadcast",
        json={
            "messages": [
                {
                    "topic": "system-notifications",
                    "event": "notification",
                    "payload": payload,
                }
            ]
        },
        headers={
            "apikey": supabase.get_api_key(),
            "Authorization": f"Bearer {supabase.get_api_key()}",
        },
        timeout=10,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"broadcast failed ({resp.status_code}): {resp.text}")
