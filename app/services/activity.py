from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Request

from app.db.supabase import get_client, verify_token_full
from app.models import ActivityEvent, CreateActivityEventBody, NewOrderItem


ROLE_ACTOR: dict[str, tuple[str, str]] = {
    "admin": ("management", "Management"),
    "developer": ("management", "Management"),
    "waiter": ("waiter", "Camarero"),
    "kitchen": ("kitchen", "Cocina"),
}

KITCHEN_STATUS_LABELS = {
    "pending": "pendiente",
    "cooking": "en cocina",
    "ready": "listo para servir",
    "delivered": "servido",
    "cancelled": "cancelado",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unique_tags(tags: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for tag in tags or []:
        clean = str(tag).strip().lower()
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


def _safe_insert(row: dict[str, Any], *, raise_errors: bool = False) -> ActivityEvent | None:
    try:
        inserted = get_client().table("activity_events").insert(row).execute().data
        if not inserted:
            if raise_errors:
                raise RuntimeError("failed to insert activity event")
            return None
        return ActivityEvent(**inserted[0])
    except Exception as exc:
        if raise_errors:
            raise
        print(f"[activity] failed to record event: {exc}")
        return None


def actor_from_request(request: Request, *, customer_name: str | None = None) -> tuple[str, str | None, str]:
    user_id = getattr(request.state, "user_id", None)
    role = getattr(request.state, "role", None)

    if not user_id:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            try:
                user_id, tenant_id, role = verify_token_full(header[7:])
                request.state.user_id = user_id
                request.state.tenant_id = tenant_id
                request.state.role = role
            except Exception:
                user_id = None
                role = None

    if user_id:
        actor_type, actor_name = ROLE_ACTOR.get(str(role), ("management", "Management"))
        return actor_type, user_id, actor_name

    if customer_name:
        return "customer", None, f'cliente "{customer_name}"'
    return "customer", None, "Cliente"


def record_event(
    *,
    tenant_id: str,
    action: str,
    category: str,
    title: str,
    description: str,
    actor_type: str = "system",
    actor_id: str | None = None,
    actor_name: str | None = None,
    source: str = "system",
    table_id: str | None = None,
    table_number: int | None = None,
    order_id: str | None = None,
    order_item_id: str | None = None,
    dish_id: str | None = None,
    dish_name: str | None = None,
    quantity: int | None = None,
    amount: float | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    occurred_at: str | None = None,
    raise_errors: bool = False,
) -> ActivityEvent | None:
    row = {
        "tenant_id": tenant_id,
        "occurred_at": occurred_at or _now_iso(),
        "actor_type": actor_type,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "source": source,
        "action": action,
        "category": category,
        "title": title,
        "description": description,
        "table_id": table_id,
        "table_number": table_number,
        "order_id": order_id,
        "order_item_id": order_item_id,
        "dish_id": dish_id,
        "dish_name": dish_name,
        "quantity": quantity,
        "amount": amount,
        "tags": _unique_tags([category, action, *(tags or [])]),
        "metadata": metadata or {},
    }
    return _safe_insert(row, raise_errors=raise_errors)


def create_manual_event(
    body: CreateActivityEventBody,
    *,
    tenant_id: str,
    request: Request,
) -> ActivityEvent:
    actor_type, actor_id, actor_name = actor_from_request(request)
    return record_event(
        tenant_id=tenant_id,
        occurred_at=body.occurred_at,
        actor_type=body.actor_type or actor_type,
        actor_id=actor_id,
        actor_name=body.actor_name or actor_name,
        source=body.source,
        action=body.action,
        category=body.category,
        title=body.title,
        description=body.description,
        table_id=body.table_id,
        table_number=body.table_number,
        order_id=body.order_id,
        order_item_id=body.order_item_id,
        dish_id=body.dish_id,
        dish_name=body.dish_name,
        quantity=body.quantity,
        amount=body.amount,
        tags=body.tags,
        metadata=body.metadata,
        raise_errors=True,
    )


def list_events(
    *,
    tenant_id: str,
    category: str | None = None,
    tag: str | None = None,
    actor_type: str | None = None,
    table_number: int | None = None,
    query: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
) -> list[ActivityEvent]:
    limit = max(1, min(limit, 500))
    fetch_limit = 500 if query or (tag and tag != "all") else limit

    q = (
        get_client()
        .table("activity_events")
        .select("*")
        .eq("tenant_id", tenant_id)
        .order("occurred_at", desc=True)
        .limit(fetch_limit)
    )

    if category and category != "all":
        q = q.eq("category", category)
    if actor_type and actor_type != "all":
        q = q.eq("actor_type", actor_type)
    if table_number is not None:
        q = q.eq("table_number", table_number)
    if date_from:
        q = q.gte("occurred_at", date_from)
    if date_to:
        q = q.lte("occurred_at", date_to)

    rows = q.execute().data or []

    if tag and tag != "all":
        needle_tag = tag.strip().lower()
        rows = [
            row for row in rows
            if needle_tag in [str(value).lower() for value in (row.get("tags") or [])]
        ]

    if query:
        needle = query.strip().lower()
        rows = [
            row for row in rows
            if needle in str(row.get("title") or "").lower()
            or needle in str(row.get("description") or "").lower()
            or needle in str(row.get("dish_name") or "").lower()
            or needle in str(row.get("actor_name") or "").lower()
        ]

    rows = rows[:limit]

    return [ActivityEvent(**row) for row in rows]


def get_order_context(order_id: str) -> dict[str, Any] | None:
    rows = (
        get_client()
        .table("orders")
        .select("id,tenant_id,table_id,table_number,status,total")
        .eq("id", order_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def get_order_item_context(item_id: str) -> dict[str, Any] | None:
    rows = (
        get_client()
        .table("order_items")
        .select("id,order_id,dish_id,dish_name,dish_price,quantity,kitchen_status,payment_status,order:orders(id,tenant_id,table_id,table_number,status,total)")
        .eq("id", item_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def get_order_items_context(item_ids: list[str]) -> list[dict[str, Any]]:
    if not item_ids:
        return []
    rows = (
        get_client()
        .table("order_items")
        .select("id,order_id,dish_id,dish_name,dish_price,quantity,kitchen_status,payment_status,order:orders(id,tenant_id,table_id,table_number,status,total)")
        .in_("id", item_ids)
        .execute()
        .data
        or []
    )
    return rows


def record_items_added(
    *,
    request: Request,
    tenant_id: str,
    order_id: str,
    table_id: str,
    table_number: int,
    items: list[NewOrderItem],
    source: str | None = None,
) -> None:
    first_customer = next((item.diner_name for item in items if item.diner_name), None)
    actor_type, actor_id, actor_name = actor_from_request(request, customer_name=first_customer)
    source = source or ("client" if actor_type == "customer" else "management")

    for item in items:
        quantity = int(item.quantity or 0)
        actor_label = actor_name or "Sistema"
        if actor_type == "customer":
            actor_label = actor_name or "Cliente"
            description = (
                f"{actor_label} de mesa {table_number} ha añadido "
                f"{quantity} {item.dish_name} a través de la app de cliente."
            )
        else:
            description = f"{actor_label} ha añadido {quantity} {item.dish_name} a mesa {table_number}."

        record_event(
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            actor_name=actor_name,
            source=source,
            action="item_added",
            category="orders",
            title=f"{item.dish_name} añadido",
            description=description,
            table_id=table_id,
            table_number=table_number,
            order_id=order_id,
            dish_id=item.dish_id,
            dish_name=item.dish_name,
            quantity=quantity,
            amount=float(item.dish_price) * quantity,
            tags=["items", "food", actor_type, f"table-{table_number}"],
            metadata={
                "notes": item.notes,
                "diner_name": item.diner_name,
                "category_id": item.category_id,
                "customization": item.customization,
            },
        )


def record_table_opened(
    *,
    request: Request,
    tenant_id: str,
    order_id: str,
    table_id: str,
    table_number: int,
) -> None:
    actor_type, actor_id, actor_name = actor_from_request(request)
    actor_label = actor_name or "Sistema"
    record_event(
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
        source="management" if actor_type != "customer" else "client",
        action="table_opened",
        category="tables",
        title=f"Mesa {table_number} abierta",
        description=f"{actor_label} ha abierto la mesa {table_number}.",
        table_id=table_id,
        table_number=table_number,
        order_id=order_id,
        tags=["tables", "opened", actor_type, f"table-{table_number}"],
    )


def record_order_closed(*, request: Request, order: dict[str, Any], tenant_id: str) -> None:
    actor_type, actor_id, actor_name = actor_from_request(request)
    actor_label = actor_name or "Sistema"
    table_number = order.get("table_number")
    record_event(
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
        source="management" if actor_type != "customer" else "client",
        action="table_closed",
        category="tables",
        title=f"Mesa {table_number} cerrada",
        description=f"{actor_label} ha cerrado la mesa {table_number}.",
        table_id=order.get("table_id"),
        table_number=table_number,
        order_id=order.get("id"),
        amount=order.get("total"),
        tags=["tables", "closed", "orders", actor_type, f"table-{table_number}"],
    )


def record_payment_created(
    *,
    request: Request,
    tenant_id: str,
    order: dict[str, Any] | None,
    order_id: str,
    amount: float,
    method: str,
) -> None:
    actor_type, actor_id, actor_name = actor_from_request(request)
    actor_label = actor_name or "Sistema"
    table_number = order.get("table_number") if order else None
    table_text = f" de la mesa {table_number}" if table_number is not None else ""
    record_event(
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
        source="management" if actor_type != "customer" else "client",
        action="payment_created",
        category="payments",
        title="Cuenta cobrada",
        description=f"{actor_label} ha cobrado {amount:.2f} EUR{table_text}.",
        table_id=order.get("table_id") if order else None,
        table_number=table_number,
        order_id=order_id,
        amount=amount,
        tags=["payments", "checkout", actor_type, *( [f"table-{table_number}"] if table_number is not None else [] )],
        metadata={"method": method},
    )


def record_kitchen_status_changed(
    *,
    request: Request,
    tenant_id: str,
    item: dict[str, Any] | None,
    status: str,
) -> None:
    if not item:
        return
    actor_type, actor_id, actor_name = actor_from_request(request)
    order = item.get("order") or {}
    table_number = order.get("table_number")
    dish_name = item.get("dish_name") or "Plato"
    label = KITCHEN_STATUS_LABELS.get(status, status)
    if status == "ready":
        description = f"{dish_name} ha salido de cocina para la mesa {table_number}."
    elif status == "delivered":
        description = f"{dish_name} se ha servido en la mesa {table_number}."
    else:
        actor_label = actor_name or "Cocina"
        description = f"{actor_label} ha marcado {dish_name} como {label} para la mesa {table_number}."

    record_event(
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
        source="kitchen",
        action=f"kitchen_{status}",
        category="kitchen",
        title=f"{dish_name}: {label}",
        description=description,
        table_id=order.get("table_id"),
        table_number=table_number,
        order_id=item.get("order_id"),
        order_item_id=item.get("id"),
        dish_id=item.get("dish_id"),
        dish_name=dish_name,
        quantity=item.get("quantity"),
        tags=["kitchen", "food", status, actor_type, *( [f"table-{table_number}"] if table_number is not None else [] )],
        metadata={"previous_status": item.get("kitchen_status"), "new_status": status},
    )
