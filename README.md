# BillSplit API (Python)

REST API for the BillSplit restaurant ordering system, built with **FastAPI** and **Python 3.12+**.

This is a Python port of the [Go implementation](https://github.com/projecteix11/billsplit-api/tree/go-code), with identical routes, business logic, and Redsys payment signing.

## Stack

- **FastAPI** — web framework
- **Uvicorn** — ASGI server
- **Requests** — HTTP client for Supabase PostgREST
- **PyCryptodome** — 3DES-CBC for Redsys payment signing
- **Supabase** — database (PostgREST + Auth)

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
api/
├── main.py              # App entry point, CORS, route registration
├── requirements.txt
└── app/
    ├── models.py        # Pydantic data models
    ├── db/
    │   └── supabase.py  # PostgREST HTTP client
    ├── middleware/
    │   └── auth.py      # JWT auth dependency
    ├── services/
    │   ├── dishes.py    # Dish & category logic
    │   ├── orders.py    # Order management & tax calculation
    │   └── payments.py  # Redsys signing & payment creation
    └── routers/
        ├── dishes.py
        ├── orders.py
        ├── order_items.py
        └── payments.py
```

## Response Format

All endpoints return a consistent JSON envelope:

```json
{ "data": ..., "error": null }
{ "data": null, "error": "error message" }
```
