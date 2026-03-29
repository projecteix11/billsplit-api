import os
from dotenv import load_dotenv

load_dotenv(".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import supabase
from app.logging import client as logging_client
from app.routers import dishes, orders, order_items, payments

supabase.init()
logging_client.init()

from app.middleware.request_logging import RequestLoggingMiddleware

app = FastAPI()

# Request logging (canonical log lines)
app.add_middleware(RequestLoggingMiddleware)

# CORS
cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174").split(",")
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Routers
app.include_router(dishes.router)
app.include_router(orders.router)
app.include_router(order_items.router)
app.include_router(payments.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "3001"))
    print(f"BillSplit API (Python) running on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
