# SQL Guidelines — Patrones preferidos

Estas guías se inyectan en el prompt de Claude para mejorar la calidad del SQL generado.
Agregar nuevos patrones en la misma estructura.

---

## Nomenclatura — Aliases con sentido del negocio hotelero

Usar siempre nombres en español que el dueño del negocio reconozca. Nunca usar jerga de retail o términos ambiguos.

| En vez de | Usar |
|---|---|
| `ticket_promedio` | `gasto_promedio` |
| `avg_revenue` | `ingreso_promedio` |
| `count` | `cantidad_reservas` / `cantidad_huespedes` (según contexto) |
| `revenue` | `ingresos` |
| `pct` | `porcentaje` |
| `num_nights` | `noches` |
| `check_in` / `check_out` | `fecha_entrada` / `fecha_salida` |
| `booking` | `reserva` |
| `rate` | `tarifa` |
| `occupancy` | `ocupacion_pct` |

**Ejemplos correctos:**
```sql
SELECT
    c.nombre                                          AS canal,
    SUM(r.total_hospedaje)                            AS ingresos,
    COUNT(r.id)                                       AS cantidad_reservas,
    ROUND(SUM(r.total_hospedaje) / COUNT(r.id), 0)   AS gasto_promedio
FROM reservas r
JOIN canales_venta c ON r.canal_id = c.id
WHERE r.estado NOT IN ('cancelada', 'no_show')
GROUP BY c.nombre
ORDER BY ingresos DESC
```

---

## Consultas multi-período

Cuando el usuario pide datos de múltiples años o meses, usar **una sola query** con `GROUP BY` período en lugar de queries separadas.

**Preferido:**
```sql
SELECT c.nombre AS canal,
       EXTRACT(YEAR FROM r.fecha_entrada) AS año,
       SUM(r.total_hospedaje) AS ventas
FROM reservas r
JOIN canales_venta c ON r.canal_id = c.id
WHERE EXTRACT(YEAR FROM r.fecha_entrada) IN (2025, 2026)
  AND r.estado != 'cancelada'
GROUP BY c.nombre, EXTRACT(YEAR FROM r.fecha_entrada)
ORDER BY año, ventas DESC
```

**Evitar:** dos queries separadas (una por año) cuando se puede hacer con `IN (...)` y `GROUP BY año`.

---

## Rankings con límite

Para "top N" o "los más..." usar siempre `ORDER BY ... DESC LIMIT N`.

**Preferido:**
```sql
SELECT h.numero, h.tipo, COUNT(r.id) AS reservas
FROM habitaciones h
JOIN reservas r ON r.habitacion_id = h.id
GROUP BY h.id, h.numero, h.tipo
ORDER BY reservas DESC
LIMIT 10
```

---

## Comparación entre períodos

Para "comparar X vs Y" o "variación entre períodos", usar CTEs con JOIN final.

**Preferido:**
```sql
WITH periodo_a AS (
    SELECT SUM(monto) AS total FROM pagos
    WHERE fecha >= '2025-01-01' AND fecha < '2026-01-01' AND estado = 'pagado'
),
periodo_b AS (
    SELECT SUM(monto) AS total FROM pagos
    WHERE fecha >= '2026-01-01' AND fecha < '2027-01-01' AND estado = 'pagado'
)
SELECT
    a.total AS total_2025,
    b.total AS total_2026,
    b.total - a.total AS variacion,
    ROUND((b.total - a.total) * 100.0 / NULLIF(a.total, 0), 1) AS variacion_pct
FROM periodo_a a, periodo_b b
```

---

## Ocupación, ADR y RevPAR

Para métricas de revenue management usar siempre el total de habitaciones activas como denominador.
- **Ocupación %** = noches vendidas / (habitaciones activas × días del período) × 100
- **ADR** = ingresos / noches vendidas
- **RevPAR** = ingresos / (habitaciones activas × días del período)

Las noches se atribuyen al mes de check-in. Para estadías que cruzan meses esto es una aproximación válida para estancias cortas.

**Dashboard mensual (año en curso):**
```sql
WITH total_hab AS (
    SELECT COUNT(*) AS total FROM habitaciones WHERE activa = true
),
ventas AS (
    SELECT
        DATE_TRUNC('month', fecha_entrada)::date AS mes,
        SUM(noches)          AS noches_vendidas,
        SUM(total_hospedaje) AS ingresos
    FROM reservas
    WHERE EXTRACT(YEAR FROM fecha_entrada) = EXTRACT(YEAR FROM CURRENT_DATE)
      AND estado NOT IN ('cancelada', 'no_show')
    GROUP BY DATE_TRUNC('month', fecha_entrada)
)
SELECT
    TO_CHAR(v.mes, 'Mon YYYY') AS mes,
    ROUND(v.noches_vendidas::numeric
          / (t.total * EXTRACT(DAY FROM (v.mes + INTERVAL '1 month') - v.mes)) * 100, 1) AS ocupacion_pct,
    ROUND(v.ingresos / NULLIF(v.noches_vendidas, 0), 0) AS adr,
    ROUND(v.ingresos
          / (t.total * EXTRACT(DAY FROM (v.mes + INTERVAL '1 month') - v.mes)), 0) AS revpar,
    ROUND(v.ingresos, 0) AS ingresos_total
FROM ventas v
CROSS JOIN total_hab t
ORDER BY v.mes
```

**Evitar:** usar 30 días fijos para todos los meses. Usar siempre `EXTRACT(DAY FROM (mes + INTERVAL '1 month') - mes)` para obtener los días reales del mes.

**Nombres de meses en español:** `TO_CHAR` devuelve meses en inglés. Usar siempre este CASE:
```sql
CASE EXTRACT(MONTH FROM v.mes)::int
    WHEN 1 THEN 'Ene' WHEN 2 THEN 'Feb' WHEN 3 THEN 'Mar'
    WHEN 4 THEN 'Abr' WHEN 5 THEN 'May' WHEN 6 THEN 'Jun'
    WHEN 7 THEN 'Jul' WHEN 8 THEN 'Ago' WHEN 9 THEN 'Sep'
    WHEN 10 THEN 'Oct' WHEN 11 THEN 'Nov' WHEN 12 THEN 'Dic'
END || ' ' || EXTRACT(YEAR FROM v.mes)::int AS mes
```

**Para "el mejor mes" o "el peor mes":** agregar `LIMIT 1` al ORDER BY existente.

```sql
-- "¿cuál fue el mes con mejor RevPAR?"
... ORDER BY revpar DESC LIMIT 1
```

---

## Margen neto por canal

Para calcular margen descontando comisión de la OTA usar `comision_pct` de `canales_venta`.
- Alias `comision_pct` (porcentaje, no dinero) y `ingresos_netos` (dinero).
- Alias `margen_promedio` para el margen por reserva — **no** usar `margen_promedio_por_reserva`.
- Para "¿qué canal me deja mejor margen?" agregar `LIMIT 1`.

**Preferido:**
```sql
SELECT
    c.nombre                                                              AS canal,
    SUM(r.total_hospedaje)                                               AS ingresos_brutos,
    c.comision_pct,
    ROUND(SUM(r.total_hospedaje) * (1 - c.comision_pct / 100), 0)       AS ingresos_netos,
    ROUND(SUM(r.total_hospedaje) * (1 - c.comision_pct / 100)
          / NULLIF(COUNT(r.id), 0), 0)                                   AS margen_promedio
FROM reservas r
JOIN canales_venta c ON r.canal_id = c.id
WHERE r.estado NOT IN ('cancelada', 'no_show')
  AND EXTRACT(YEAR FROM r.fecha_entrada) = EXTRACT(YEAR FROM CURRENT_DATE)
GROUP BY c.nombre, c.comision_pct
ORDER BY ingresos_netos DESC
LIMIT 1
```

---

## Pickup de reservas

Para "cuántas reservas entraron esta semana / este mes para fechas futuras" usar `created_at` de `reservas`.

**Preferido:**
```sql
SELECT
    COUNT(*) AS nuevas_reservas,
    SUM(total_hospedaje) AS valor_reservado
FROM reservas
WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
  AND fecha_entrada > CURRENT_DATE
  AND estado NOT IN ('cancelada', 'no_show')
```

---

## Lead time promedio

Para "con cuánta anticipación reservan" usar diferencia entre `created_at` y `fecha_entrada`.

**Preferido:**
```sql
SELECT
    ROUND(AVG(fecha_entrada - created_at::date), 0) AS lead_time_dias,
    MIN(fecha_entrada - created_at::date) AS minimo,
    MAX(fecha_entrada - created_at::date) AS maximo
FROM reservas
WHERE estado NOT IN ('cancelada', 'no_show')
  AND EXTRACT(YEAR FROM fecha_entrada) = EXTRACT(YEAR FROM CURRENT_DATE)
```

---

## Porcentajes sobre total

Para "participación de X sobre el total" usar subquery con `SUM` total en el denominador.

**Preferido:**
```sql
SELECT
    cv.nombre AS canal,
    SUM(r.total_hospedaje) AS ventas,
    ROUND(SUM(r.total_hospedaje) * 100.0 / NULLIF(SUM(SUM(r.total_hospedaje)) OVER (), 0), 1) AS pct
FROM reservas r
JOIN canales_venta c ON r.canal_id = c.id
WHERE r.estado != 'cancelada'
GROUP BY cv.nombre
ORDER BY ventas DESC
```
