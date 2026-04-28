import os
import requests

_session: requests.Session | None = None
_base_url: str = ""
_api_key: str = ""


def init() -> None:
    global _session, _base_url, _api_key

    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError("missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")

    _base_url = url
    _api_key = key

    _session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=20,
        pool_maxsize=100,
    )
    _session.mount("https://", adapter)
    _session.mount("http://", adapter)
    _session.headers.update({
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    })


def _request(method: str, table: str, query: str = "", body=None, prefer: str = "", result_type=None):
    url = f"{_base_url}/rest/v1/{table}"
    if query:
        url += f"?{query}"

    headers = {}
    if prefer:
        headers["Prefer"] = prefer

    resp = _session.request(method, url, json=body, headers=headers, timeout=10)

    if resp.status_code >= 400:
        try:
            err = resp.json()
            msg = err.get("message", resp.text)
        except Exception:
            msg = resp.text
        raise RuntimeError(f"supabase {resp.status_code}: {msg}")

    if result_type is not None and resp.content and resp.text != "null":
        return resp.json()
    return None


def select(table: str, query: str = ""):
    return _request("GET", table, query=query, result_type=True) or []


def insert(table: str, body, return_result: bool = True):
    prefer = "return=representation" if return_result else ""
    return _request("POST", table, body=body, prefer=prefer, result_type=return_result)


def update(table: str, query: str, body):
    _request("PATCH", table, query=query, body=body)


def delete(table: str, query: str):
    _request("DELETE", table, query=query)


def create_auth_user(email: str, password: str, user_metadata: dict) -> dict:
    """Create a user via Supabase Auth Admin API (requires service_role key)."""
    resp = _session.post(
        f"{_base_url}/auth/v1/admin/users",
        json={
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": user_metadata,
        },
        timeout=10,
    )
    if resp.status_code >= 400:
        try:
            err = resp.json()
            msg = err.get("msg", err.get("message", resp.text))
        except Exception:
            msg = resp.text
        raise RuntimeError(f"failed to create user: {msg}")
    return resp.json()


def delete_auth_user(user_id: str) -> None:
    """Delete a user via Supabase Auth Admin API (requires service_role key)."""
    resp = _session.delete(
        f"{_base_url}/auth/v1/admin/users/{user_id}",
        timeout=10,
    )
    if resp.status_code >= 400:
        try:
            err = resp.json()
            msg = err.get("msg", err.get("message", resp.text))
        except Exception:
            msg = resp.text
        raise RuntimeError(f"failed to delete user: {msg}")


def verify_token(token: str) -> str:
    user_id, _ = verify_token_full(token)
    return user_id


def verify_token_full(token: str) -> tuple[str, str]:
    """Verify token and return (user_id, tenant_id)."""
    resp = _session.get(
        f"{_base_url}/auth/v1/user",
        headers={"apikey": _api_key, "Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if resp.status_code != 200:
        raise ValueError("invalid or expired token")
    user = resp.json()
    user_id = user.get("id", "")
    if not user_id:
        raise ValueError("invalid token: no user id")
    tenant_id = str((user.get("user_metadata") or {}).get("tenant_id", ""))
    return user_id, tenant_id
