"""Event factory for the BillSplit API backend.

Produces dicts matching the Logging API's EventCreate schema.
"""

from typing import Optional

_SOURCE = "🐍 api"


class LogFactory:

    @staticmethod
    def canonical_line(
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
        client_ip: Optional[str] = None,
        metadata: Optional[dict] = None,
        source: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> dict:
        level = (
            "error" if status_code >= 500
            else "warning" if status_code >= 400
            else "info"
        )
        event_type = "api_error" if status_code >= 400 else "system_event"
        meta = {**(metadata or {})}
        if request_id:
            meta["request_id"] = request_id
        return {
            "type": event_type,
            "level": level,
            "source": source or _SOURCE,
            "module": "http",
            "action": f"{method} {path} -> {status_code}",
            "http_method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 2),
            "user_id": user_id,
            "request_id": request_id,
            "correlation_id": correlation_id,
            "client_ip": client_ip,
            "metadata": meta,
        }

    @staticmethod
    def payment_event(
        action: str,
        order_id: str,
        amount: float,
        method: str,
        user_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> dict:
        level = "error" if error else "info"
        meta: dict = {"order_id": order_id, "amount": amount, "payment_method": method}
        if error:
            meta["error"] = error
        return {
            "type": "user_action",
            "level": level,
            "source": _SOURCE,
            "module": "payments",
            "action": action,
            "user_id": user_id,
            "metadata": meta,
        }

    @staticmethod
    def order_lifecycle(
        action: str,
        order_id: str,
        table_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        meta = {"order_id": order_id}
        if table_id:
            meta["table_id"] = table_id
        if metadata:
            meta.update(metadata)
        return {
            "type": "user_action",
            "level": "info",
            "source": _SOURCE,
            "module": "orders",
            "action": action,
            "metadata": meta,
        }

    @staticmethod
    def auth_event(
        action: str,
        user_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        return {
            "type": "auth_event",
            "level": "warning",
            "source": _SOURCE,
            "module": "auth",
            "action": action,
            "user_id": user_id,
            "metadata": metadata or {},
        }
