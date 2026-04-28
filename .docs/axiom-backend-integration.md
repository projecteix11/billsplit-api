# Axiom — Backend Integration Guide (billsplit-api)

## Context

The management frontend already sends logs to Axiom (dataset: `gobbly-management`).
The backend (`billsplit-api`, FastAPI/Python) currently sends logs to a custom api-logging service that has been deprecated. This guide covers migrating the backend to send logs directly to Axiom.

## Axiom Account

- **Dashboard**: https://app.axiom.co
- **Login**: `infra@gobbly.app` (code sent to `gobbly.app@gmail.com`)
- **Organization**: Gobbly

## Step 1 — Create a Backend API Token

1. Go to **Settings > API Tokens** in Axiom dashboard
2. Click **New API Token**
3. Name: `gobbly-api-ingest`
4. Permissions: **Ingest** only on `gobbly-management` dataset
5. Copy the token

> Use the same dataset (`gobbly-management`) so frontend + backend logs are unified and queryable together. The `source` field distinguishes them (`management` vs `api`).

## Step 2 — Install axiom-py

```bash
pip install axiom-py
```

Add to `requirements.txt`:
```
axiom-py==1.0.0
```

## Step 3 — Migrate logging client

Replace `app/logging/client.py` with:

```python
"""Fire-and-forget logging client using Axiom.

Sends events directly to Axiom in a daemon thread so the main request
is never blocked or failed by logging issues.
"""

import os
import threading
from datetime import datetime, timezone

import axiom_py

_client = None
_dataset = ""


def init() -> None:
    global _client, _dataset
    token = os.getenv("AXIOM_TOKEN", "")
    _dataset = os.getenv("AXIOM_DATASET", "gobbly-management")
    if token:
        _client = axiom_py.Client(token=token)


def _send(event: dict) -> None:
    if not _client:
        return
    try:
        # Ensure timestamp is present
        if "_time" not in event and "timestamp" not in event:
            event["_time"] = datetime.now(timezone.utc).isoformat()
        _client.ingest_events(dataset=_dataset, events=[event])
    except Exception:
        pass  # logging must never break the application


def log_event(event: dict) -> None:
    """Queue an event to be sent in a background daemon thread."""
    threading.Thread(target=_send, args=(event,), daemon=True).start()
```

## Step 4 — Update environment variables

### Remove (old)
```
LOGGING_API_URL=...
LOGGING_API_KEY=...
```

### Add (new)
```
AXIOM_TOKEN=xaat-...       # The ingest-only token from Step 1
AXIOM_DATASET=gobbly-management
```

Set these in:
- `.env` (local dev)
- Vercel environment variables (production)

## Step 5 — Update LogFactory / event enrichment

Make sure all events include a `source` field set to `"api"` to distinguish from frontend logs:

```python
# In app/logging/factory.py or wherever events are built:
event = {
    "type": "api_request",       # or api_error, system_event, etc.
    "level": "info",
    "source": "api",             # <-- distinguishes from frontend ("management")
    "module": "orders",
    "action": "GET /api/orders",
    "status_code": 200,
    "duration_ms": 45,
    "user_id": request.user.id,
    "metadata": { ... },
}
log_event(event)
```

## Step 6 — Recommended backend events

| Event | Type | Module | When |
|-------|------|--------|------|
| API request | `api_request` | `{router}` | Every request (via middleware) |
| API error | `api_error` | `{router}` | 4xx/5xx responses |
| Auth failure | `auth_event` | `auth` | Invalid/expired tokens |
| DB error | `system_event` | `database` | Supabase query failures |
| Rate limit hit | `system_event` | `rate_limit` | SlowAPI limit exceeded |
| App startup | `system_event` | `app` | Server boot |

### Request logging middleware (recommended)

```python
# app/middleware/logging.py
import time
from starlette.middleware.base import BaseHTTPMiddleware
from app.logging import log_event

class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.time()
        response = await call_next(request)
        duration_ms = round((time.time() - start) * 1000)

        log_event({
            "type": "api_request" if response.status_code < 400 else "api_error",
            "level": "error" if response.status_code >= 500 else "warning" if response.status_code >= 400 else "info",
            "source": "api",
            "module": "http",
            "action": f"{request.method} {request.url.path}",
            "http_method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "metadata": {
                "query": str(request.query_params) if request.query_params else None,
            },
        })

        return response
```

Add to `main.py`:
```python
from app.middleware.logging import LoggingMiddleware
app.add_middleware(LoggingMiddleware)
```

## Event Schema (shared with frontend)

Use the same field names as the frontend for unified querying:

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | `api_request`, `api_error`, `auth_event`, `system_event` |
| `level` | string | `info`, `warning`, `error`, `fatal` |
| `source` | string | `api` (backend) or `management` (frontend) |
| `module` | string | Feature area |
| `action` | string | What happened |
| `http_method` | string | GET, POST, etc. |
| `path` | string | Request path |
| `status_code` | number | HTTP response status |
| `duration_ms` | number | Request duration |
| `user_id` | string | Authenticated user ID |
| `metadata` | object | Additional context |
| `request_id` | string | UUID v4 — identifica una única llamada HTTP (1 fetch = 1 request_id) |
| `correlation_id` | string | UUID v4 — agrupa todas las llamadas HTTP de una misma acción de usuario |

## Distributed Tracing — Frontend ↔ Backend

El frontend ya envía headers de trazabilidad en cada llamada HTTP. Esta sección explica cómo el backend debe leerlos para que Axiom muestre trazas completas frontend + backend.

### Convención de `source`

Cada evento en Axiom lleva un campo `source` que identifica quién lo generó y si el cliente es humano o bot:

| Servicio | source | Cuándo |
|----------|--------|--------|
| Frontend (humano) | 💻 management | Navegador por defecto |
| Frontend (bot/LLM) | 🤖 management | Bot detectado vía User-Agent |
| Backend (humano) | 🐍 api | Por defecto |
| Backend (bot) | 🤖 api | Bot detectado vía User-Agent o header `X-Client-Type` |

### Headers que envía el frontend

Cada llamada HTTP desde el frontend incluye estos headers automáticamente:

| Header | Valor | Propósito |
|--------|-------|-----------|
| `X-Request-Id` | UUID v4 (único por llamada HTTP) | Traza individual: 1 fetch = 1 request_id |
| `X-Correlation-Id` | UUID v4 (compartido entre llamadas relacionadas) | Traza de operación: 1 acción de usuario = N fetches con mismo correlation_id |
| `X-Client-Type` | `bot` o `human` | Para que el backend ajuste su source (🤖 vs 🐍) |

### Qué debe hacer el backend

1. **Leer `X-Request-Id`** de la request entrante y usarlo como `request_id` en el evento de Axiom. No generar uno nuevo — el frontend ya lo creó.
2. **Leer `X-Correlation-Id`** de la request entrante e incluirlo como `correlation_id` en el evento de Axiom.
3. **Opcionalmente leer `X-Client-Type`** para decidir entre `🐍 api` y `🤖 api` como source.
4. **Opcionalmente devolver `X-Request-Id`** en el header de respuesta — útil para depuración en DevTools del navegador.

### Flujo de trazabilidad — ejemplo real

Acción "Enviar a Cocina" que genera 3 llamadas API:

```
El usuario hace clic en "Enviar a Cocina"
│
│  correlation_id = "cor-111"  (se genera una vez para toda la acción)
│
├─► GET /api/tables/{id}/open-order
│     X-Request-Id: "req-aaa"
│     X-Correlation-Id: "cor-111"
│     ├─ 💻 management: action=get_open_order, correlation_id=cor-111
│     └─ 🐍 api: action=GET /api/tables/.../open-order -> 200, request_id=req-aaa, correlation_id=cor-111
│
├─► POST /api/orders
│     X-Request-Id: "req-bbb"
│     X-Correlation-Id: "cor-111"
│     ├─ 💻 management: action=order_created, correlation_id=cor-111
│     └─ 🐍 api: action=POST /api/orders -> 201, request_id=req-bbb, correlation_id=cor-111
│
└─► PATCH /api/tables/{id}
      X-Request-Id: "req-ccc"
      X-Correlation-Id: "cor-111"
      ├─ 💻 management: action=table_status_changed, correlation_id=cor-111
      └─ 🐍 api: action=PATCH /api/tables/... -> 200, request_id=req-ccc, correlation_id=cor-111
```

En Axiom: `correlation_id == "cor-111"` muestra los **6 eventos** (3 front + 3 back) en orden cronológico.

### Consultas de trazabilidad en Axiom

- **Traza completa de una acción de usuario** — filtrar por `correlation_id`
- **Detalle de una llamada HTTP individual** — filtrar por `request_id`
- **Todo el tráfico de bots** — filtrar por `source` que contenga 🤖

## Querying both frontend + backend

```apl
// All errors from any source
['gobbly-management']
| where level == "error"
| order by _time desc

// Backend slow requests (> 1s)
['gobbly-management']
| where source == "api" and duration_ms > 1000
| project _time, action, duration_ms, status_code

// Full user journey (frontend + backend)
['gobbly-management']
| where user_id == "some-user-id"
| order by _time asc

// Error rate by source
['gobbly-management']
| where level in ("error", "warning")
| summarize count() by source, bin(_time, 1h)
```

## Free Tier Reminder

- 500 GB/month ingest, 25 GB storage, 30 days retention
- Shared between frontend and backend — more than enough for Gobbly's scale
