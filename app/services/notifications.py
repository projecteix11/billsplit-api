import httpx

from app.db.supabase import get_client, get_base_url, get_api_key


def broadcast_notification(
    tenant_id: str,
    title: str,
    description: str | None = None,
    notification_type: str = "system_alert",
    params: dict | None = None,
) -> None:
    payload = {
        "type": notification_type,
        "titleKey": title,
    }
    if description:
        payload["descriptionKey"] = description
    if params:
        payload["params"] = params

    row: dict = {
        "tenant_id": tenant_id,
        "type": notification_type,
        "title_key": title,
    }
    if description:
        row["description_key"] = description
    if params:
        row["params"] = params

    get_client().table("notifications").insert(row).execute()

    resp = httpx.post(
        f"{get_base_url()}/realtime/v1/api/broadcast",
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
            "apikey": get_api_key(),
            "Authorization": f"Bearer {get_api_key()}",
        },
        timeout=10,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"broadcast failed ({resp.status_code}): {resp.text}")
