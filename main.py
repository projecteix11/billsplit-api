import os
from dotenv import load_dotenv

load_dotenv(".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.db import supabase
from app.middleware.rate_limit import limiter, rate_limit_exceeded_handler
from app.routers import daily_menus, dishes, orders, order_items, payments

supabase.init()

app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS
cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174").split(",")
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Routers
app.include_router(daily_menus.router)
app.include_router(dishes.router)
app.include_router(orders.router)
app.include_router(order_items.router)
app.include_router(payments.router)


@app.get("/api/health")
@limiter.exempt
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "3001"))
    print(f"BillSplit API (Python) running on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
