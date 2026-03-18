"""
Tests for:
  POST /api/payments               – create payment (rate limited)
  POST /api/payments/redsys-sign   – generate Redsys payment signature (rate limited)

The Redsys signing is pure crypto – we can test it without mocking by using
known inputs and verifying the output structure.
"""

import base64
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from tests.conftest import make_payment


# ---------------------------------------------------------------------------
# POST /api/payments
# ---------------------------------------------------------------------------

VALID_TOKEN = "valid-bearer-token"
VALID_USER_ID = "user-uuid-123"


def _auth_headers(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestCreatePayment:
    _valid_body = {
        "orderId": "order-1",
        "amount": 27.50,
        "method": "card",
    }

    def test_create_payment_returns_201_on_success(self, client: TestClient):
        payment = make_payment()
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            with patch("app.services.payments.supabase") as mock_sb:
                mock_sb.insert.return_value = [payment]
                resp = client.post(
                    "/api/payments",
                    json=self._valid_body,
                    headers=_auth_headers(),
                )

        assert resp.status_code == 201

    def test_create_payment_returns_data_envelope(self, client: TestClient):
        payment = make_payment()
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            with patch("app.services.payments.supabase") as mock_sb:
                mock_sb.insert.return_value = [payment]
                resp = client.post(
                    "/api/payments",
                    json=self._valid_body,
                    headers=_auth_headers(),
                )

        body = resp.json()
        assert "data" in body
        assert body["error"] is None

    def test_create_payment_returns_correct_payment_fields(self, client: TestClient):
        payment = make_payment()
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            with patch("app.services.payments.supabase") as mock_sb:
                mock_sb.insert.return_value = [payment]
                resp = client.post(
                    "/api/payments",
                    json=self._valid_body,
                    headers=_auth_headers(),
                )

        data = resp.json()["data"]
        assert data["id"] == "pay-1"
        assert data["order_id"] == "order-1"
        assert data["amount"] == 27.50
        assert data["tip_amount"] == 0.0
        assert data["total_charged"] == 27.50
        assert data["payment_method"] == "card"
        assert data["status"] == "confirmed"

    def test_create_payment_inserts_with_correct_fields(self, client: TestClient):
        payment = make_payment()
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            with patch("app.services.payments.supabase") as mock_sb:
                mock_sb.insert.return_value = [payment]
                client.post(
                    "/api/payments",
                    json=self._valid_body,
                    headers=_auth_headers(),
                )

        call_args = mock_sb.insert.call_args
        assert call_args[0][0] == "payments"
        body = call_args[0][1]
        assert body["order_id"] == "order-1"
        assert body["amount"] == 27.50
        assert body["tip_amount"] == 0
        assert body["total_charged"] == 27.50
        assert body["payment_method"] == "card"
        assert body["status"] == "confirmed"

    def test_create_payment_missing_order_id_returns_422(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post("/api/payments", json={"amount": 10.0, "method": "cash"}, headers=_auth_headers())
        assert resp.status_code == 422

    def test_create_payment_missing_amount_returns_422(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post("/api/payments", json={"orderId": "o-1", "method": "cash"}, headers=_auth_headers())
        assert resp.status_code == 422

    def test_create_payment_missing_method_returns_422(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post("/api/payments", json={"orderId": "o-1", "amount": 10.0}, headers=_auth_headers())
        assert resp.status_code == 422

    def test_create_payment_zero_amount_returns_422(self, client: TestClient):
        """amount=0 is rejected by Pydantic Field(gt=0) — returns 422."""
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments",
                json={"orderId": "o-1", "amount": 0, "method": "cash"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 422

    def test_create_payment_empty_order_id_returns_422(self, client: TestClient):
        """Empty orderId rejected by Pydantic Field(min_length=1) — returns 422."""
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments",
                json={"orderId": "", "amount": 10.0, "method": "cash"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 422

    def test_create_payment_returns_500_on_db_error(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            with patch("app.services.payments.supabase") as mock_sb:
                mock_sb.insert.side_effect = RuntimeError("supabase 500: error")
                resp = client.post(
                    "/api/payments",
                    json=self._valid_body,
                    headers=_auth_headers(),
                )

        assert resp.status_code == 500
        body = resp.json()
        assert body["data"] is None
        assert body["error"] is not None

    def test_create_payment_returns_500_when_insert_returns_nothing(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            with patch("app.services.payments.supabase") as mock_sb:
                mock_sb.insert.return_value = None
                resp = client.post(
                    "/api/payments",
                    json=self._valid_body,
                    headers=_auth_headers(),
                )

        assert resp.status_code == 500

    def test_create_payment_without_auth_returns_401(self, client: TestClient):
        """C1 security fix: endpoint now requires auth."""
        resp = client.post("/api/payments", json=self._valid_body)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/payments/redsys-sign
# ---------------------------------------------------------------------------

class TestRedsysSign:
    _valid_body = {
        "amount": 50.00,
        "urlOk": "https://example.com/ok",
        "urlKo": "https://example.com/ko",
    }

    def test_redsys_sign_returns_200(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json=self._valid_body,
                headers=_auth_headers(),
            )
        assert resp.status_code == 200

    def test_redsys_sign_returns_required_fields(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json=self._valid_body,
                headers=_auth_headers(),
            )
        body = resp.json()
        assert "Ds_MerchantParameters" in body
        assert "Ds_Signature" in body
        assert "Ds_SignatureVersion" in body
        assert "redsysUrl" in body
        assert "orderNumber" in body

    def test_redsys_sign_signature_version_is_hmac_sha256(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json=self._valid_body,
                headers=_auth_headers(),
            )
        assert resp.json()["Ds_SignatureVersion"] == "HMAC_SHA256_V1"

    def test_redsys_sign_merchant_params_is_valid_base64(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json=self._valid_body,
                headers=_auth_headers(),
            )
        params_b64 = resp.json()["Ds_MerchantParameters"]
        # Should not raise
        decoded = base64.b64decode(params_b64).decode("utf-8")
        params = json.loads(decoded)
        assert "DS_MERCHANT_AMOUNT" in params
        assert "DS_MERCHANT_ORDER" in params
        assert "DS_MERCHANT_MERCHANTCODE" in params

    def test_redsys_sign_amount_converted_to_cents(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json={"amount": 12.50, "urlOk": "https://ok", "urlKo": "https://ko"},
                headers=_auth_headers(),
            )
        params_b64 = resp.json()["Ds_MerchantParameters"]
        params = json.loads(base64.b64decode(params_b64))
        assert params["DS_MERCHANT_AMOUNT"] == "1250"

    def test_redsys_sign_includes_url_ok_and_ko(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json=self._valid_body,
                headers=_auth_headers(),
            )
        params_b64 = resp.json()["Ds_MerchantParameters"]
        params = json.loads(base64.b64decode(params_b64))
        assert params["DS_MERCHANT_URLOK"] == "https://example.com/ok"
        assert params["DS_MERCHANT_URLKO"] == "https://example.com/ko"

    def test_redsys_sign_order_number_max_12_chars(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json=self._valid_body,
                headers=_auth_headers(),
            )
        order_number = resp.json()["orderNumber"]
        assert len(order_number) <= 12

    def test_redsys_sign_signature_is_non_empty_base64(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json=self._valid_body,
                headers=_auth_headers(),
            )
        sig = resp.json()["Ds_Signature"]
        assert len(sig) > 0
        base64.b64decode(sig)  # Should not raise

    def test_redsys_sign_redsys_url_is_present(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json=self._valid_body,
                headers=_auth_headers(),
            )
        url = resp.json()["redsysUrl"]
        assert "redsys.es" in url

    def test_redsys_sign_missing_amount_returns_422(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json={"urlOk": "https://ok", "urlKo": "https://ko"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 422

    def test_redsys_sign_missing_url_ok_returns_422(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json={"amount": 10.0, "urlKo": "https://ko"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 422

    def test_redsys_sign_missing_url_ko_returns_422(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json={"amount": 10.0, "urlOk": "https://ok"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 422

    def test_redsys_sign_zero_amount_returns_422(self, client: TestClient):
        """amount=0 is rejected by Pydantic Field(gt=0) — returns 422."""
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json={"amount": 0, "urlOk": "https://ok", "urlKo": "https://ko"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 422

    def test_redsys_sign_empty_url_ok_returns_422(self, client: TestClient):
        """Empty urlOk rejected by Pydantic Field(min_length=1) — returns 422."""
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json={"amount": 10.0, "urlOk": "", "urlKo": "https://ko"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 422

    def test_redsys_sign_empty_url_ko_returns_422(self, client: TestClient):
        """Empty urlKo rejected by Pydantic Field(min_length=1) — returns 422."""
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json={"amount": 10.0, "urlOk": "https://ok", "urlKo": ""},
                headers=_auth_headers(),
            )
        assert resp.status_code == 422

    def test_redsys_sign_without_auth_returns_401(self, client: TestClient):
        """C1 security fix: endpoint now requires auth."""
        resp = client.post("/api/payments/redsys-sign", json=self._valid_body)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Pure unit tests for Redsys service functions (no HTTP layer)
# ---------------------------------------------------------------------------

class TestRedsysServiceUnit:
    def test_sign_redsys_returns_result_object(self):
        from app.services.payments import sign_redsys
        result = sign_redsys(50.0, "https://ok", "https://ko")
        assert result.Ds_SignatureVersion == "HMAC_SHA256_V1"
        assert result.Ds_MerchantParameters
        assert result.Ds_Signature
        assert result.orderNumber

    def test_sign_redsys_dict_method_returns_all_keys(self):
        from app.services.payments import sign_redsys
        result = sign_redsys(10.0, "https://ok", "https://ko")
        d = result.dict()
        assert set(d.keys()) == {
            "Ds_MerchantParameters",
            "Ds_Signature",
            "Ds_SignatureVersion",
            "redsysUrl",
            "orderNumber",
        }

    def test_derive_key_returns_bytes(self):
        from app.services.payments import _derive_key
        secret = "sq7HjrUOBfKmC576ILgskD900SqIlHkI8awNPoDg"
        key = _derive_key(secret, "123456789012")
        assert isinstance(key, bytes)
        assert len(key) > 0

    def test_sign_redsys_different_amounts_produce_different_params(self):
        from app.services.payments import sign_redsys
        r1 = sign_redsys(10.0, "https://ok", "https://ko")
        r2 = sign_redsys(20.0, "https://ok", "https://ko")
        p1 = json.loads(base64.b64decode(r1.Ds_MerchantParameters))
        p2 = json.loads(base64.b64decode(r2.Ds_MerchantParameters))
        assert p1["DS_MERCHANT_AMOUNT"] != p2["DS_MERCHANT_AMOUNT"]


# ---------------------------------------------------------------------------
# Pure unit tests for payment service (no HTTP layer)
# ---------------------------------------------------------------------------

class TestCreatePaymentService:
    def test_create_payment_builds_correct_row(self):
        from app.services import payments as svc
        payment_data = make_payment()

        with patch("app.services.payments.supabase") as mock_sb:
            mock_sb.insert.return_value = [payment_data]
            result = svc.create_payment("order-1", 27.50, "card")

        assert result.id == "pay-1"
        assert result.order_id == "order-1"
        assert result.status == "confirmed"

    def test_create_payment_raises_on_empty_insert_result(self):
        from app.services import payments as svc

        with patch("app.services.payments.supabase") as mock_sb:
            mock_sb.insert.return_value = None
            with pytest.raises(RuntimeError, match="failed to create payment"):
                svc.create_payment("order-1", 10.0, "cash")
