# Diseño — Packs de datos componibles (reemplazo del "vertical por rubro")

Estado: **propuesta para revisar** (no implementado). Cierra la dirección de
`doc/design-kpis-pnl.md` y `doc/design-pnl-erp.md`.

Idea central: **una empresa no "es" una vertical** — es la **composición de los
sistemas de datos que tiene** (POS, ERP, banco, manual). Cada uno aporta sus
tablas + sus fuentes. Son **componibles** (un restaurante puede tener POS *y* ERP).

---

## 1. El problema

Hoy `vertical` mezcla 2 ejes ortogonales:
- **Qué ES** la empresa (rubro: hotel, restaurante, fábrica).
- **Qué sistemas de datos TIENE** (POS, ERP, banco, marketing, manual).

Y los trata como **excluyentes** (elegís uno). Pero un restaurante puede tener
Toteat (POS) **y** Odoo (ERP) **y** banco **y** Meta a la vez. "Una vertical" no
lo captura.

Tras lo construido, el `vertical` solo controla ya: (a) qué `schema.sql` se crea,
(b) qué fuentes están disponibles, (c) 2 módulos en código (Cierre, P&L default).
Todo lo demás (módulos, KPIs, P&L plantilla, Ventas, integraciones) ya es por-empresa.

---

## 2. El modelo: packs componibles + preset

Separar en **dos conceptos**:

1. **Packs de datos** — *estructurales*, **componibles**. Cada pack aporta **tablas + fuentes**. Lo que la empresa **tiene**.
2. **Preset** (opcional, ex-"rubro") — un bundle de config inicial (módulos/KPIs/Ventas) para arrancar rápido. *Editable, no estructural.* Lo que la empresa **es**.

Al **crear** una empresa: tildás los **packs** que correspondan (checkboxes) + opcionalmente un **preset**.

### Catálogo de packs (inicial)

| Pack | Aporta tablas (ejemplo) | Habilita fuentes / módulos |
|------|------------------------|-----------------------------|
| **base** (siempre) | categorias_gasto, gastos, documentos_tributarios, movimientos_bancarios, presupuesto, audit_log, canales_venta | Gastos, Tributario, CxC/CxP (desde facturas), Tesorería, Presupuesto, Conciliación |
| **pos_gastronomico** | productos, categorias_menu, mesas, pedidos, detalle_pedido, pagos | `metrica:ventas/n_pedidos/...`, `tabla:ventas_por_canal/top_productos`, Cierre POS |
| **pos_hotelero** | habitaciones, huespedes, reservas, pagos, consumos_frigobar, consumos_servicios | `metrica:hospedaje/noches/...`, `tabla:hospedaje_por_canal`, Revenue/ADR |
| **erp** | plan_cuentas, saldos_cuentas | `cuentas:tipo=income/cogs/...`, P&L contable |
| **marketing** | canales_marketing, campanas, insights_marketing | módulo Marketing (Meta Ads) |

Ejemplos de composición:
- **Restaurante** = base + pos_gastronomico (+ erp si tiene Odoo, + marketing si tiene Meta).
- **Hotel** = base + pos_hotelero (+ erp).
- **Fábrica de Ventanas** = base + erp (+ marketing). **Sin POS.**

> Los módulos **degradan solo**: si no tenés el pack, su fuente no existe → el módulo
> queda vacío o se apaga. Ej. la fábrica no tiene `metrica:ventas` (no hay POS); su
> Ventas sale de `cuentas:` (erp).

---

## 3. Cómo se implementa

### Estructura
```
src/packs/<pack>/schema.sql     # fragmento de tablas (CREATE TABLE IF NOT EXISTS)
src/packs/<pack>/sources.py     # registra métricas + fuentes de tabla del pack
src/packs/<pack>/defaults.py    # (opcional) config default que aporta el pack
```

### Dato por tenant
`public.tenants` gana **`packs text[]`** (ej. `{base, pos_gastronomico, erp}`). Es
estructural (afecta schema + carga de fuentes), por eso columna y no solo config.

### Alta de empresa
1. Validar slug/nombre.
2. `CREATE SCHEMA`.
3. Aplicar **la unión** de los `schema.sql` de los packs elegidos (base primero;
   todos idempotentes, así que el orden y los solapes no rompen).
4. Guardar `packs` + el config (del preset, si se eligió).
5. Generar API key + recargar registry.

### Carga de fuentes
El registry de métricas/tablas pasa de `cargar_vertical(vertical)` a
**`cargar_packs(packs)`**: importa el `sources.py` de cada pack activo del tenant.
Lookup de fuentes = unión de las de sus packs (+ horizontales).

---

## 4. Migración de los tenants actuales

Mapeo directo y **sin recrear nada** (los schemas ya existen; los fragmentos son
`IF NOT EXISTS`):
- `hotel` → `packs = {base, pos_hotelero}`
- `restaurante` → `packs = {base, pos_gastronomico}`
- (+ `erp` a los que ya tienen plan_cuentas/saldos, ej. los que migramos.)

`vertical` se mantiene **transitoriamente** (ver §5).

---

## 5. Lo que todavía está atado a "vertical" (y el plan para soltarlo)

Estos siguen en código por tipo; el `vertical` se mantiene como **etiqueta de
transición** hasta soltarlos:
- **Orquestación del dashboard** (`dispatch.dashboard().calcular_dashboard()`): junta
  ventas/rent/revenue/cierre por vertical. → migrar a ensamblado por módulos/packs.
- **Módulo "Cierre"** (POS-específico). → hacerlo config-driven como hicimos con Ventas.
- **P&L default** (motor hardcodeado; el override por plantilla ya es config). → opcional:
  expresar el default como plantilla por pack.

Cuando estos 3 sean config-driven/por-pack, **`vertical` desaparece**.

---

## 6. Fases

| Fase | Entregable | Estado |
|------|------------|--------|
| **P1** | `src/packs/` (base, pos_gastronomico, pos_hotelero, erp) + `public.tenants.packs` + `cargar_packs` en el registry. El alta ensambla el schema desde packs. Migrar tenants actuales (set `packs`). Sin cambio visible. | **✅ HECHO** (commit 58bcafb, migración 011 aplicada en prod, backfill 1:1 verificado) |
| **P2** | **Alta de empresa por packs** (checkboxes) + preset (plantillas reutilizables), en MBI Admin. | **✅ HECHO** (commit f0896ff, verificado en vivo: select de preset + checkboxes HTMX + chips en la tabla) |
| **P3** | Soltar lo vertical-code: Cierre config-driven + orquestación del informe por módulos → **eliminar `vertical`**. | pendiente |
| **P4** | Packs nuevos (pos_retail, servicios…) + crear la **Fábrica** (base + erp) con su Ventas por `cuentas:`. | pendiente |

> **Nota P1:** el pack `marketing` quedó fuera del alcance (sus tablas viven en la
> migración 004, no en los schema.sql de vertical). Se agrega en P4. El mapeo
> `cargar_packs` hoy delega en los módulos de métricas por-vertical existentes
> (`src.verticals.<v>.metricas`); las fuentes se mudan físicamente al pack en P3.

---

## 7. Decisiones abiertas / riesgos

- **`packs` columna vs en config**: propongo columna `text[]` (es estructural). 
- **Preset**: ¿lo guardamos como "plantillas de config" reutilizables (restaurante, hotel, comercial) que el alta copia al config del tenant? (Recomendado.)
- **Transición de `vertical`**: convive con `packs` en P1-P2; se elimina en P3. Riesgo: el dispatch del dashboard depende de `vertical` hasta P3.
- **Solapes de tablas entre packs** (ej. `canales_venta`, `pagos`): definir a qué pack pertenece cada tabla sin duplicar. `pagos` (FK a pedido/reserva) es POS — en base-only no existe; CxC ahí sale de facturas.
- **Dynamic schema**: aplicar fragmentos al crear es seguro (DDL idempotente); agregar un pack a un tenant existente = aplicar su fragmento (también idempotente).
- **Permisos/grants**: en prod superuser (no-op); en tests, agregar las tablas de cada pack a los GRANT.

---

## 8. Recomendación de arranque

**P1** primero (packs estructurales + `cargar_packs` + migrar tenants), **sin cambiar
nada visible** — es refactor de fondo de bajo riesgo (schemas idempotentes, mapeo 1:1).
Después P2 (alta por checkboxes) y recién ahí creamos la Fábrica como `base + erp`.
P3 (eliminar `vertical`) queda para cuando Cierre + orquestación sean config-driven.
