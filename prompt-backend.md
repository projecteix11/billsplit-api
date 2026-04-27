# Contexto sesión backend — billsplit-api

## Qué hemos hecho en esta sesión

### 1. Eliminado el prefijo `/api` de todas las rutas
El backend está en `api.gobbly.app`, así que tener `/api/dishes` resultaba en `api.gobbly.app/api/dishes` — redundante.
Ahora todas las rutas son `/dishes`, `/categories`, `/orders`, etc.

Archivos afectados: todos los routers en `app/routers/`, `main.py`, `app/middleware/auth.py`, `app/middleware/request_logging.py` y todos los tests.

### 2. `GET /dishes` siempre devuelve todos los platos
Eliminado el query param `?all=true`. El endpoint `/dishes` ahora siempre llama a `get_all_dishes()` (incluye platos no disponibles). El frontend ya no necesita pasar `?all=true`.

### 3. Soporte para header `X-Tenant-Slug`
Añadido en `app/middleware/tenant.py` como paso 3 de la cadena de resolución de tenant:

```
JWT state → Bearer token → X-Tenant-Slug (directo) → Origin/Referer → 404
```

El header `X-Tenant-Slug` se acepta directamente como `tenant_id` sin DB lookup. Esto es **temporal** hasta que exista la tabla intermedia de tenants. Cuando esté lista, este paso debe hacer un SELECT por ID.

### 4. Endpoint de debug (temporal)
Añadido `GET /debug-headers` en `main.py` que devuelve todos los headers recibidos. Útil para diagnosticar si los headers llegan a Vercel. Se puede eliminar cuando ya no sea necesario.

---

## Arquitectura de despliegue actual

| App | Plataforma | URL |
|-----|-----------|-----|
| Backend API | Vercel | `api.gobbly.app` |
| Panel gestión (frontend) | Vercel | `management.gobbly.app` |
| Vista cliente/comensal | Cloudflare Pages | `{tenant}.gobbly.app` |

**Worker Cloudflare `gobbly-tenants`** — actúa de proxy/router para `*.gobbly.app`:
- `/`, `/menu*`, `/booking*` → `tenant-site.pages.dev`
- Todo lo demás → `clients-60p.pages.dev`

---

## Tenant ID de producción

El tenant ID correcto es: `ac87c9d9-0eda-451c-b583-c59e02e2e9e6`

Actualmente hardcodeado en el frontend como valor del header `X-Tenant-Slug`. Esto es **temporal**: mientras no existe la DB admin intermediaria (que centralizará la configuración de todos los clientes: tenantId, módulos activos, suscripciones, etc.), necesitamos un tenant ID fijo para poder probar que el flujo end-to-end funciona correctamente. Cuando esa DB exista, el tenant se resolverá dinámicamente a partir del subdominio o del JWT.

---

## Pendiente

- Cuando exista la tabla intermedia de tenants, el paso 3 de `get_current_tenant` (`app/middleware/tenant.py`) debe hacer un DB lookup por ID en lugar de usar el valor directamente.
- Eliminar el endpoint `/debug-headers` de `main.py` cuando ya no sea necesario.
- El frontend debe extraer el slug del subdominio (`getTenantSlug()`) en lugar de usar el UUID hardcodeado.

---

## Tests

302 tests pasan. Ejecutar con:
```bash
source venv/bin/activate && python -m pytest tests/ -v
```
