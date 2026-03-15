from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import time

from Crypto.Cipher import DES3

from app.db import supabase
from app.models import Payment

REDSYS_URL = "https://sis-t.redsys.es:25443/sis/realizarPago"


def _redsys_secret() -> str:
    return os.getenv("REDSYS_SECRET", "sq7HjrUOBfKmC576ILgskD900SqIlHkI8awNPoDg")


def _redsys_merchant_code() -> str:
    return os.getenv("REDSYS_MERCHANT_CODE", "999008881")


def _redsys_terminal() -> str:
    return os.getenv("REDSYS_TERMINAL", "001")


def _derive_key(secret: str, order_number: str) -> bytes:
    key_bytes = base64.b64decode(secret)

    # 3DES requires exactly 24 bytes
    if len(key_bytes) < 24:
        key_bytes = key_bytes.ljust(24, b"\x00")
    else:
        key_bytes = key_bytes[:24]

    # Pad orderNumber to nearest multiple of 8 with null bytes
    l = ((len(order_number) + 7) // 8) * 8
    padded = order_number.encode().ljust(l, b"\x00")

    iv = b"\x00" * 8
    cipher = DES3.new(key_bytes, DES3.MODE_CBC, iv)
    return cipher.encrypt(padded)


class RedsysSignResult:
    def __init__(self, merchant_params: str, signature: str, order_number: str):
        self.Ds_MerchantParameters = merchant_params
        self.Ds_Signature = signature
        self.Ds_SignatureVersion = "HMAC_SHA256_V1"
        self.redsysUrl = REDSYS_URL
        self.orderNumber = order_number

    def dict(self):
        return {
            "Ds_MerchantParameters": self.Ds_MerchantParameters,
            "Ds_Signature": self.Ds_Signature,
            "Ds_SignatureVersion": self.Ds_SignatureVersion,
            "redsysUrl": self.redsysUrl,
            "orderNumber": self.orderNumber,
        }


def sign_redsys(amount: float, url_ok: str, url_ko: str) -> RedsysSignResult:
    order_number = str(int(time.time() * 1000))
    if len(order_number) > 12:
        order_number = order_number[-12:]

    amount_cents = str(int(amount * 100))

    params = {
        "DS_MERCHANT_AMOUNT": amount_cents,
        "DS_MERCHANT_ORDER": order_number,
        "DS_MERCHANT_MERCHANTCODE": _redsys_merchant_code(),
        "DS_MERCHANT_TERMINAL": _redsys_terminal(),
        "DS_MERCHANT_TRANSACTIONTYPE": "0",
        "DS_MERCHANT_CURRENCY": "978",
        "DS_MERCHANT_URLOK": url_ok,
        "DS_MERCHANT_URLKO": url_ko,
    }

    params_json = json.dumps(params, separators=(",", ":"))
    merchant_params = base64.b64encode(params_json.encode()).decode()

    derived_key = _derive_key(_redsys_secret(), order_number)
    mac = hmac.new(derived_key, merchant_params.encode(), hashlib.sha256)
    signature = base64.b64encode(mac.digest()).decode()

    return RedsysSignResult(merchant_params, signature, order_number)


def create_payment(order_id: str, amount: float, method: str) -> Payment:
    row = {
        "order_id": order_id,
        "amount": amount,
        "tip_amount": 0,
        "total_charged": amount,
        "payment_method": method,
        "status": "confirmed",
    }

    inserted = supabase.insert("payments", row, return_result=True)
    if not inserted:
        raise RuntimeError("failed to create payment")
    return Payment(**inserted[0])
