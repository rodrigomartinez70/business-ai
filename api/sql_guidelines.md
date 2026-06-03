# SQL Guidelines — Patrones genéricos (todos los verticales)

Estas guías se inyectan en el prompt de Claude para mejorar la calidad del SQL.
Son **agnósticas al rubro**. Las reglas específicas de cada negocio (hotel,
restaurante, …) están en `src/verticals/<vertical>/sql_guidelines.md`.

Los ejemplos usan `pagos`/`gastos` (tablas presentes en todos los verticales) a
modo ilustrativo; aplicá el mismo patrón a las tablas reales del schema.

---

## Nomenclatura

Usar siempre nombres en **español** que el dueño del negocio reconozca. Nunca
jerga de retail ni términos ambiguos en inglés.

| En vez de | Usar |
|---|---|
| `avg_revenue` / `revenue` | `ingreso_promedio` / `ingresos` |
| `count` | `cantidad` (con contexto: `cantidad_pedidos`, `cantidad_reservas`) |
| `pct` | `porcentaje` |
| `rate` | `tasa` / `tarifa` |

---

## Comparaciones año contra año (YoY) — REGLA CRÍTICA

**NUNCA comparar el año completo anterior contra el año en curso parcial.**
Si el año actual es 2026 y hoy es 29 de mayo, hay datos solo hasta mayo 2026.
Comparar todo 2025 (12 meses) vs 2026 hasta mayo (5 meses) es siempre incorrecto.

**Regla:** cuando el rango incluye el año actual, recortar AMBOS años al mismo
rango (desde el 1 de enero hasta `CURRENT_DATE` y su equivalente del año anterior).

```sql
WITH corte AS (
    SELECT
        DATE_TRUNC('year', CURRENT_DATE)                     AS inicio_actual,
        CURRENT_DATE                                          AS fin_actual,
        DATE_TRUNC('year', CURRENT_DATE) - INTERVAL '1 year' AS inicio_anterior,
        CURRENT_DATE                  - INTERVAL '1 year'    AS fin_anterior
),
actual AS (
    SELECT COALESCE(SUM(monto), 0) AS total FROM pagos, corte
    WHERE estado = 'pagado' AND fecha BETWEEN corte.inicio_actual AND corte.fin_actual
),
anterior AS (
    SELECT COALESCE(SUM(monto), 0) AS total FROM pagos, corte
    WHERE estado = 'pagado' AND fecha BETWEEN corte.inicio_anterior AND corte.fin_anterior
)
SELECT a.total AS año_anterior, b.total AS año_actual,
       b.total - a.total AS variacion,
       ROUND((b.total - a.total) * 100.0 / NULLIF(a.total, 0), 1) AS crecimiento_pct
FROM anterior a, actual b
```

**Lo mismo aplica a meses:** "mayo 2026 vs mayo 2025" → usar los días transcurridos
de mayo en ambos años.

---

## Consultas multi-período

Cuando se piden varios años/meses, usar **una sola query** con `GROUP BY` período.
Si uno de los períodos es el actual, incluir `AND fecha <= CURRENT_DATE` para no
comparar contra meses futuros sin datos.

```sql
SELECT EXTRACT(YEAR FROM fecha) AS año, SUM(monto) AS total
FROM pagos
WHERE EXTRACT(YEAR FROM fecha) IN (2025, 2026) AND fecha <= CURRENT_DATE
  AND estado = 'pagado'
GROUP BY EXTRACT(YEAR FROM fecha)
ORDER BY año
```

---

## Períodos cerrados

Para comparar dos períodos **ambos completamente cerrados** (ej. abril 2025 vs
abril 2026), usar CTEs con fechas explícitas (rangos fijos están bien aquí).

```sql
WITH a AS (SELECT SUM(monto) AS total FROM pagos
           WHERE fecha BETWEEN '2025-04-01' AND '2025-04-30' AND estado='pagado'),
     b AS (SELECT SUM(monto) AS total FROM pagos
           WHERE fecha BETWEEN '2026-04-01' AND '2026-04-30' AND estado='pagado')
SELECT a.total, b.total, b.total - a.total AS variacion,
       ROUND((b.total - a.total) * 100.0 / NULLIF(a.total, 0), 1) AS variacion_pct
FROM a, b
```

Si uno de los períodos incluye el año/mes actual, ver "Comparaciones YoY".

---

## Rankings con límite

Para "top N" o "los más…" usar siempre `ORDER BY ... DESC LIMIT N`.
Para "el mejor/el peor" agregar `LIMIT 1` al `ORDER BY`.

---

## Porcentajes sobre total

Para "participación de X sobre el total" usar window function en el denominador.

```sql
SELECT categoria,
       SUM(monto) AS total,
       ROUND(SUM(monto) * 100.0 / NULLIF(SUM(SUM(monto)) OVER (), 0), 1) AS porcentaje
FROM gastos
GROUP BY categoria
ORDER BY total DESC
```

---

## Nombres de meses en español

`TO_CHAR` devuelve meses en inglés. Usar este CASE:

```sql
CASE EXTRACT(MONTH FROM m)::int
    WHEN 1 THEN 'Ene' WHEN 2 THEN 'Feb' WHEN 3 THEN 'Mar'
    WHEN 4 THEN 'Abr' WHEN 5 THEN 'May' WHEN 6 THEN 'Jun'
    WHEN 7 THEN 'Jul' WHEN 8 THEN 'Ago' WHEN 9 THEN 'Sep'
    WHEN 10 THEN 'Oct' WHEN 11 THEN 'Nov' WHEN 12 THEN 'Dic'
END || ' ' || EXTRACT(YEAR FROM m)::int AS mes
```

---

## Anti-cartesiano (recordatorio)

Cuando combines agregaciones de **tablas distintas con relación 1-a-muchos**, usá
CTEs/subqueries independientes, NUNCA un JOIN directo entre ellas (multiplica los
montos). Si todo está en una sola tabla, no hagas JOIN.

```sql
WITH ingresos AS (SELECT SUM(monto) AS total FROM pagos WHERE estado='pagado'),
     egresos  AS (SELECT SUM(monto) AS total FROM gastos)
SELECT i.total AS ingresos, e.total AS egresos, i.total - e.total AS resultado
FROM ingresos i, egresos e
```
