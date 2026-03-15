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


def verify_token(token: str) -> str:
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
    return user_id
