"""Unit tests for the CORS allowed-origin regex (main.cors_origin_regex).

Guards the P3 hardening: private LAN ranges / localhost must only be accepted
when APP_ENV=local, never in production.
"""

import re

from main import cors_origin_regex


def _matches(regex: str, origin: str) -> bool:
    # Starlette's CORSMiddleware fullmatches the Origin against allow_origin_regex.
    return re.fullmatch(regex, origin) is not None


class TestCorsOriginRegex:
    def test_prod_allows_gobbly_subdomains(self):
        regex = cors_origin_regex(is_local=False)
        assert _matches(regex, "https://app.gobbly.app")
        assert _matches(regex, "https://gobbly.app")
        assert _matches(regex, "https://some-tenant.gobbly.app")

    def test_prod_rejects_localhost_and_private_ranges(self):
        regex = cors_origin_regex(is_local=False)
        assert not _matches(regex, "http://localhost:5173")
        assert not _matches(regex, "http://192.168.1.50:5173")
        assert not _matches(regex, "http://10.0.0.4:4173")
        assert not _matches(regex, "http://127.0.0.1:5173")

    def test_prod_rejects_lookalike_domains(self):
        regex = cors_origin_regex(is_local=False)
        assert not _matches(regex, "https://gobbly.app.evil.com")
        assert not _matches(regex, "https://evilgobbly.app")
        assert not _matches(regex, "http://app.gobbly.app")  # http, not https

    def test_local_allows_localhost_and_private_ranges(self):
        regex = cors_origin_regex(is_local=True)
        assert _matches(regex, "http://localhost:5173")
        assert _matches(regex, "http://192.168.1.50:5173")
        assert _matches(regex, "http://10.0.0.4:4173")
        # and still allows prod origins
        assert _matches(regex, "https://app.gobbly.app")
