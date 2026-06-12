from __future__ import annotations
import os
import secrets

import httpx

from app.db.supabase import get_client
from app.models import Payment, RedsysInitiateItem
from app.services.orders import (
    get_order_by_id,
    _calculate_tax,
    _round2,
)

# public.payments.payment_method allows: bizum, apple_pay, google_pay, card, cash.
_VALID_METHODS = {"bizum", "apple_pay", "google_pay", "card", "cash"}


def _edge_function_url() -> str:
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    return f"{base}/functions/v1/redsys-sign"


def _service_key() -> str:
    return os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


def _generate_order_number() -> str:
    """12 numeric chars. Redsys requires the first 4 to be digits; all-numeric is
    safe. Collisions are guarded by the unique index on redsys_order_number."""
    return "".join(secrets.choice("0123456789") for _ in range(12))


def _sign_via_edge(amount: float, order_number: str, url_ok: str, url_ko: str, pay_method: str) -> dict:
    """Call the (service-role-only) redsys-sign edge function with the
    server-computed amount and order number. The edge function sets the S2S
    merchant URL itself, so it is never client-controlled."""
    key = _service_key()
    resp = httpx.post(
        _edge_function_url(),
        json={
            "amount": amount,
            "orderNumber": order_number,
            "urlOk": url_ok,
            "urlKo": url_ko,
            "payMethod": pay_method,
        },
        headers={"Authorization": f"Bearer {key}", "apikey": key},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def initiate_redsys(
    order_id: str,
    items: list[RedsysInitiateItem],
    method: str,
    url_ok: str,
    url_ko: str,
) -> dict:
    """Server-authoritative Redsys initiation. Computes the amount from the DB,
    persists a pending payment keyed to the generated Redsys order number, and
    returns a signed request. The amount is NEVER taken from the client."""
    if method not in _VALID_METHODS:
        raise ValueError(f"invalid payment method: {method}")
    if not items:
        raise ValueError("at least one item is required")

    order = get_order_by_id(order_id)
    if order is None:
        raise ValueError("order not found")

    by_id = {i.id: i for i in order.items}

    subtotal = 0.0
    covered: list[dict] = []
    for sel in items:
        item = by_id.get(sel.itemId)
        if item is None:
            raise ValueError(f"item {sel.itemId} does not belong to order {order_id}")
        remaining = item.split_portions - item.paid_portions
        if remaining <= 0:
            raise ValueError(f"item {sel.itemId} is already paid")
        portions = max(1, sel.portions)
        if portions > remaining:
            portions = remaining
        # Per-portion price of this line, pre-tax.
        subtotal += item.dish_price * item.quantity * portions / item.split_portions
        covered.append({"item_id": item.id, "portions": portions})

    subtotal = _round2(subtotal)
    if subtotal <= 0:
        raise ValueError("computed amount is zero")
    tax = _calculate_tax(subtotal)
    amount = _round2(subtotal + tax)

    # Persist the pending payment, retrying on the (rare) order-number collision.
    order_number = ""
    for _ in range(5):
        candidate = _generate_order_number()
        row = {
            "order_id": order_id,
            "amount": amount,
            "tip_amount": 0,
            "total_charged": amount,
            "payment_method": method,
            "status": "pending",
            "redsys_order_number": candidate,
            "covered_items": covered,
        }
        try:
            get_client().table("payments").insert(row).execute()
            order_number = candidate
            break
        except Exception as e:
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                continue
            raise
    if not order_number:
        raise RuntimeError("could not allocate a unique Redsys order number")

    return _sign_via_edge(amount, order_number, url_ok, url_ko, method)


def get_payment_by_redsys_order(order_number: str) -> Payment | None:
    """Look up a payment by its Redsys order number — the opaque 12-digit handle
    the client received at initiate. Used by the diner frontend after the S2S
    callback confirms, to obtain the payment id for a Verifactu invoice request
    (the client no longer creates the payment, so it can't know the id otherwise)."""
    rows = (
        get_client()
        .table("payments")
        .select("id, order_id, amount, tip_amount, total_charged, payment_method, status")
        .eq("redsys_order_number", order_number)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return None
    return Payment(**rows[0])


def create_payment(order_id: str, amount: float, method: str) -> Payment:
    """Manual/cash payment recorded by authenticated staff. Online (Redsys)
    payments are confirmed only by the S2S callback, never here."""
    row = {
        "order_id": order_id,
        "amount": amount,
        "tip_amount": 0,
        "total_charged": amount,
        "payment_method": method,
        "status": "confirmed",
    }

    inserted = get_client().table("payments").insert(row).execute().data
    if not inserted:
        raise RuntimeError("failed to create payment")
    return Payment(**inserted[0])
