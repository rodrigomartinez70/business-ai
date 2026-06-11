-- 007_tenant_config.sql — Config del tenant como JSONB (editable por el back-office MBI Admin).
-- Si public.tenants.config está presente, el registry lo prefiere por sobre el config_path YAML.
-- Esto permite gestionar la configuración (destinatarios, módulos, etc.) desde la UI/API.

ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS config jsonb;

COMMENT ON COLUMN public.tenants.config IS
  'Config del tenant en JSON. Reemplaza al config_path YAML cuando está presente.';
