# Agregar un vertical nuevo

La plataforma separa lo **horizontal** (compartido por todos los rubros) de lo
**vertical** (diferenciador de cada rubro). Agregar un vertical = **rellenar el
contrato**: solo escribís lo propio del dominio; el resto lo provee la plataforma.

## Lo que YA te da la plataforma (no lo escribas)

`src/finanzas/` — motor tributario (F29 con hook `ingresos()`), conciliación
bancaria, control de gastos, economía (UF/IPC).
`src/render.py` — helpers de HTML del dashboard (`_card`, `_kpis`, `_fm`, …).
`src/agents/` — insights (IA) y alertas.
Multi-tenant, auth por API key, dispatch por vertical, provisioning.

## El contrato (lo que tu vertical DEBE proveer)

En `api/src/verticals/<vertical>/`:

| Pieza | Archivo | Debe exponer |
|---|---|---|
| Esquema de datos | `schema.sql` | tablas del tenant |
| Config | `config.template.yaml` | `business.vertical`, KPIs, roles, aliases |
| Prompts IA | `insights_prompts.py` | `SYSTEM`, `PROMPTS`, `RESUMIDORES` |
| Dashboard | `dashboard.py` | `calcular_dashboard()`, `renderizar_dashboard_html(data, cfg)` |
| Copiloto Tributario | `agents/tributario/__init__.py` | `calcular_tributario_semanal(hasta)`, `renderizar_tributario_markdown(data)` |
| Hook de ingresos | `agents/tributario/ingresos.py` | `async ingresos(conn, ini, fin) -> float` |
| Conversacional | `agents/tributario/conversacional.py` | `responder_tributario(pregunta, historial)` |
| Diferenciadores | `agents/ventas.py`, `pnl_mensual.py`, `cierre_diario.py`, `cash_flow.py` | lógica de dominio del rubro |
| Guías SQL (opcional) | `sql_guidelines.md` | reglas/ejemplos SQL del rubro (se suman a las genéricas de `api/sql_guidelines.md`) |

El `agents/tributario/__init__.py` y `conversacional.py` son **wrappers de 3
líneas** sobre el motor horizontal (ver el vertical hotel/restaurante como molde):

```python
# agents/tributario/__init__.py
from src.finanzas.tributario import (
    calcular_tributario_semanal as _engine, renderizar_tributario_markdown)
from .ingresos import ingresos
async def calcular_tributario_semanal(hasta):
    return await _engine(hasta, ingresos)
```

## Pasos

1. Crear `api/src/verticals/<vertical>/` con los archivos del contrato (copiá
   hotel o restaurante como molde y adaptá el dominio).
2. Registrar el vertical en `api/src/verticals/registry.py` → `VERTICALS`.
3. `pytest` valida el contrato automáticamente (`test_contrato_verticales.py`);
   si falta algo, falla con la lista de incumplimientos.
4. (Opcional) generador de datos: `scripts/generar_datos_<vertical>.py`.
5. Provisionar un tenant:
   ```bash
   python scripts/provision_tenant.py --tenant-id <id> --nombre "<Nombre>" \
     --vertical <vertical> --base-domain majorbi.com \
     --api-key-gerente $(openssl rand -hex 32)
   docker compose restart api
   ```

## Principio horizontal vs vertical

- **Horizontal** = lo idéntico / schema-driven (conciliación, control de gastos,
  motor tributario, economía, render, insights). Vive fuera del vertical.
- **Vertical** = la lógica de dominio (ventas/RevPAR/ticket, P&L, cierre, cash
  flow, qué cuenta como ingreso). Son los diferenciadores reales.
- Para lo común dentro de lo distinto: un **hook inyectable** (como `ingresos()`),
  no un "motor" lleno de hooks.
