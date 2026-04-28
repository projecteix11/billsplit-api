-- Migrations aplicadas en Supabase
-- Aplicar en orden cronológico
-- Source of truth: management/supabase/migrations/

-- =============================================================================
-- 2026-04-28: columnas de plataforma en tenants
-- =============================================================================
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS trial_ends_at timestamptz;
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS features jsonb NOT NULL DEFAULT '{}';
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS branding jsonb NOT NULL DEFAULT '{}';

-- =============================================================================
-- 2026-04-28: catálogo de módulos de plataforma
-- =============================================================================
CREATE TABLE IF NOT EXISTS public.platform_modules (
    key           text PRIMARY KEY,
    name          text NOT NULL,
    description   text,
    is_active     boolean NOT NULL DEFAULT true,
    sort_order    integer NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public.platform_modules (key, name, description, sort_order) VALUES
    ('reservations', 'Reservas',      'Gestión de reservas de mesas',              1),
    ('kitchen',      'Cocina',        'Panel de cocina y gestión de estados de platos', 2),
    ('payments',     'Pagos',         'Procesamiento de pagos y métodos de pago',  3),
    ('daily_menus',  'Menús del día', 'Creación y gestión de menús diarios',       4),
    ('campaigns',    'Campañas',      'Descuentos y campañas promocionales',       5),
    ('qr_codes',     'Códigos QR',    'Generación de QR por mesa',                 6)
ON CONFLICT (key) DO NOTHING;

ALTER TABLE public.platform_modules ENABLE ROW LEVEL SECURITY;

CREATE POLICY "platform_modules_select"
    ON public.platform_modules FOR SELECT TO authenticated
    USING (true);

-- =============================================================================
-- 2026-04-28: panel de gestión — platform_admin, módulos, planes, restaurantes
-- (management/supabase/migrations/20260428100000 + 20260428100001)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Función helper: is_platform_admin()
-- -----------------------------------------------------------------------------
-- SECURITY INVOKER: corre como el usuario llamante → auth.uid() resuelve
-- correctamente desde el JWT de PostgREST (lee request.jwt.claim.sub).
-- SECURITY DEFINER rompía esto al cambiar el contexto de ejecución a postgres.
CREATE OR REPLACE FUNCTION public.is_platform_admin()
RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = public, auth, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.platform_admins WHERE user_id = auth.uid()
    );
$$;

-- -----------------------------------------------------------------------------
-- platform_admins
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.platform_admins (
    user_id    uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.platform_admins ENABLE ROW LEVEL SECURITY;

CREATE POLICY "platform_admins_select"
    ON public.platform_admins FOR SELECT TO authenticated
    USING (user_id = auth.uid());

CREATE POLICY "platform_admins_insert"
    ON public.platform_admins FOR INSERT TO service_role
    WITH CHECK (true);

CREATE POLICY "platform_admins_update"
    ON public.platform_admins FOR UPDATE TO service_role
    USING (true) WITH CHECK (true);

CREATE POLICY "platform_admins_delete"
    ON public.platform_admins FOR DELETE TO service_role
    USING (true);

-- -----------------------------------------------------------------------------
-- Ampliar platform_modules con columnas de UI
-- -----------------------------------------------------------------------------
ALTER TABLE public.platform_modules
    ADD COLUMN IF NOT EXISTS icon             text NOT NULL DEFAULT '🧩',
    ADD COLUMN IF NOT EXISTS color            text NOT NULL DEFAULT '#22c55e',
    ADD COLUMN IF NOT EXISTS category         text NOT NULL DEFAULT 'operations',
    ADD COLUMN IF NOT EXISTS is_core          boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS monthly_price    numeric(10,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS module_features  jsonb NOT NULL DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS dependencies     jsonb NOT NULL DEFAULT '[]';

UPDATE public.platform_modules SET icon = '📅', color = '#6366f1', category = 'operations', is_core = false WHERE key = 'reservations';
UPDATE public.platform_modules SET icon = '🍳', color = '#f59e0b', category = 'operations', is_core = false WHERE key = 'kitchen';
UPDATE public.platform_modules SET icon = '💳', color = '#10b981', category = 'operations', is_core = true  WHERE key = 'payments';
UPDATE public.platform_modules SET icon = '🍽️', color = '#3b82f6', category = 'operations', is_core = false WHERE key = 'daily_menus';
UPDATE public.platform_modules SET icon = '🎯', color = '#ec4899', category = 'customer',   is_core = false WHERE key = 'campaigns';
UPDATE public.platform_modules SET icon = '📱', color = '#8b5cf6', category = 'operations', is_core = true  WHERE key = 'qr_codes';

-- Políticas en platform_modules: solo platform_admin puede leer y escribir
-- (la policy _select anterior que permitía a todos los autenticados se reemplaza)
CREATE POLICY "platform_modules_select"
    ON public.platform_modules FOR SELECT TO authenticated
    USING (public.is_platform_admin());

CREATE POLICY "platform_modules_insert"
    ON public.platform_modules FOR INSERT TO authenticated
    WITH CHECK (public.is_platform_admin());

CREATE POLICY "platform_modules_update"
    ON public.platform_modules FOR UPDATE TO authenticated
    USING (public.is_platform_admin()) WITH CHECK (public.is_platform_admin());

CREATE POLICY "platform_modules_delete"
    ON public.platform_modules FOR DELETE TO authenticated
    USING (public.is_platform_admin());

-- VIEW modules: expone platform_modules con id en lugar de key.
-- security_barrier evita que el optimizador eluda el RLS de la tabla base.
-- security_invoker = true hace que la vista se ejecute como el usuario llamante
-- (no como el owner postgres), necesario para que el RLS se aplique.
CREATE OR REPLACE VIEW public.modules
    WITH (security_barrier = true, security_invoker = true) AS
SELECT
    key             AS id,
    name,
    description,
    icon,
    color,
    category,
    is_core,
    monthly_price,
    module_features AS features,
    dependencies,
    sort_order,
    is_active,
    created_at
FROM public.platform_modules
WHERE is_active = true;

-- -----------------------------------------------------------------------------
-- plans
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.plans (
    id               text PRIMARY KEY,
    name             text NOT NULL,
    description      text,
    monthly_price    numeric(10,2) NOT NULL DEFAULT 0,
    annual_price     numeric(10,2),
    included_modules jsonb NOT NULL DEFAULT '[]',
    max_users        integer NOT NULL DEFAULT 5,
    max_tables       integer NOT NULL DEFAULT 20,
    features         jsonb NOT NULL DEFAULT '[]',
    is_popular       boolean NOT NULL DEFAULT false,
    created_at       timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public.plans (id, name, description, monthly_price, annual_price, included_modules, max_users, max_tables, features, is_popular) VALUES
    ('basic',
     'Básico', 'Para restaurantes que empiezan',
     49, 490, '["payments","qr_codes"]', 5, 20,
     '["Soporte por email","Acceso web"]', false),
    ('professional',
     'Profesional', 'Para restaurantes en crecimiento',
     99, 990, '["payments","qr_codes","kitchen","daily_menus"]', 15, 50,
     '["Soporte prioritario","Acceso web y móvil","Estadísticas"]', true),
    ('premium',
     'Premium', 'Para cadenas y restaurantes avanzados',
     199, 1990, '["payments","qr_codes","kitchen","daily_menus","reservations","campaigns"]', 50, 200,
     '["Soporte 24/7","Multi-sede","API acceso","Estadísticas avanzadas"]', false)
ON CONFLICT (id) DO NOTHING;

ALTER TABLE public.plans ENABLE ROW LEVEL SECURITY;

CREATE POLICY "plans_select"
    ON public.plans FOR SELECT TO authenticated USING (true);

CREATE POLICY "plans_insert"
    ON public.plans FOR INSERT TO authenticated
    WITH CHECK (public.is_platform_admin());

CREATE POLICY "plans_update"
    ON public.plans FOR UPDATE TO authenticated
    USING (public.is_platform_admin()) WITH CHECK (public.is_platform_admin());

CREATE POLICY "plans_delete"
    ON public.plans FOR DELETE TO authenticated
    USING (public.is_platform_admin());

-- -----------------------------------------------------------------------------
-- Ampliar tenants con columnas de gestión de clientes
-- -----------------------------------------------------------------------------
ALTER TABLE public.tenants
    ADD COLUMN IF NOT EXISTS email     text,
    ADD COLUMN IF NOT EXISTS subdomain text,
    ADD COLUMN IF NOT EXISTS logo_url  text,
    ADD COLUMN IF NOT EXISTS phone     text,
    ADD COLUMN IF NOT EXISTS address   text,
    ADD COLUMN IF NOT EXISTS city      text,
    ADD COLUMN IF NOT EXISTS status    text NOT NULL DEFAULT 'trial'
        CHECK (status IN ('active','trial','suspended','cancelled')),
    ADD COLUMN IF NOT EXISTS max_users integer NOT NULL DEFAULT 5,
    ADD COLUMN IF NOT EXISTS mrr       numeric(10,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS plan_id   text REFERENCES public.plans(id);

UPDATE public.tenants SET plan_id = plan::text WHERE plan_id IS NULL;

-- Políticas de platform_admin sobre tenants
CREATE POLICY "tenants_platform_admin_select"
    ON public.tenants FOR SELECT TO authenticated
    USING (public.is_platform_admin());

CREATE POLICY "tenants_platform_admin_insert"
    ON public.tenants FOR INSERT TO authenticated
    WITH CHECK (public.is_platform_admin());

CREATE POLICY "tenants_platform_admin_update"
    ON public.tenants FOR UPDATE TO authenticated
    USING (public.is_platform_admin()) WITH CHECK (public.is_platform_admin());

CREATE POLICY "tenants_platform_admin_delete"
    ON public.tenants FOR DELETE TO authenticated
    USING (public.is_platform_admin());

-- VIEW restaurants: proyección de tenants para el panel de gestión
-- security_invoker = true para que el RLS de tenants se aplique al usuario llamante
CREATE OR REPLACE VIEW public.restaurants
    WITH (security_invoker = true) AS
SELECT
    id, name, slug, subdomain, logo_url, email, phone, address, city,
    country, timezone, currency, plan_id, status, trial_ends_at,
    max_users, mrr, created_at, updated_at
FROM public.tenants;

-- -----------------------------------------------------------------------------
-- restaurant_modules
-- Trigger: sincroniza tenants.features cuando cambian los módulos asignados
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.restaurant_modules (
    restaurant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    module_id     text NOT NULL REFERENCES public.platform_modules(key) ON DELETE CASCADE,
    PRIMARY KEY (restaurant_id, module_id)
);

ALTER TABLE public.restaurant_modules ENABLE ROW LEVEL SECURITY;

CREATE POLICY "restaurant_modules_select"
    ON public.restaurant_modules FOR SELECT TO authenticated
    USING (public.is_platform_admin());

CREATE POLICY "restaurant_modules_insert"
    ON public.restaurant_modules FOR INSERT TO authenticated
    WITH CHECK (public.is_platform_admin());

CREATE POLICY "restaurant_modules_delete"
    ON public.restaurant_modules FOR DELETE TO authenticated
    USING (public.is_platform_admin());

CREATE OR REPLACE FUNCTION public.sync_tenant_features_from_modules()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_tenant_id uuid;
    v_features  jsonb;
BEGIN
    v_tenant_id := COALESCE(NEW.restaurant_id, OLD.restaurant_id);

    SELECT COALESCE(jsonb_object_agg(module_id, true), '{}') INTO v_features
    FROM public.restaurant_modules
    WHERE restaurant_id = v_tenant_id;

    UPDATE public.tenants SET features = v_features WHERE id = v_tenant_id;

    RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS trg_sync_tenant_features ON public.restaurant_modules;
CREATE TRIGGER trg_sync_tenant_features
    AFTER INSERT OR DELETE ON public.restaurant_modules
    FOR EACH ROW EXECUTE FUNCTION public.sync_tenant_features_from_modules();

-- Inicializar restaurant_modules desde tenants.features existentes
INSERT INTO public.restaurant_modules (restaurant_id, module_id)
SELECT t.id, key
FROM public.tenants t, jsonb_object_keys(t.features) AS key
WHERE t.features != '{}'
  AND EXISTS (SELECT 1 FROM public.platform_modules pm WHERE pm.key = key)
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- Usuario platform_admin
-- En cloud: crear el usuario vía Supabase Auth dashboard e insertar en platform_admins.
-- En Docker: el bloque DO $$ de la migración 20260428100000 lo crea automáticamente.
-- IMPORTANTE: insertar también en auth.identities — sin esta fila GoTrue crea un nuevo
-- auth.users con distinto UUID al hacer login, rompiendo is_platform_admin().
-- -----------------------------------------------------------------------------
-- DO $$
-- DECLARE v_user_id uuid;
-- BEGIN
--   SELECT id INTO v_user_id FROM auth.users WHERE email = 'christian@gobbly.app';
--   INSERT INTO auth.identities (provider_id, user_id, identity_data, provider, last_sign_in_at, created_at, updated_at)
--   VALUES ('christian@gobbly.app', v_user_id,
--     jsonb_build_object('sub', v_user_id::text, 'email', 'christian@gobbly.app'),
--     'email', now(), now(), now())
--   ON CONFLICT DO NOTHING;
--   INSERT INTO public.platform_admins (user_id) VALUES (v_user_id) ON CONFLICT DO NOTHING;
-- END; $$;
-- INSERT INTO public.platform_admins (user_id)
-- VALUES ('<uuid-del-usuario-christian@gobbly.app>')
-- ON CONFLICT DO NOTHING;

-- =============================================================================
-- 2026-04-28: fix views security_invoker + GoTrue NULL varchar fix
-- (management/supabase/migrations/20260428100002)
-- =============================================================================

-- Las VIEWs en PostgreSQL se ejecutan como el owner (postgres) por defecto,
-- lo que bypasea el RLS de las tablas base. security_invoker = true fuerza
-- a que la vista se ejecute como el usuario llamante.
-- Ver: https://www.postgresql.org/docs/15/sql-createview.html

-- Ya aplicado arriba en las definiciones de las views modules y restaurants.

-- Fix GoTrue: al insertar usuarios en auth.users, TODOS los campos varchar
-- de tokens deben ser '' (string vacío), NUNCA NULL.
-- GoTrue (Go) usa database/sql.Scan que no puede escanear NULL en string.
-- Afecta: confirmation_token, recovery_token, email_change_token_new,
--         email_change, email_change_token_current, phone, phone_change,
--         phone_change_token, reauthentication_token.
-- Si algún campo queda NULL, GoTrue devuelve 500 "Database error querying schema".
-- Fix de emergencia para usuarios ya creados con NULL:
-- UPDATE auth.users SET
--   confirmation_token = COALESCE(confirmation_token, ''),
--   recovery_token = COALESCE(recovery_token, ''),
--   email_change_token_new = COALESCE(email_change_token_new, ''),
--   email_change = COALESCE(email_change, ''),
--   email_change_token_current = COALESCE(email_change_token_current, ''),
--   phone = COALESCE(phone, ''),
--   phone_change = COALESCE(phone_change, ''),
--   phone_change_token = COALESCE(phone_change_token, ''),
--   reauthentication_token = COALESCE(reauthentication_token, '')
-- WHERE email = 'christian@gobbly.app';

-- =============================================================================
-- 2026-04-28: fix panel admin Roger — auth mock y identidad dev@dev.com
-- =============================================================================

-- Fix: insertar identidad para dev@dev.com (seed del Docker sin identidad)
-- Sin esta fila, GoTrue no puede autenticar vía email/password.
INSERT INTO auth.identities (provider_id, user_id, identity_data, provider, last_sign_in_at, created_at, updated_at)
SELECT
    'dev@dev.com',
    id,
    jsonb_build_object('sub', id::text, 'email', 'dev@dev.com'),
    'email',
    now(), now(), now()
FROM auth.users WHERE email = 'dev@dev.com'
ON CONFLICT DO NOTHING;

-- =============================================================================
-- 2026-04-28: tenants.features — set completo de módulos (true/false)
-- (management/supabase/migrations/20260428110000_full_feature_set_on_tenants.sql)
-- =============================================================================
-- ANTES de aplicar en cloud: asegurarse de que platform_modules tiene los
-- 6 módulos seed (reservations, kitchen, payments, daily_menus, campaigns, qr_codes).

-- 1. Trigger sync actualizado: LEFT JOIN con platform_modules → todos los módulos
CREATE OR REPLACE FUNCTION public.sync_tenant_features_from_modules()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_tenant_id uuid;
    v_features  jsonb;
BEGIN
    v_tenant_id := COALESCE(NEW.restaurant_id, OLD.restaurant_id);

    SELECT jsonb_object_agg(pm.key, (rm.module_id IS NOT NULL))
    INTO v_features
    FROM public.platform_modules pm
    LEFT JOIN public.restaurant_modules rm
        ON rm.module_id = pm.key AND rm.restaurant_id = v_tenant_id;

    UPDATE public.tenants SET features = COALESCE(v_features, '{}') WHERE id = v_tenant_id;

    RETURN COALESCE(NEW, OLD);
END;
$$;

-- 2. Trigger nuevo en platform_modules: propaga módulo nuevo (false) a todos los tenants
CREATE OR REPLACE FUNCTION public.propagate_new_module_to_tenants()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    UPDATE public.tenants
    SET features = features || jsonb_build_object(NEW.key, false)
    WHERE NOT (features ? NEW.key);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_propagate_new_module ON public.platform_modules;
CREATE TRIGGER trg_propagate_new_module
    AFTER INSERT ON public.platform_modules
    FOR EACH ROW EXECUTE FUNCTION public.propagate_new_module_to_tenants();

-- 3. Backfill: rellenar todos los tenants con el set completo
UPDATE public.tenants t
SET features = (
    SELECT jsonb_object_agg(pm.key, (rm.module_id IS NOT NULL))
    FROM public.platform_modules pm
    LEFT JOIN public.restaurant_modules rm
        ON rm.module_id = pm.key AND rm.restaurant_id = t.id
);

-- =============================================================================
-- 2026-04-28: fix sidebar — reservations faltaba en nav_items, daily_menus sin gate
-- =============================================================================
-- NOTA FRONTEND: añadir 'daily_menus' a FEATURE_GATED_NAV_KEYS en useNavItems.ts
-- (ya aplicado en la rama actual)

-- Insertar reservations en nav_items (faltaba → no aparecía en sidebar aunque el
-- feature estuviera activo, porque el store usa DB cuando hay items y no el fallback)
INSERT INTO public.nav_items (key, label_key, route_name, icon, enabled, sort_order)
VALUES (
  'reservations',
  'sidebar.reservations',
  'reservations',
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/><path d="M8 14h2m2 0h2M8 18h2"/></svg>',
  true,
  7
)
ON CONFLICT (key) DO UPDATE SET enabled = true;

-- Añadir reservations y daily_menus a role_permissions para admin y developer
-- (SectionKey en packages/types/permissions.ts y ALL_SECTIONS también actualizados)
INSERT INTO public.role_permissions (role_id, section_key)
SELECT r.id, s.key
FROM public.roles r
CROSS JOIN (VALUES ('reservations'), ('daily_menus'), ('campaigns')) AS s(key)
WHERE r.name IN ('admin', 'developer')
ON CONFLICT DO NOTHING;

-- campaigns: añadir a nav_items (faltaba igual que reservations)
INSERT INTO public.nav_items (key, label_key, route_name, icon, enabled, sort_order)
VALUES (
  'campaigns', 'sidebar.campaigns', 'campaigns',
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M15 10l4.553-2.069A1 1 0 0121 8.87V15.13a1 1 0 01-1.447.9L15 14M3 8a2 2 0 012-2h10a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V8z"/></svg>',
  true, 8
) ON CONFLICT (key) DO UPDATE SET enabled = true;
