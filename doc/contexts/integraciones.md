# Contexto: Integraciones

## Importación CSV (`/api/ingest`)

### Decisión de diseño
Las tablas permitidas para importar CSV no deben ser una lista hardcodeada.

**Solución acordada:** en runtime, derivar las tablas permitidas del schema real de PostgreSQL, excluyendo las tablas definidas en `schema.exclude_tables` del config.yaml. Sin lista estática en el código.

**Por qué:** la lista hardcodeada actual (`habitaciones`, `reservas`, etc.) es específica del hotel. Cada negocio tiene tablas distintas y no debería requerir cambios de código.
