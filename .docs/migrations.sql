-- Migrations pendientes de aplicar en Supabase
-- Aplicar en orden cronológico

-- 2026-04-28: columnas de plataforma en tenants
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS trial_ends_at timestamptz;
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS features jsonb NOT NULL DEFAULT '{}';
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS branding jsonb NOT NULL DEFAULT '{}';

-- 2026-04-28: catálogo de módulos de plataforma
CREATE TABLE IF NOT EXISTS public.platform_modules (
    key text PRIMARY KEY,
    name text NOT NULL,
    description text,
    is_active boolean NOT NULL DEFAULT true,
    sort_order integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public.platform_modules (key, name, description, sort_order) VALUES
    ('reservations', 'Reservas', 'Gestión de reservas de mesas', 1),
    ('kitchen', 'Cocina', 'Panel de cocina y gestión de estados de platos', 2),
    ('payments', 'Pagos', 'Procesamiento de pagos y métodos de pago', 3),
    ('daily_menus', 'Menús del día', 'Creación y gestión de menús diarios', 4),
    ('campaigns', 'Campañas', 'Descuentos y campañas promocionales', 5),
    ('qr_codes', 'Códigos QR', 'Generación de QR por mesa', 6)
ON CONFLICT (key) DO NOTHING;

-- RLS: catálogo legible por autenticados, escritura solo service_role
ALTER TABLE public.platform_modules ENABLE ROW LEVEL SECURITY;

CREATE POLICY "platform_modules_select"
    ON public.platform_modules
    FOR SELECT
    TO authenticated
    USING (true);
