"""Shared HTTP error responses.

Centralises the sanitized 500 so handlers stop returning raw `str(e)` to clients
— a PostgREST/Supabase error string can include SQL, column, constraint and
table names (Master Ecosystem Report C5, info disclosure). The full exception
and traceback are logged server-side instead; the client gets a generic message.
"""
import logging

from fastapi.responses import JSONResponse

_log = logging.getLogger("app.errors")


def internal_error(e: Exception) -> JSONResponse:
    """Generic 500 for the client; full exception + traceback to server logs."""
    _log.exception("Unhandled error in request handler: %s", e)
    return JSONResponse(status_code=500, content={"data": None, "error": "Internal server error"})
