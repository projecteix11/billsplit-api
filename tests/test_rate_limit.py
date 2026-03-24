"""
Tests for rate limiting behaviour.

We verify:
- The rate_limit_exceeded_handler returns a 429 with the correct envelope
- The handler includes a Retry-After header
- The limiter is attached to the app
"""

import json
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded


def _make_exc(detail: str = None) -> RateLimitExceeded:
    """Build a RateLimitExceeded using a MagicMock Limit (as slowapi expects)."""
    limit = MagicMock()
    limit.error_message = None
    limit.limit = "10 per 1 minute"
    exc = RateLimitExceeded(limit)
    if detail is not None:
        exc.detail = detail
    return exc


class TestRateLimitExceededHandler:
    def test_handler_returns_429_response(self):
        from app.middleware.rate_limit import rate_limit_exceeded_handler

        exc = _make_exc()
        request = MagicMock()
        response = rate_limit_exceeded_handler(request, exc)
        assert response.status_code == 429

    def test_handler_returns_correct_envelope(self):
        from app.middleware.rate_limit import rate_limit_exceeded_handler

        exc = _make_exc()
        request = MagicMock()
        response = rate_limit_exceeded_handler(request, exc)
        body = json.loads(response.body)
        assert body["data"] is None
        assert "Rate limit exceeded" in body["error"]

    def test_handler_includes_retry_after_header(self):
        from app.middleware.rate_limit import rate_limit_exceeded_handler

        exc = _make_exc()
        request = MagicMock()
        response = rate_limit_exceeded_handler(request, exc)
        assert "Retry-After" in response.headers

    def test_handler_extracts_retry_after_from_detail(self):
        from app.middleware.rate_limit import rate_limit_exceeded_handler

        exc = _make_exc(detail="Rate limit exceeded: 45")
        request = MagicMock()
        response = rate_limit_exceeded_handler(request, exc)
        assert response.headers["Retry-After"] == "45"

    def test_handler_uses_last_word_of_detail_as_retry_after(self):
        from app.middleware.rate_limit import rate_limit_exceeded_handler

        # The handler does: exc.detail.split(" ")[-1]
        exc = _make_exc(detail="some message 30")
        request = MagicMock()
        response = rate_limit_exceeded_handler(request, exc)
        assert response.headers["Retry-After"] == "30"

    def test_handler_uses_60_as_fallback_when_detail_is_none(self):
        from app.middleware.rate_limit import rate_limit_exceeded_handler

        exc = _make_exc()
        exc.detail = None
        request = MagicMock()
        response = rate_limit_exceeded_handler(request, exc)
        assert response.headers["Retry-After"] == "60"


class TestLimiterConfiguration:
    def test_limiter_has_default_limits(self):
        from app.middleware.rate_limit import limiter
        assert limiter._default_limits is not None

    def test_app_has_limiter_in_state(self, app):
        from app.middleware.rate_limit import limiter
        assert app.state.limiter is limiter
