# Changelog

## 2026-03-18

### Bug fixes

- **Auth response consistency**: `require_auth` now returns the same JSON envelope `{"data": null, "error": "..."}` as the rest of the API. Previously it raised `HTTPException`, which FastAPI wrapped as `{"detail": "..."}`, breaking the contract. A custom `AuthError` exception and handler (`auth_error_handler`) were added in `app/middleware/auth.py` and registered in `main.py`.

- **Float rounding precision**: `_round2()` in `app/services/orders.py` now uses `Decimal` with `ROUND_HALF_UP` instead of `math.floor(v * 100 + 0.5) / 100`. The old implementation had a floating-point bug where `_round2(1.005)` returned `1.0` instead of `1.01`, which could cause incorrect tax calculations.

- **Python 3.9 compatibility**: Replaced `requests.Session | None` type hint in `app/db/supabase.py` with `Optional[requests.Session]`, fixing a `TypeError` on Python < 3.10.

### Refactors

- **Centralized router registration**: Routers are now registered via `app/routers/__init__.py` through a `register(app)` function. Adding new routers no longer requires changes to `main.py`.

### New

- **Test suite**: Added 201 tests using pytest + FastAPI TestClient across 9 test files covering all endpoints, services, auth, rate limiting, and the Supabase client. Run with `pytest` or `pytest -v`.

- **CLAUDE.md**: Added project guidance file for Claude Code with build commands, architecture overview, and key patterns.
