# SQL Guidelines — Vertical RESTAURANTE

Reglas específicas del negocio gastronómico. Se suman a las guías genéricas.

---

## Aliases con sentido del negocio gastronómico

| En vez de | Usar |
|---|---|
| `order` | `pedido` |
| `table` | `mesa` |
| `item` / `dish` | `producto` |
| `avg_ticket` | `ticket_promedio` |
| `guests` / `covers` | `comensales` |
| `count` | `cantidad_pedidos` (según contexto) |

Las ventas se calculan sobre las **líneas de pedido** (`detalle_pedido.total`) de
pedidos pagados. Excluir siempre los pedidos `estado IN ('anulado')` (y considerar
solo `'pagado'` para venta efectiva).

```sql
SELECT c.nombre AS canal,
       SUM(d.total)            AS ventas,
       COUNT(DISTINCT p.id)    AS cantidad_pedidos,
       ROUND(SUM(d.total) / NULLIF(COUNT(DISTINCT p.id), 0), 0) AS ticket_promedio
FROM pedidos p
JOIN detalle_pedido d ON d.pedido_id = p.id
LEFT JOIN canales_venta c ON c.id = p.canal_id
WHERE p.estado = 'pagado'
GROUP BY c.nombre
ORDER BY ventas DESC
```

---

## Ticket promedio y comensales

- **Ticket promedio** = ventas / cantidad de pedidos pagados.
- **Venta por comensal** = ventas / `SUM(comensales)`.
- Para mix por canal (salón/delivery/apps) agrupar por `canales_venta.nombre`.

```sql
SELECT ROUND(SUM(d.total) / NULLIF(COUNT(DISTINCT p.id), 0), 0)  AS ticket_promedio,
       ROUND(SUM(d.total) / NULLIF(SUM(p.comensales), 0), 0)     AS venta_por_comensal
FROM pedidos p JOIN detalle_pedido d ON d.pedido_id = p.id
WHERE p.estado = 'pagado' AND p.fecha >= CURRENT_DATE - INTERVAL '7 days'
```

---

## Food cost y margen

El costo del producto está en `detalle_pedido.costo_total`; el margen en
`detalle_pedido.margen`.
- **Food cost %** = costo / ventas × 100
- **Margen bruto %** = margen / ventas × 100

```sql
SELECT ROUND(SUM(d.costo_total) * 100.0 / NULLIF(SUM(d.total), 0), 1) AS food_cost_pct,
       ROUND(SUM(d.margen)      * 100.0 / NULLIF(SUM(d.total), 0), 1) AS margen_bruto_pct
FROM pedidos p JOIN detalle_pedido d ON d.pedido_id = p.id
WHERE p.estado = 'pagado'
```

---

## Productos más vendidos / más rentables

"Top productos" por ventas o por margen → `GROUP BY producto ... ORDER BY ... DESC LIMIT N`.

```sql
SELECT pr.nombre AS producto,
       SUM(d.cantidad) AS unidades,
       SUM(d.total)    AS ventas,
       SUM(d.margen)   AS margen
FROM detalle_pedido d
JOIN pedidos p ON p.id = d.pedido_id
LEFT JOIN productos pr ON pr.id = d.producto_id
WHERE p.estado = 'pagado'
GROUP BY pr.nombre
ORDER BY ventas DESC
LIMIT 10
```

---

## Comisiones de apps de delivery

Las apps (Rappi, PedidosYa, Uber Eats) tienen `comision_pct` en `canales_venta`.
Para venta neta de comisión: `SUM(d.total) * (1 - c.comision_pct / 100)`.
