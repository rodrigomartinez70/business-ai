# Gap Analysis — Agentes Financieros (Chile)

Comparación entre los **15 agentes financieros objetivo** (definidos en
`doc/Agentes_Financieros_Chile.xlsx`) y lo construido en la plataforma.
Última actualización: 2026-06-08.

---

## Tabla de cobertura

| # | Agente objetivo | Estado | Implementación |
|---|-----------------|--------|----------------|
| 1 | **IVA** (determinar/proyectar IVA, F29) | 🟡 Bueno | `finanzas/tributario/iva.py` — débito/crédito/remanente/PPM/retenciones + borrador F29. **Falta:** conciliación real ERP↔SII (RCV) |
| 2 | **Cumplimiento Tributario** | 🟢 Cumple | `finanzas/tributario/cumplimiento.py` — calendario SII + vencimientos |
| 3 | **Tesorería** | 🟢 Cumple (nuevo) | `finanzas/tesoreria.py` — caja + forecast 8 sem + propuesta de pagos. Reemplaza al `cash_flow` simple |
| 4 | **Cuentas por Cobrar** | 🟢 Cumple (nuevo) | `finanzas/cuentas_por_cobrar.py` — cartera devengada, aging, DSO |
| 5 | **Cuentas por Pagar** | 🟢 Cumple (nuevo) | `finanzas/cuentas_por_pagar.py` — facturas pendientes, aging, vencidas, ranking proveedor |
| 6 | **Conciliación Bancaria** | 🟢 Cumple | `finanzas/conciliacion.py` + upload de cartolas (`finanzas/cartola.py`). **Falta:** asientos sugeridos |
| 7 | **Cierre Contable** | 🟡 Parcial | `cierre_diario.py` es operativo, no contable. Necesita libro mayor del ERP |
| 8 | **Auditor Interno** | 🔴 Falta | Necesita detalle transaccional del ERP |
| 9 | **Remuneraciones** | 🔴 Falta | Necesita integración RRHH/nómina |
| 10 | **Previred** | 🔴 Falta | Necesita integración RRHH |
| 11 | **Operación Renta** | 🔴 Falta | Necesita balance + DDJJ del ERP/SII |
| 12 | **DDJJ** | 🔴 Falta | Cumplimiento las lista, no las prepara |
| 13 | **Presupuestario** | 🟢 Cumple (nuevo) | `finanzas/presupuesto.py` — presupuesto vs ejecución YTD + desviaciones |
| 14 | **Control de Gestión** | 🟢 Cumple | `agents/alertas.py` + `agents/insights.py` + dashboards + rentabilidad/revenue |
| 15 | **CFO Virtual** | 🟢 Cumple (nuevo) | `finanzas/cfo.py` — informe ejecutivo consolidado, determinístico (sin LLM) |

**Resumen:** 10 cumplen 🟢 · 1 parcial 🟡 · 4 faltan 🔴 (+1 con mejora pendiente en IVA).

### Agentes extra (no estaban en el xlsx)
Riesgo Tributario, Conversacional Tributario (híbrido Claude/Ollama con garantía de
privacidad), Revenue Management, Rentabilidad por Canal, Marketing/Meta Ads,
SII Estado-DTE, Ventas.

---

## Lo construido en esta iteración (quick wins)

5 agentes horizontales nuevos, en `api/src/finanzas/`, expuestos en `/api/agents/`:

| Endpoint | Agente | Fuente de datos |
|----------|--------|-----------------|
| `GET /api/agents/cuentas-por-pagar` | Cuentas por Pagar | `documentos_tributarios` (vencimiento estimado = fecha + plazo) |
| `GET /api/agents/cuentas-por-cobrar` | Cuentas por Cobrar | hotel: `reservas` no cobradas · restaurante: `pedidos` abiertos |
| `GET /api/agents/presupuesto` | Presupuestario | tabla `presupuesto` vs `pagos`/`gastos` reales |
| `GET /api/agents/tesoreria` | Tesorería | caja + CxC + CxP + flujo recurrente 90d |
| `GET /api/agents/cfo` | CFO Virtual | consolida P&L, Tesorería, CxC/CxP, Presupuesto, Tributario |

Todos aceptan `?formato=json|markdown` y `?fecha=YYYY-MM-DD` (corte; default hoy).

### Nota sobre el modelo de datos (POS)
Los verticales hotel/restaurante son de **cobro al contado**, así que la cartera de
Cuentas por Cobrar puede ser baja o nula — es correcto. Cuando se conecten ERPs
(Odoo/Defontana) con facturación B2B y vencimientos reales, estos agentes ganan
profundidad sin cambios de código (solo más datos en las mismas tablas).

### Activar el Agente Presupuestario
Requiere cargar la tabla `presupuesto` (año, mes, tipo `ingreso|gasto`, categoría, monto).
La migración `postgres/migrations/006_presupuesto.sql` crea la tabla; aplicarla por
cada schema de tenant. Las categorías de gasto deben coincidir (por nombre) con
`categorias_gasto` para que la comparación calce.

---

## Pendiente (bloqueado por datos, no por código)

| Necesidad | Desbloquea |
|-----------|------------|
| Integración **RRHH/nómina** | Remuneraciones, Previred, DDJJ (honorarios/remun.) |
| **Libro mayor** real del ERP (Odoo/Defontana ya están mock) | Cierre Contable, Auditor Interno, Operación Renta |
| **RCV + certificado digital** del SII | IVA conciliación ERP↔SII, DDJJ, Operación Renta |

El cuello de botella es **fuente de datos**, no agentes. Ver memorias de integraciones
(`project_odoo_integracion`, `project_defontana_integracion`, `project_sii_dte`).

---

## Mejoras futuras de los agentes nuevos
- **Conciliación:** generar asientos contables sugeridos.
- **CxP:** usar `fecha_vencimiento` real cuando el ERP la provea (hoy se estima).
- **CFO Virtual:** narrativa con LLM sobre métricas/% (sin montos a Claude), si se desea.
- **Tesorería:** incorporar líneas de crédito y vencimientos de obligaciones financieras.
