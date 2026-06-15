import os
from dotenv import load_dotenv

load_dotenv(".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.db import supabase
from app.logging import client as logging_client

from app.middleware.auth import AuthError, auth_error_handler
from app.middleware.rate_limit import limiter, rate_limit_exceeded_handler
from app.http_errors import internal_error
from app import routers

supabase.init()
logging_client.init()

from app.middleware.request_logging import RequestLoggingMiddleware

_tags_metadata = [
    {"name": "auth",          "description": "Perfil del usuario autenticado y datos de su tenant."},
    {"name": "orders",        "description": "Gestión de órdenes de mesa e ítems individuales."},
    {"name": "menu",          "description": "Platos, categorías, alérgenos e ingredientes del menú."},
    {"name": "daily menus",   "description": "Menús del día con secciones e ítems configurables."},
    {"name": "payments",      "description": "Pagos y firma Redsys para TPV virtual."},
    {"name": "reservations",  "description": "Reservas de mesa con estado y notas."},
    {"name": "staff",         "description": "Alta y baja de usuarios de staff del tenant."},
    {"name": "tenants",       "description": "Información pública y resolución de tenants por slug."},
    {"name": "chat",          "description": "Asistente LLM con acceso a mesa, menú y órdenes."},
    {"name": "ai",            "description": "Generación de descripciones de platos con IA."},
    {"name": "notifications", "description": "Broadcast de notificaciones en tiempo real vía Supabase Realtime."},
]

app = FastAPI(openapi_tags=_tags_metadata)

# Request logging (canonical log lines)
app.add_middleware(RequestLoggingMiddleware)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_exception_handler(AuthError, auth_error_handler)


async def _unhandled_exception_handler(_request, exc):
    # Catch-all (C5): any exception not handled by an endpoint's try/except
    # returns a sanitized 500 instead of a raw error string / stack trace.
    return internal_error(exc)


app.add_exception_handler(Exception, _unhandled_exception_handler)

app.add_middleware(SlowAPIMiddleware)

# CORS
cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:4173,http://localhost:5173,http://localhost:5174").split(",")
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"https://([a-z0-9-]+\.)?gobbly\.app",
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-Id", "X-Client-Type", "X-Correlation-Id", "X-Tenant-Slug", "X-Api-Key", "X-Tenant-Id", "X-Guest-Token"],
    expose_headers=["X-Request-Id"],
)

# Routers
routers.register(app)


@app.get("/health")
@limiter.exempt
def health():
    # Cheap liveness: the process is up and serving.
    return {"status": "ok"}


@app.get("/ready")
@limiter.exempt
def ready():
    """Readiness probe (XM-7): confirms the API can actually reach the database
    with a minimal round-trip. Returns 503 on failure so external monitors get a
    truthful signal, unlike the always-ok liveness /health above."""
    try:
        supabase.get_client().table("tenants").select("id").limit(1).execute()
        return {"status": "ready"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "3001"))
    print(f"BillSplit API (Python) running on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
