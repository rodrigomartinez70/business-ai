# SQL Guidelines — Vertical HOTEL

Reglas específicas del negocio hotelero. Se suman a las guías genéricas.

---

## Aliases con sentido del negocio hotelero

| En vez de | Usar |
|---|---|
| `num_nights` | `noches` |
| `check_in` / `check_out` | `fecha_entrada` / `fecha_salida` |
| `booking` | `reserva` |
| `rate` | `tarifa` |
| `occupancy` | `ocupacion_pct` |
| `count` | `cantidad_reservas` / `cantidad_huespedes` (según contexto) |

Ingresos de hospedaje: `SUM(total_hospedaje)` de `reservas`. Excluir siempre
`estado IN ('cancelada', 'no_show')` en métricas de venta.

```sql
SELECT c.nombre AS canal,
       SUM(r.total_hospedaje) AS ingresos,
       COUNT(r.id)            AS cantidad_reservas,
       ROUND(SUM(r.total_hospedaje) / COUNT(r.id), 0) AS ingreso_promedio
FROM reservas r
JOIN canales_venta c ON r.canal_id = c.id
WHERE r.estado NOT IN ('cancelada', 'no_show')
GROUP BY c.nombre
ORDER BY ingresos DESC
```

---

## Ocupación, ADR y RevPAR

Usar el total de habitaciones activas como denominador.
- **Ocupación %** = noches vendidas / (habitaciones activas × días del período) × 100
- **ADR** = ingresos / noches vendidas
- **RevPAR** = ingresos / (habitaciones activas × días del período)

Las noches se atribuyen al mes de check-in. Usar siempre los días reales del mes
(`EXTRACT(DAY FROM (mes + INTERVAL '1 month') - mes)`), nunca 30 fijo.

```sql
WITH total_hab AS (SELECT COUNT(*) AS total FROM habitaciones WHERE activa = true),
ventas AS (
    SELECT DATE_TRUNC('month', fecha_entrada)::date AS mes,
           SUM(noches) AS noches_vendidas, SUM(total_hospedaje) AS ingresos
    FROM reservas
    WHERE EXTRACT(YEAR FROM fecha_entrada) = EXTRACT(YEAR FROM CURRENT_DATE)
      AND estado NOT IN ('cancelada', 'no_show')
    GROUP BY DATE_TRUNC('month', fecha_entrada)
)
SELECT v.mes,
       ROUND(v.noches_vendidas::numeric
             / (t.total * EXTRACT(DAY FROM (v.mes + INTERVAL '1 month') - v.mes)) * 100, 1) AS ocupacion_pct,
       ROUND(v.ingresos / NULLIF(v.noches_vendidas, 0), 0) AS adr,
       ROUND(v.ingresos / (t.total * EXTRACT(DAY FROM (v.mes + INTERVAL '1 month') - v.mes)), 0) AS revpar
FROM ventas v CROSS JOIN total_hab t
ORDER BY v.mes
```

---

## Margen neto por canal

Descontar la comisión OTA con `comision_pct` de `canales_venta`.
Alias `ingresos_netos` (dinero), `margen_promedio` (por reserva). Para "¿qué canal
deja mejor margen?" agregar `LIMIT 1`.

```sql
SELECT c.nombre AS canal,
       SUM(r.total_hospedaje) AS ingresos_brutos,
       c.comision_pct,
       ROUND(SUM(r.total_hospedaje) * (1 - c.comision_pct / 100), 0) AS ingresos_netos
FROM reservas r JOIN canales_venta c ON r.canal_id = c.id
WHERE r.estado NOT IN ('cancelada', 'no_show')
GROUP BY c.nombre, c.comision_pct
ORDER BY ingresos_netos DESC
```

---

## Pickup de reservas y lead time

- **Pickup:** reservas creadas en un período para fechas futuras → usar `created_at`.
- **Lead time:** anticipación = `fecha_entrada - created_at::date`.

```sql
-- Pickup últimos 7 días
SELECT COUNT(*) AS nuevas_reservas, SUM(total_hospedaje) AS valor_reservado
FROM reservas
WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
  AND fecha_entrada > CURRENT_DATE AND estado NOT IN ('cancelada', 'no_show')
```
