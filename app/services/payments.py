from __future__ import annotations
import os

import httpx

from app.db.supabase import get_client
from app.models import Payment


def _edge_function_url() -> str:
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    return f"{base}/functions/v1/redsys-sign"


class RedsysSignResult:
    def __init__(self, data: dict):
        self.Ds_MerchantParameters = data["Ds_MerchantParameters"]
        self.Ds_Signature = data["Ds_Signature"]
        self.Ds_SignatureVersion = data["Ds_SignatureVersion"]
        self.redsysUrl = data["redsysUrl"]
        self.orderNumber = data["orderNumber"]

    def dict(self):
        return {
            "Ds_MerchantParameters": self.Ds_MerchantParameters,
            "Ds_Signature": self.Ds_Signature,
            "Ds_SignatureVersion": self.Ds_SignatureVersion,
            "redsysUrl": self.redsysUrl,
            "orderNumber": self.orderNumber,
        }


def sign_redsys(amount: float, url_ok: str, url_ko: str) -> RedsysSignResult:
    resp = httpx.post(
        _edge_function_url(),
        json={"amount": amount, "urlOk": url_ok, "urlKo": url_ko},
        timeout=10,
    )
    resp.raise_for_status()
    return RedsysSignResult(resp.json())


def create_payment(order_id: str, amount: float, method: str) -> Payment:
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
