# BillSplit API (Python)

REST API for the BillSplit restaurant ordering system, built with **FastAPI** and **Python 3.12+**.

This is a Python port of the [Go implementation](https://github.com/projecteix11/billsplit-api/tree/go-code), with identical routes, business logic, and Redsys payment signing.

## Stack

- **FastAPI** — web framework
- **Uvicorn** — ASGI server
- **Requests** — HTTP client for Supabase PostgREST
- **PyCryptodome** — 3DES-CBC for Redsys payment signing
- **Supabase** — database (PostgREST + Auth)
- **pytest** — testing framework

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

REDSYS_SECRET=sq7HjrUOBfKmC576ILgskD900SqIlHkI8awNPoDg
REDSYS_MERCHANT_CODE=999008881
REDSYS_TERMINAL=001

CORS_ORIGINS=http://localhost:5173,http://localhost:5174

PORT=3001
```

### 3. Run

```bash
python main.py
```

Or with hot reload for development:

```bash
uvicorn main:app --port 3001 --reload
```

## Tests

Tests use **pytest** with FastAPI's `TestClient`. Supabase and auth calls are mocked.

```bash
# Run all tests
pytest

# Run a single test file
pytest tests/test_orders.py

# Run a specific test
pytest tests/test_orders.py::test_create_order_success

# Verbose output
pytest -v
```

### Last run (2026-03-18)

| File | Tests | Coverage |
|------|------:|----------|
| `test_health.py` | 4 | Health endpoint |
| `test_dishes.py` | 13 | Dishes & categories |
| `test_orders.py` | 36 | All 6 order endpoints + auth |
| `test_order_items.py` | 28 | Kitchen-status & payment-status |
| `test_payments.py` | 29 | Payments + Redsys crypto |
| `test_services.py` | 29 | Service layer & math helpers |
| `test_auth.py` | 17 | Auth middleware & dependency |
| `test_supabase_client.py` | 20 | DB client (init, CRUD, token) |
| `test_rate_limit.py` | 8 | Rate limiting handler & config |
| **Total** | **201** | **All passing in 0.39s** |

## API Routes

### Public

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/dishes` | List available dishes |
| `GET` | `/api/categories` | List dish categories |
| `POST` | `/api/orders` | Create a new order |
| `GET` | `/api/orders/{orderId}` | Get order by ID |
| `POST` | `/api/orders/{orderId}/items` | Add items to an order |
| `PATCH` | `/api/orders/{orderId}/close` | Close an order |
| `GET` | `/api/tables/{tableId}/open-order` | Get open order for a table |
| `PATCH` | `/api/order-items/payment-status` | Update payment status of items |
| `POST` | `/api/payments` | Record a payment |
| `POST` | `/api/payments/redsys-sign` | Sign a Redsys payment request |

### Protected (requires `Authorization: Bearer <token>`)

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/orders?status=open\|closed` | List all orders (management) |
| `PATCH` | `/api/order-items/{itemId}/kitchen-status` | Update kitchen status |

## Project Structure

```
├── main.py              # App entry point, CORS, middleware
├── requirements.txt
└── app/
    ├── models.py        # Pydantic data models
    ├── db/
    │   └── supabase.py  # PostgREST HTTP client
    ├── middleware/
    │   ├── auth.py      # JWT auth dependency
    │   └── rate_limit.py # Per-IP rate limiting (slowapi)
    ├── services/
    │   ├── dishes.py    # Dish & category logic
    │   ├── orders.py    # Order management & tax calculation
    │   └── payments.py  # Redsys signing & payment creation
    └── routers/
        ├── __init__.py  # register() — centralizes all router inclusion
        ├── dishes.py
        ├── orders.py
        ├── order_items.py
        └── payments.py
```

Router registration is centralized in `app/routers/__init__.py`. To add a new router, create the file in `app/routers/` and add it to the `register()` function — no changes needed in `main.py`.

## Response Format

All endpoints return a consistent JSON envelope:

```json
{ "data": ..., "error": null }
{ "data": null, "error": "error message" }
```
