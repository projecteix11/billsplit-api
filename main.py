import os
from dotenv import load_dotenv

load_dotenv(".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.db import supabase
from app.logging import client as logging_client

from app.middleware.auth import AuthError, auth_error_handler
from app.middleware.rate_limit import limiter, rate_limit_exceeded_handler
from app import routers

supabase.init()
logging_client.init()

from app.middleware.request_logging import RequestLoggingMiddleware

app = FastAPI()

# Request logging (canonical log lines)
app.add_middleware(RequestLoggingMiddleware)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_exception_handler(AuthError, auth_error_handler)

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
    allow_headers=["Content-Type", "Authorization", "X-Request-Id", "X-Client-Type", "X-Correlation-Id", "X-Tenant-Slug"],
    expose_headers=["X-Request-Id"],
)

# Routers
routers.register(app)


@app.get("/health")
@limiter.exempt
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "3001"))
    print(f"BillSplit API (Python) running on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
