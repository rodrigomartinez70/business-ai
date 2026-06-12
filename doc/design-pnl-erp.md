# Diseño — P&L contable desde ERP (cuentas agrupadas)

Estado: **propuesta para revisar** (no implementado). Continúa `doc/design-kpis-pnl.md` (F2).
Idea central: con un ERP, cada línea del P&L = **suma de saldos de un grupo de cuentas**.
La plantilla de F2 ya es la herramienta de configuración; solo falta un nuevo tipo de
fuente (`cuentas:`) y traer el mayor a nuestra DB.

---

## 1. Por qué

El P&L genérico (17 líneas: Ingresos Brutos → … → Resultado Neto) es, en contabilidad,
la **suma de saldos de cuentas agrupadas por línea**. Un ERP (Odoo, Defontana) tiene el
**plan de cuentas** con tipo/grupo por cuenta. Entonces:
- Las 2 brechas del P&L-por-métricas **desaparecen**: gastos por bucket = grupos de cuentas;
  impuesto = saldo real de la cuenta de impuesto (no una estimación).
- Es más preciso y es el estándar contable.

**Unificación clave:** la **misma plantilla** sirve para los dos mundos; solo cambia la fuente.

| Cliente | Fuente de cada línea |
|---|---|
| Sin ERP (POS: hotel/restaurante) | `metrica:…` (tablas operativas; estimaciones) |
| Con ERP (Odoo/Defontana) | `cuentas:…` (saldos contables reales agrupados) |

---

## 2. Modelo de datos (en el schema del tenant)

```sql
CREATE TABLE plan_cuentas (
    id          SERIAL PRIMARY KEY,
    id_externo  VARCHAR(64),          -- id de la cuenta en el ERP
    codigo      VARCHAR(40),          -- '4.1.01'
    nombre      VARCHAR(200),
    tipo        VARCHAR(40),          -- account_type normalizado: income | cogs | expense | tax | ...
    grupo       VARCHAR(80),          -- agrupador/parent (opcional)
    UNIQUE (id_externo)
);

CREATE TABLE saldos_cuentas (
    cuenta_id   INTEGER REFERENCES plan_cuentas(id),
    anio        SMALLINT,
    mes         SMALLINT,             -- movimiento del período (no acumulado)
    debe        NUMERIC(14,2) DEFAULT 0,
    haber       NUMERIC(14,2) DEFAULT 0,
    UNIQUE (cuenta_id, anio, mes)
);
```

- Granularidad **mensual** por cuenta → P&L YTD = suma de meses 1..corte; comparativo = mismo rango del año anterior. (Para corte a mitad de mes es aprox.; la alternativa exacta es guardar `account.move.line` y sumar por fecha — más datos. Recomiendo mensual para v1.)
- **Signo:** el saldo "natural" de la cuenta se normaliza por `tipo` (income = haber−debe; expense/cogs/tax = debe−haber). La presentación (negativo en el P&L) la da el `signo` de la línea en la plantilla.

---

## 3. Sync del ERP (Odoo)

El conector `integraciones/odoo.py` (hoy mock) gana:
- `obtener_plan_cuentas()` → `account.account` (code, name, **account_type**, group). Mapeo de account_type de Odoo → nuestro `tipo` normalizado (income, expense_direct_cost→cogs, expense, …).
- `obtener_saldos(desde, hasta)` → `read_group` sobre `account.move.line` (solo asientos *posted*, cuentas de resultado) sumando debe/haber **agrupado por cuenta + mes**.
- Mapper → puebla `plan_cuentas` + `saldos_cuentas` del tenant. Cron diario + on-demand.
- Credenciales por la UI de integraciones que ya existe (proveedor `odoo`). **Defontana** = mismo patrón, otro conector/mapeo.

---

## 4. Fuente `cuentas:` en el motor de plantilla

Nuevo tipo de fuente en `pnl_plantilla.py`, además de `metrica:`/`formula:`/`const:`/`ref:`:

```
cuentas:tipo=cogs
cuentas:codigo=4100-4199      # rango
cuentas:grupo=6.2
cuentas:id=123,124            # cuentas puntuales
```

- En la fase de pre-cálculo (análoga a las métricas), se resuelven todos los filtros `cuentas:` a sumas por período (actual + anterior), sumando `saldos_cuentas` de las cuentas que matchean el filtro, normalizado por tipo.
- Validación (editor): el filtro debe resolver a ≥1 cuenta existente; sintaxis del filtro válida.

---

## 5. Mapeo cuenta→línea (la configuración)

Vive en la **misma plantilla** del editor (config.pnl.plantilla) — no hay UI nueva:

```yaml
pnl:
  plantilla:
    - {id: ing_brutos,  etiqueta: "Ingresos Brutos",     tipo: detalle,  fuente: "cuentas:tipo=income"}
    - {id: costo,       etiqueta: "(-) Costo de Ventas",  tipo: detalle,  fuente: "cuentas:tipo=cogs", signo: -1}
    - {id: margen,      etiqueta: "= Margen Bruto",       tipo: subtotal, fuente: "ref:ing_brutos,costo"}
    - {id: g_admin,     etiqueta: "• Administración",     tipo: sub,      fuente: "cuentas:grupo=6.2", signo: -1}
    - {id: impuesto,    etiqueta: "(-) Impuesto a la Renta", tipo: detalle, fuente: "cuentas:tipo=tax", signo: -1}
    - {id: resultado,   etiqueta: "= Resultado Neto",     tipo: total,    fuente: "ref:margen,g_admin,impuesto"}
```

Más adelante (F3) un **selector visual** del plan sincronizado (autocomplete de cuentas) para armar el filtro sin escribirlo.

---

## 6. Default contable

Una **plantilla default "modo contable"** (las 17 líneas estándar) usando `cuentas:tipo=…`
con los account_type **universales** de Odoo (income, cogs, expense, tax). Cada empresa
después refina los grupos (g. marketing vs admin vs generales) según su plan real.

Cómo elegir el default por tenant: si el tenant tiene **integración ERP activa** (Odoo/Defontana
en `public.integraciones`) → default contable (`cuentas:`); si no → default POS (`metrica:`/hardcodeado actual).

---

## 7. Fases

| Fase | Entregable |
|------|------------|
| **E1** | Tablas `plan_cuentas` + `saldos_cuentas` + sync real de Odoo (plan + saldos mensuales) + mapper/cron |
| **E2** | Fuente `cuentas:` en `pnl_plantilla.py` (pre-cálculo por filtro + normalización por tipo) + validación |
| **E3** | Plantilla default "contable" + selección de default por modo (ERP vs POS) |
| **E4** | Selector visual de cuentas en el editor (autocomplete del plan) + Defontana |

---

## 8. Decisiones abiertas / riesgos

- **Convención de signos** y mapeo de `account_type` Odoo → nuestro `tipo` (income/cogs/expense/tax/…). Es el detalle contable más delicado.
- **Granularidad**: mensual (recomendado) vs `move.line` exacto.
- **Año fiscal / multimoneda / asientos no-posted**: v1 asume año calendario, una moneda, solo posted.
- **Modo ERP vs POS**: cómo se decide (propuesta: por integración activa); ¿un tenant podría mezclar (algunas líneas `cuentas:` y otras `metrica:`)? La plantilla lo permite naturalmente.
- **Defontana**: plan de cuentas y API distintos a Odoo → mismo modelo de datos, otro mapper.
- **Performance**: una consulta de saldos por filtro × 2 períodos; cachear el plan + saldos por request.

---

## 9. Recomendación de arranque

**E1 + E2**: traer el mayor real de Odoo a `plan_cuentas`/`saldos_cuentas` y agregar la fuente
`cuentas:` al motor. Con eso ya se puede armar el P&L contable de un cliente Odoo desde el editor
(E3 default + E4 selector son refinamientos). Requiere credenciales reales de un Odoo para validar
el mapeo de account_type.
