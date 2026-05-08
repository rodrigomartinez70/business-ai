# SQL Guidelines — Patrones preferidos

Estas guías se inyectan en el prompt de Claude para mejorar la calidad del SQL generado.
Agregar nuevos patrones en la misma estructura.

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
