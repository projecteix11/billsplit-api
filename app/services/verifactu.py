"""Verifactu (AEAT e-invoice) access for the diner app — routed through the API.

The diner client used to read `verifactu_config` directly with the anon key and
call the `verifactu` edge function with the spoofable tenant *slug*. The Phase 0.4
RLS lockdown revoked anon's access to `verifactu_config`, and the slug never
matched the table's `tenant_id` (which holds the tenant uuid), so the diner
invoice flow was dead. This module is the Option-A fix: the API derives the
tenant uuid server-side (get_current_tenant) and talks to the edge function with
the service-role key — exactly like the Redsys path in services/payments.py.
"""
from __future__ import annotations

import os

import httpx

from app.db.supabase import get_client

# Invoice creation can trigger an AEAT mTLS round-trip (auto-send) and PDF
# generation rasterises a document — both are slower than a normal query.
_EDGE_TIMEOUT = 30.0


def _edge_url() -> str:
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    return f"{base}/functions/v1/verifactu"


def _call_edge(payload: dict) -> dict:
    """Invoke the verifactu edge function with the service-role key. The edge
    function uses service-role internally to bypass RLS; calling it server-side
    keeps both the anon key and the tenant identity out of the browser."""
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    resp = httpx.post(
        _edge_url(),
        json=payload,
        headers={"Authorization": f"Bearer {key}", "apikey": key},
        timeout=_EDGE_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_config(tenant_id: str) -> dict | None:
    """Public-safe Verifactu config for the diner: whether invoicing is enabled
    and whether the certificate is verified (drives auto-send). The sensitive
    columns (nif, cert paths, encrypted password) are never projected."""
    rows = (
        get_client()
        .table("verifactu_config")
        .select("enabled, cert_verified")
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return None
    row = rows[0]
    return {"enabled": bool(row.get("enabled")), "cert_verified": bool(row.get("cert_verified"))}


def create_invoice(
    tenant_id: str,
    order_id: str,
    payment_id: str,
    tipo_factura: str,
    destinatario_nombre: str | None = None,
    destinatario_nif: str | None = None,
) -> dict:
    """Create a Verifactu invoice for a paid order. `auto_send` is decided
    server-side from the tenant's cert_verified flag (never trusted from the
    client). Returns the edge function's {ok, invoice?, error?} envelope."""
    cfg = get_config(tenant_id)
    auto_send = bool(cfg and cfg.get("cert_verified"))
    return _call_edge(
        {
            "action": "create-invoice",
            "tenant_id": tenant_id,
            "order_id": order_id,
            "payment_id": payment_id,
            "tipo_factura": tipo_factura,
            "destinatario_nombre": destinatario_nombre,
            "destinatario_nif": destinatario_nif,
            "auto_send": auto_send,
        }
    )


def generate_pdf(tenant_id: str, invoice_id: str) -> dict:
    """Render + store the invoice PDF. Returns {ok, pdf_url?, error?}."""
    return _call_edge(
        {
            "action": "generate-pdf",
            "invoice_id": invoice_id,
            "tenant_id": tenant_id,
        }
    )
