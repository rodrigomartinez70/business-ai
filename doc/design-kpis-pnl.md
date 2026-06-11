# Diseño — KPIs y P&L particulares por empresa

Estado: **propuesta para revisar** (no implementado). Autor: arquitectura MBI.
Decisión base: config-as-data (opción 2) + catálogo de métricas seguras (B) → síntesis.

---

## 1. Problema y objetivo

El modelo tiene 3 capas:
- **Horizontal** — motores genéricos (P&L `finanzas/pnl.py`, evaluador de KPIs `agents/alertas.py`, IVA, tesorería, CxC/CxP…).
- **Vertical** — el *tipo* de negocio: hooks (`ingresos_fn`, `costo_ventas_fn`), `schema.sql`, agentes propios.
- **Tenant** — la *instancia*: `config` JSONB en `public.tenants.config`.

Cada empresa tiene **particularidades** (KPIs propios, estructura de P&L propia, umbrales). Queremos poder **cargar una empresa y configurar sus particularidades sin deploy** para el caso común, de forma **segura** y **self-service** desde MBI Admin.

Hoy ya hay seams declarativos:
- **KPIs**: `agents/alertas.py` los lee del config (cada KPI = SQL + unidad + umbral).
- **P&L**: `finanzas/pnl.py` es horizontal; toma hooks del vertical y lee del `config.pnl` las líneas sin fuente de dato (depreciación, financieros, impuesto).

Limitaciones actuales: SQL crudo en el config (footgun de seguridad si se edita por UI), sin validación, P&L con estructura **fija** en código.

---

## 2. Decisión de arquitectura

1. **El config (JSONB en la DB) es la fuente de verdad** de las particularidades. Ya existe.
2. Se introduce una **capa semántica**: un **catálogo de métricas** nombradas y seguras, definidas en código (vertical + horizontal). Los KPIs y el P&L se construyen **referenciando métricas**, nunca SQL del usuario.
3. **Edición**: editor del config **validado por JSON-Schema** (power-tool) + **forms estructurados** (KPI builder / P&L builder) como evolución. Import/export YAML.
4. **Escape hatch**: un **registro de "calculadores"** en código para la métrica bespoke rara. Agregar uno = función + registro (tarea chica de dev). Es lo único que pide deploy.

> Esto es el patrón *semantic layer* (LookML / dbt-metrics / Cube), adaptado y minimal.

---

## 3. Catálogo de métricas

Una **métrica** es una función vetada por dev que devuelve **un número para un período** `(conn, ini, fin) -> float`, registrada con un nombre estable. El usuario **nunca** escribe la query; solo **referencia** la métrica.

```python
# src/metricas/registry.py  (horizontal)
@metrica("ingresos", unidad="moneda", label="Ingresos")
async def ingresos(conn, ini, fin) -> float: ...

# src/verticals/restaurante/metricas.py
@metrica("ventas", unidad="moneda", label="Ventas (pedidos pagados)")
async def ventas(conn, ini, fin) -> float: ...
@metrica("food_cost", unidad="moneda")
async def food_cost(conn, ini, fin) -> float: ...
@metrica("gasto", unidad="moneda", params=["categoria"])
async def gasto(conn, ini, fin, categoria) -> float: ...
```

**Catálogo inicial (ejemplos):**
- **Horizontal**: `ingresos`, `gastos_total`, `gasto[categoria]`, `cobros`, `egresos`, `caja`, `cxc_total`, `cxp_total`, `iva_debito`, `iva_credito`, `saldo_iva`.
- **Restaurante**: `ventas`, `n_pedidos`, `ticket_promedio`, `food_cost`, `costo_ventas`, `margen_bruto`, `propinas`.
- **Hotel**: `hospedaje`, `ocupacion_pct`, `adr`, `revpar`, `noches`, `consumos`, `gop`, `cancelacion_pct`.

**Seguridad**: el catálogo lo define el dev. El usuario solo elige nombres del catálogo. Cero SQL en el config. La UI ofrece el catálogo como dropdown.

---

## 4. Modelo de KPI particular

```yaml
kpis:
  - clave: food_cost_pct
    nombre: "Food cost %"
    formula: "food_cost / ventas * 100"      # fórmula sobre el catálogo
    unidad: "%"
    umbral_max: 35                            # alerta si supera
    formato: "0.0"
  - clave: ticket_promedio
    nombre: "Ticket promedio"
    metrica: ticket_promedio                  # o referencia directa a una métrica
    unidad: moneda
```

- **Evaluador de fórmulas seguro**: `ast.parse` + whitelist (nombres = métricas del catálogo, operadores aritméticos, funciones permitidas `min/max/abs/round`). **Sin `eval`**, sin acceso a Python. Referencia a métrica inexistente → error de validación.
- **Default + override**: el vertical trae un set de KPIs default; el tenant **agrega/override** por `clave`.
- **Coexistencia**: los KPIs-SQL actuales de `alertas.py` siguen funcionando (camino dev); los nuevos por-fórmula son los editables por UI. Migración gradual.

---

## 5. Modelo de P&L particular

El P&L pasa de estructura fija a **plantilla de líneas** (ordenada):

```yaml
pnl:
  plantilla:
    - id: ing_brutos      ; etiqueta: "Ingresos Brutos"      ; tipo: detalle  ; fuente: "metrica:ingresos"
    - id: devol           ; etiqueta: "(-) Devoluciones"     ; tipo: detalle  ; fuente: "const:devoluciones" ; signo: -1
    - id: ing_netos       ; etiqueta: "= Ingresos Netos"     ; tipo: subtotal ; fuente: "ref:ing_brutos,devol"
    - id: costo_ventas    ; etiqueta: "(-) Costo de Ventas"  ; tipo: detalle  ; fuente: "metrica:costo_ventas" ; signo: -1
    - id: margen_bruto    ; etiqueta: "= Margen Bruto"       ; tipo: subtotal ; fuente: "ref:ing_netos,costo_ventas"
    - id: gastos_op       ; etiqueta: "(-) Gastos Operativos"; tipo: detalle  ; fuente: "formula:gastos_total" ; signo: -1
    - id: ebitda          ; etiqueta: "= EBITDA"             ; tipo: subtotal ; fuente: "ref:margen_bruto,gastos_op"
    # … depreciación, financieros, impuesto, resultado neto …
```

- **Fuente** ∈ `metrica:<name>` · `formula:<expr>` · `const:<config_key>` · `ref:<line_ids>` (suma de líneas) · `hook:<vertical_fn>`.
- El **motor** (generalización de `pnl.py`) evalúa la plantilla **top-down**, resuelve `ref`/`formula`, y arma la comparativa **actual vs año anterior** (que ya hace hoy).
- El **vertical trae una plantilla default** (la estructura hardcodeada actual); el **tenant la override** para sus particularidades (agregar/quitar/reordenar líneas, cambiar fuentes).
- Validación: detectar `ref` circular, métricas/ids inexistentes, antes de guardar.

---

## 6. Esquema del config + validación

El `config` del tenant gana (todo opcional; si falta, usa el default del vertical):

```yaml
report:
  modulos: { ... }          # ya existe
kpis: [ ... ]               # §4
pnl:
  plantilla: [ ... ]        # §5
  constantes: { devoluciones: 0, impuesto_pct: 0 }
```

- **JSON-Schema** valida estructura + tipos + claves de catálogo conocidas, **al guardar** (en el servicio admin) y en el **editor** (muestra errores antes de aplicar).
- Guardar inválido → se rechaza (no rompe el tenant). El registry **no recarga** un config inválido.

---

## 7. Edición (MBI Admin)

El editor vive **dentro de la app** (MBI Admin), no es un archivo en el server ni una herramienta aparte. `/admin/tenants/{id}/config`.

**Editor de código tipo VSCode** (power-tool):
- **Componente de editor embebido** (CodeMirror — recomendado por liviano — o Monaco, el motor de VSCode; vía CDN como HTMX): resaltado YAML, números de línea, plegado.
- **Scaffold de arranque**: un config vacío se abre **pre-cargado con la plantilla del vertical** (todas las secciones con comentarios/placeholders) → se llena, no se recuerda de memoria.
- **No olvidar componentes** se garantiza con: (1) el scaffold, (2) **validación JSON-Schema en vivo** que marca errores y claves requeridas faltantes (no guarda inválido), (3) **autocomplete del catálogo de métricas** en las fórmulas.

**Forms estructurados** (fase posterior, modo guiado): **KPI builder** (nombre + fórmula con autocomplete + umbrales) y **P&L builder** (líneas reordenables, fuente por dropdown). Escriben el **mismo** config — imposible olvidar un campo.

**Import/Export YAML** del config completo (migración / clonar empresa).

---

## 8. Fases de implementación

| Fase | Entregable |
|------|------------|
| **0** | Catálogo de métricas (horizontal + restaurante + hotel) + **evaluador de fórmulas seguro** (AST whitelist) + JSON-Schema del config |
| **1** | **KPIs por fórmula**: evaluación en alertas/dashboard + editor de config validado (UI) — *valor rápido* |
| **2** | **P&L como plantilla**: generalizar `pnl.py`, template default por vertical, override por tenant |
| **3** | **Forms estructurados** (KPI builder / P&L builder) sobre el config |
| **4** | Import/export YAML + versionado del config + registro de "calculadores" (escape hatch) |

---

## 9. Riesgos y decisiones abiertas

- **SQL crudo actual** (`alertas.py`): se mantiene para dev, se **deprecia** para la UI. Migrar los KPIs existentes a fórmula.
- **Performance**: cada métrica = query. Cachear por `(tenant, métrica, período)` dentro de un request (un dashboard pide muchas).
- **Validación**: referencias circulares en P&L, métrica/constante inexistente, división por cero en fórmulas.
- **Rol/permisos**: ¿quién edita el config? (¿solo superadmin, o un rol "analista"?).
- **Vertical default**: dónde viven los KPIs/plantilla default (¿`config.template.yaml` del vertical o un módulo `defaults.py`?). Propuesta: módulo Python (versionado con el código).
- **Compatibilidad**: tenants sin `kpis`/`pnl` en config → usan el default del vertical (cero migración forzada).

---

## 10. Recomendación de arranque

**Fase 0 + Fase 1** primero: catálogo de métricas + evaluador seguro + KPIs por fórmula con el editor de config validado. Es el menor riesgo, da valor rápido (KPIs particulares por empresa, self-service) y construye la base que el P&L (Fase 2) reusa.
