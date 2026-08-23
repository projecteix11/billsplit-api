from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.backends import default_backend
try:
    # cryptography >= 44.0 moved TripleDES to decrepit
    from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
except ImportError:
    from cryptography.hazmat.primitives.ciphers.algorithms import TripleDES  # type: ignore[no-redef]

from app.db.supabase import get_client
from app.models import Payment, RedsysInitiateItem
from app.services.orders import (
    get_order_by_id,
    _calculate_tax,
    _round2,
)

# public.payments.payment_method allows: bizum, apple_pay, google_pay, card, cash.
_VALID_METHODS = {"bizum", "apple_pay", "google_pay", "card", "cash"}

# Redsys response codes that indicate a successful payment (0000–0099).
_REDSYS_SUCCESS_CODES = set(range(0, 100))


def _edge_function_url() -> str:
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    return f"{base}/functions/v1/redsys-sign"


def _service_key() -> str:
    return os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


def _redsys_secret() -> str:
    """Return the shared Redsys 3DES/HMAC secret (same as used in redsys-sign edge function)."""
    return os.getenv("REDSYS_SECRET", "sq7HjrUOBfKmC576ILgskD5srU870gJ7")


def _generate_order_number() -> str:
    """12 numeric chars. Redsys requires the first 4 to be digits; all-numeric is
    safe. Collisions are guarded by the unique index on redsys_order_number."""
    return "".join(secrets.choice("0123456789") for _ in range(12))


# ─── Redsys HMAC_SHA256_V1 signature helpers ──────────────────────────────────

def _derive_redsys_key(secret: str, order_number: str) -> bytes:
    """Derive a per-order 3DES key.  Mirrors the JS implementation in redsys-sign:
    1. Base64-decode the merchant secret, take first 24 bytes (3DES key).
    2. Zero-pad the order-number to the next 8-byte boundary.
    3. Encrypt with 3DES-CBC (zero IV, no PKCS7 padding).
    """
    raw_key = base64.b64decode(secret)[:24]
    l = ((len(order_number) + 7) // 8) * 8  # next 8-byte boundary
    padded = order_number.ljust(l, "\x00")[:l].encode("ascii")

    iv = b"\x00" * 8
    cipher = Cipher(TripleDES(raw_key), modes.CBC(iv), backend=default_backend())
    enc = cipher.encryptor()
    # No PKCS7 padding — block is already a multiple of 8 bytes
    encrypted = enc.update(padded) + enc.finalize()
    return encrypted[:l]


def _compute_redsys_signature(merchant_params_b64: str, order_number: str) -> str:
    """Compute HMAC-SHA256 over the base64-encoded merchant params.
    Returns the signature as a base64 string."""
    key = _derive_redsys_key(_redsys_secret(), order_number)
    sig = hmac.new(key, merchant_params_b64.encode("ascii"), hashlib.sha256).digest()
    return base64.b64encode(sig).decode("ascii")


def verify_redsys_signature(ds_params: str, ds_signature: str) -> dict:
    """Validate a Redsys HMAC_SHA256_V1 S2S notification.

    Args:
        ds_params:    raw value of Ds_MerchantParameters (base64-encoded JSON).
        ds_signature: raw value of Ds_Signature (base64-encoded HMAC).

    Returns:
        The decoded merchant-parameters dict on success.

    Raises:
        ValueError: if the signature is invalid or the response code indicates failure.
    """
    # Decode merchant parameters (handling URL-safe base64 replacements)
    try:
        normalized_params = ds_params.replace("-", "+").replace("_", "/")
        # Redsys sometimes sends padded, sometimes not — add padding just in case
        padded = normalized_params + "=" * (-len(normalized_params) % 4)
        decoded = json.loads(base64.b64decode(padded))
    except Exception as exc:
        raise ValueError(f"cannot decode Ds_MerchantParameters: {exc}") from exc

    order_number = decoded.get("Ds_Order", "")
    if not order_number:
        raise ValueError("Ds_Order missing from merchant parameters")

    expected = _compute_redsys_signature(ds_params, order_number)

    # Normalize ds_signature from URL-safe base64 if needed
    normalized_sig = ds_signature.replace("-", "+").replace("_", "/")

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(
        expected.encode("ascii"),
        normalized_sig.encode("ascii"),
    ):
        raise ValueError("Redsys signature mismatch — possible tampering")

    # Response code 0000-0099 → authorised; anything else → failure/rejection
    raw_code = str(decoded.get("Ds_Response", "9999")).lstrip("0") or "0"
    code = int(raw_code)
    if code not in _REDSYS_SUCCESS_CODES:
        raise ValueError(f"Redsys response code indicates failure: {decoded.get('Ds_Response')}")

    return decoded


def confirm_redsys_payment(redsys_order_number: str, amount_cents: int) -> None:
    """Mark a pending Redsys payment as confirmed and update order items.

    Called by the S2S Redsys notification endpoint after the signature has been
    verified.  This is the SOLE writer of payment_status='paid' for online payments.

    Steps:
    1. Look up the pending payment row by its Redsys order number.
    2. Mark payment as confirmed with the server-confirmed amount.
    3. Apply covered_items -> increment paid_portions / set payment_status='paid'.
    4. Update order.amount_paid.
    5. Auto-close the order if all items are fully paid.
    """
    rows = (
        get_client()
        .table("payments")
        .select("id, order_id, covered_items, status, amount")
        .eq("redsys_order_number", redsys_order_number)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise ValueError(f"no payment found for redsys_order_number={redsys_order_number}")

    payment = rows[0]
    if payment["status"] == "confirmed":
        # Idempotent — Redsys may send the callback more than once
        return

    amount_eur = _round2(amount_cents / 100)

    # 1. Confirm the payment row
    get_client().table("payments").update({
        "status": "confirmed",
        "amount": amount_eur,
        "total_charged": amount_eur,
    }).eq("id", payment["id"]).execute()

    order_id = payment["order_id"]
    covered_items: list[dict] = payment.get("covered_items") or []

    if covered_items:
        # 2. Update paid_portions / payment_status for each covered item
        for ci in covered_items:
            item_id = ci.get("item_id")
            portions = max(1, int(ci.get("portions", 1)))
            if not item_id:
                continue

            item_rows = (
                get_client()
                .table("order_items")
                .select("id, split_portions, paid_portions, payment_status")
                .eq("id", item_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            if not item_rows:
                continue

            item = item_rows[0]
            split = max(1, int(item.get("split_portions") or 1))
            already_paid = (
                split if item.get("payment_status") == "paid"
                else int(item.get("paid_portions") or 0)
            )
            new_paid = min(split, already_paid + portions)
            new_status = "paid" if new_paid >= split else "unassigned"

            get_client().table("order_items").update({
                "paid_portions": new_paid,
                "payment_status": new_status,
            }).eq("id", item_id).execute()
    else:
        # Fallback: no covered_items -> mark all unpaid items as paid
        get_client().table("order_items").update({
            "payment_status": "paid",
        }).eq("order_id", order_id).neq("payment_status", "paid").execute()

    # 3. Update order amount_paid
    all_confirmed = (
        get_client()
        .table("payments")
        .select("amount")
        .eq("order_id", order_id)
        .eq("status", "confirmed")
        .execute()
        .data
        or []
    )
    total_paid = _round2(sum(float(p["amount"]) for p in all_confirmed))
    get_client().table("orders").update({
        "amount_paid": total_paid,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", order_id).execute()

    # 4. Auto-close order if fully paid
    from app.services.orders import _maybe_close_order  # avoid circular import
    _maybe_close_order(order_id)


def _sign_locally(amount: float, order_number: str, url_ok: str, url_ko: str, pay_method: str) -> dict:
    merchant_code = os.getenv("REDSYS_MERCHANT_CODE", "263100000")
    terminal = os.getenv("REDSYS_TERMINAL", "007")
    redsys_url = os.getenv("REDSYS_URL", "https://sis-t.redsys.es:25443/sis/realizarPago")
    notify_url = os.getenv("REDSYS_NOTIFY_URL", "https://api.gobbly.app/payments/redsys-notify")
    pay_map = {"card": "C", "bizum": "z", "google_pay": "xpay", "apple_pay": "xpay"}

    amount_cents = str(int(round(amount * 100)))
    params = {
        "DS_MERCHANT_AMOUNT": amount_cents,
        "DS_MERCHANT_ORDER": order_number,
        "DS_MERCHANT_MERCHANTCODE": merchant_code,
        "DS_MERCHANT_TERMINAL": terminal,
        "DS_MERCHANT_TRANSACTIONTYPE": "0",
        "DS_MERCHANT_CURRENCY": "978",
        "DS_MERCHANT_URLOK": url_ok,
        "DS_MERCHANT_URLKO": url_ko,
        "DS_MERCHANT_MERCHANTURL": notify_url,
    }
    if pay_method in pay_map:
        params["DS_MERCHANT_PAYMETHODS"] = pay_map[pay_method]

    merchant_params_b64 = base64.b64encode(json.dumps(params).encode("utf-8")).decode("ascii")
    sig = _compute_redsys_signature(merchant_params_b64, order_number)

    return {
        "Ds_MerchantParameters": merchant_params_b64,
        "Ds_Signature": sig,
        "Ds_SignatureVersion": "HMAC_SHA256_V1",
        "redsysUrl": redsys_url,
        "orderNumber": order_number,
    }


def _sign_via_edge(amount: float, order_number: str, url_ok: str, url_ko: str, pay_method: str) -> dict:
    """Call the (service-role-only) redsys-sign edge function with the
    server-computed amount and order number. Falls back to local signing if
    the edge function is unavailable."""
    key = _service_key()
    try:
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
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return _sign_locally(amount, order_number, url_ok, url_ko, pay_method)


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
            continue
        portions = max(1, sel.portions)
        if portions > remaining:
            portions = remaining
        # Per-portion price of this line, pre-tax.
        split_div = max(1, item.split_portions)
        subtotal += item.dish_price * item.quantity * portions / split_div
        covered.append({"item_id": item.id, "portions": portions})

    if not covered:
        raise ValueError("all selected items are already paid")

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


def create_payment(
    order_id: str,
    amount: float,
    method: str,
    covered_items=None,
) -> Payment:
    """Manual/cash payment recorded by authenticated staff. Online (Redsys)
    payments are confirmed only by the S2S callback, never here."""
    covered = []
    if covered_items:
        order = get_order_by_id(order_id)
        if order:
            by_id = {i.id: i for i in order.items}
            for sel in covered_items:
                if isinstance(sel, dict):
                    sel_item_id = sel.get("itemId") or sel.get("item_id")
                    sel_portions = sel.get("portions", 1)
                else:
                    sel_item_id = getattr(sel, "itemId", None) or getattr(sel, "item_id", None)
                    sel_portions = getattr(sel, "portions", 1)

                if not sel_item_id:
                    continue
                item = by_id.get(sel_item_id)
                if item:
                    remaining = item.split_portions - item.paid_portions
                    portions = max(1, int(sel_portions))
                    if portions > remaining:
                        portions = remaining
                    covered.append({"item_id": item.id, "portions": portions})

    row = {
        "order_id": order_id,
        "amount": amount,
        "tip_amount": 0,
        "total_charged": amount,
        "payment_method": method,
        "status": "confirmed",
    }
    if covered:
        row["covered_items"] = covered

    inserted = get_client().table("payments").insert(row).execute().data
    if not inserted:
        raise RuntimeError("failed to create payment")

    payment_record = Payment(**inserted[0])

    # Update paid portions and status for covered items in DB
    if covered:
        for ci in covered:
            item_id = ci.get("item_id")
            portions = max(1, int(ci.get("portions", 1)))
            if not item_id:
                continue

            item_rows = (
                get_client()
                .table("order_items")
                .select("id, split_portions, paid_portions, payment_status")
                .eq("id", item_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            if not item_rows:
                continue

            item = item_rows[0]
            split = max(1, int(item.get("split_portions") or 1))
            already_paid = (
                split if item.get("payment_status") == "paid"
                else int(item.get("paid_portions") or 0)
            )
            new_paid = min(split, already_paid + portions)
            new_status = "paid" if new_paid >= split else "unassigned"

            get_client().table("order_items").update({
                "paid_portions": new_paid,
                "payment_status": new_status,
            }).eq("id", item_id).execute()

    # Recalculate amount_paid for the order
    all_confirmed = (
        get_client()
        .table("payments")
        .select("amount")
        .eq("order_id", order_id)
        .eq("status", "confirmed")
        .execute()
        .data
        or []
    )
    total_paid = _round2(sum(float(p["amount"]) for p in all_confirmed))
    get_client().table("orders").update({
        "amount_paid": total_paid,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", order_id).execute()

    # Auto-close order if fully paid
    from app.services.orders import _maybe_close_order  # avoid circular import
    _maybe_close_order(order_id)

    return payment_record

