# Security Review — Observaciones residuales

Revisión completada el 2026-03-18. Los 11 fixes críticos/altos/medios están implementados y verificados.

## Observaciones pendientes

| # | Severidad | Archivo | Descripción | Decisión |
|---|-----------|---------|-------------|----------|
| R1 | Bajo | `app/routers/orders.py` | `GET /api/orders/{order_id}` y `GET /api/tables/{table_id}/open-order` son públicos — cualquiera con el UUID puede leer la orden | ¿Intencional para el flujo QR de mesa sin login? |
| R2 | Bajo | `app/routers/orders.py` | `POST /api/orders` sin auth — cualquiera puede crear órdenes | ¿Los clientes crean su propia orden desde la mesa sin login? |
| R3 | Bajo | `app/routers/payments.py` | `POST /api/payments/redsys-sign` devuelve `.dict()` directamente, sin el envelope estándar `{"data": ..., "error": null}` | Inconsistencia con el resto de la API — puede confundir al frontend |
| R4 | Info | `app/middleware/rate_limit.py` | `X-Forwarded-For` confiado sin validar proxy — si el proxy upstream no limpia cabeceras, un cliente puede falsificar su IP y eludir el rate limit | Documentar en ops que requiere Nginx/Caddy configurado correctamente |
| R5 | Info | `app/models.py` | `NewOrderItem.diner_name` es `Optional` sin `min_length` — admite string vacío `""` | Impacto mínimo; añadir `min_length=1` si se quiere evitar registros con nombre vacío |

---

## Detalle de cada observación

### R1 — Endpoints de lectura de órdenes sin autenticación

Los endpoints `GET /api/orders/{order_id}` y `GET /api/tables/{table_id}/open-order` no requieren token. Cualquier persona que conozca o adivine el UUID de una orden puede ver su contenido completo: mesa, platos pedidos, precios, nombres de comensales y estado de pago.

En un sistema de restaurante con QR por mesa, esto puede ser **totalmente intencionado**: el cliente escanea el QR, obtiene el `order_id` y consulta su propia orden sin necesidad de registrarse. Si ese es el flujo, está bien. Si en cambio solo el personal del restaurante debería poder leer órdenes, habría que añadir `Depends(require_auth)`.

**Pregunta clave:** ¿el cliente de la mesa puede ver su propia orden sin estar autenticado?

---

### R2 — Creación de órdenes sin autenticación

`POST /api/orders` tampoco requiere token. Cualquiera puede crear órdenes asociadas a cualquier `tableId`, tantas veces como quiera (limitado solo por el rate limit de 20/min por IP).

Al igual que R1, puede ser intencional si el flujo es "cliente en mesa escanea QR → crea su propia orden". El riesgo es que sin auth, es difícil atribuir quién creó qué, y un bot podría llenar la base de datos de órdenes basura. Como mínimo se recomienda bajar el rate limit de este endpoint a 5/min y validar que el `tableId` existe antes de insertar.

---

### R3 — `redsys-sign` no usa el envelope estándar

Todos los endpoints de la API devuelven las respuestas con este formato:
```json
{ "data": ..., "error": null }
```

El endpoint `POST /api/payments/redsys-sign` es la excepción: devuelve directamente el objeto de firma Redsys sin envoltura:
```json
{ "Ds_MerchantParameters": "...", "Ds_Signature": "...", ... }
```

Esto no es un riesgo de seguridad en sí, pero puede romper el código del frontend si espera siempre el envelope y extrae `response.data`. Convendría unificarlo para evitar bugs silenciosos.

---

### R4 — Rate limiting con `X-Forwarded-For` requiere proxy de confianza

El rate limiting limita peticiones por IP: máximo 10/min globalmente, 20/min en mutaciones. Para identificar la IP del cliente, el código lee la cabecera `X-Forwarded-For` del request.

El problema: **cualquier cliente puede enviar esa cabecera con el valor que quiera**. Si el servidor recibe directamente el request de internet (sin proxy delante), un atacante puede poner `X-Forwarded-For: 1.2.3.4` diferente en cada petición y el rate limiter nunca lo frena, porque cada vez ve una IP distinta.

La solución es que la API solo corra detrás de un proxy inverso (Nginx, Caddy, un load balancer de nube) que esté configurado para **eliminar el `X-Forwarded-For` que viene del cliente** y añadir el suyo propio con la IP real. Así el valor de esa cabecera siempre es fiable. Si el despliegue no tiene proxy, hay que volver a usar `request.client.host` directamente.

---

### R5 — `diner_name` admite string vacío

El campo `diner_name` en `NewOrderItem` es opcional (`None` por defecto) pero si se envía, acepta cualquier string incluyendo `""`. Esto significa que en la base de datos puede haber items con nombre de comensal vacío, lo que puede generar confusión en el frontend o en los informes de cocina.

El fix es trivial: añadir `min_length=1` al `Field` de `diner_name` en `app/models.py`. Así, si se envía el campo, debe tener al menos un carácter; si no se quiere especificar, se omite o se envía `null`.
