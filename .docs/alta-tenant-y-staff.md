# Alta de nuevo tenant y staff

## 1. Nuevo tenant (cliente/restaurante)

### 1.1 Crear el tenant en la DB

Ejecutar en Supabase (dashboard o SQL):

```sql
INSERT INTO public.tenants (name, slug, plan, is_active, features, trial_ends_at)
VALUES (
  'Nombre del Restaurante',
  'nombre-slug',          -- debe ser único, se usa en el header X-Tenant-Slug
  'basic',                -- basic | professional | premium
  true,
  '{"reservations": true, "kitchen": true, "payments": true, "daily_menus": false}',
  now() + interval '30 days'  -- período de trial, null si no aplica
);
```

Anotar el `id` generado — se necesita para los pasos siguientes.

### 1.2 Verificar que se crearon automáticamente

El trigger `on_new_tenant` / `on_tenant_created` crea automáticamente:
- Una fila en `tenant_settings` con valores por defecto
- Los roles base (`seed_builtin_roles`)

Verificar:
```sql
SELECT * FROM public.tenant_settings WHERE tenant_id = '<tenant_id>';
SELECT * FROM public.roles WHERE tenant_id = '<tenant_id>';
```

### 1.3 Configurar features

Los módulos disponibles están en `platform_modules`. Activar o desactivar editando `tenants.features`:

```sql
UPDATE public.tenants
SET features = '{"reservations": true, "kitchen": true, "payments": false, "daily_menus": true}'
WHERE slug = 'nombre-slug';
```

El frontend oculta automáticamente del nav los módulos con `false`. La API devuelve 403 si se intenta acceder a un endpoint de un módulo desactivado.

---

## 2. Primer usuario admin del tenant

El primer usuario **no puede crearse via `POST /staff`** porque ese endpoint requiere autenticación. Hay que crearlo directamente en Supabase Auth.

### 2.1 Crear el usuario en Supabase Auth

**Opción A — Supabase Dashboard:**
1. Ir a Authentication → Users → Add user
2. Rellenar email y password
3. En "User metadata" añadir:
```json
{
  "first_name": "Nombre",
  "last_name": "Apellido",
  "full_name": "Nombre Apellido",
  "role": "admin",
  "tenant_id": "<tenant_id>"
}
```

**Opción B — SQL via service role:**
```sql
-- Solo ejecutar con service_role (no con anon key)
SELECT auth.create_user(
  '{"email": "admin@restaurante.com", "password": "password_seguro", "email_confirm": true,
    "user_metadata": {"first_name": "Nombre", "last_name": "Apellido", "full_name": "Nombre Apellido", "role": "admin", "tenant_id": "<tenant_id>"}}'::jsonb
);
```

### 2.2 Verificar triggers automáticos

Al crear el usuario en `auth.users`, el trigger `on_auth_user_created` crea automáticamente la fila en `public.users`. Verificar:

```sql
SELECT * FROM public.users WHERE id = '<user_id>';
```

### 2.3 Asignar rol en user_roles

```sql
INSERT INTO public.user_roles (user_id, tenant_id, role)
VALUES ('<user_id>', '<tenant_id>', 'admin');
```

El trigger `trg_sync_user_role` sincroniza el rol al `user_metadata` del JWT automáticamente.

### 2.4 Verificar con GET /me

Hacer login y llamar `GET /me` con el Bearer token:

```bash
curl -H "Authorization: Bearer <token>" http://localhost:3001/me
```

Respuesta esperada:
```json
{
  "data": {
    "user_id": "...",
    "tenant": {
      "id": "...",
      "slug": "nombre-slug",
      "plan": "basic",
      "features": { "reservations": true, "kitchen": true },
      "is_active": true,
      "trial_ends_at": "2026-05-28T..."
    },
    "role": "admin"
  }
}
```

---

## 3. Staff adicional (cualquier rol)

Una vez el primer admin está creado y autenticado, los usuarios siguientes se crean via API:

### 3.1 POST /staff

```bash
curl -X POST http://localhost:3001/staff \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "camarero@restaurante.com",
    "password": "password_seguro",
    "firstName": "Juan",
    "lastName": "García",
    "role": "waiter",
    "tenantId": "<tenant_id>"
  }'
```

Roles disponibles: `developer` | `admin` | `waiter` | `kitchen`

Este endpoint:
1. Crea el usuario en Supabase Auth con el metadata correcto
2. Inserta en `user_roles` con el rol indicado
3. El trigger crea `public.users` y sincroniza el rol al JWT

### 3.2 Eliminar staff

```bash
curl -X DELETE http://localhost:3001/staff/<user_id> \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{ "tenantId": "<tenant_id>" }'
```

---

## Resumen del flujo

```
1. INSERT tenants (SQL)
      ↓ trigger automático
   tenant_settings + roles base

2. Crear primer admin (Supabase dashboard)
      ↓ trigger automático
   public.users

3. INSERT user_roles (SQL)
      ↓ trigger automático
   JWT metadata actualizado

4. Login → GET /me → confirmar tenant + role

5. Crear staff adicional via POST /staff (autenticado)
```
