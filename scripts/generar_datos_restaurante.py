#!/usr/bin/env python3
"""
Generador de datos de prueba — vertical RESTAURANTE.

Genera pedidos/detalle/pagos, gastos mensuales, documentos tributarios (espejo
de gastos afectos) y cartola bancaria (con excepciones realistas) en el schema
del tenant indicado. Crea los datos maestros (canales, mesas, productos) si el
schema está vacío.

Uso:
  python scripts/generar_datos_restaurante.py --tenant-id restaurante_xyz --ayer
  python scripts/generar_datos_restaurante.py --tenant-id restaurante_xyz \\
      --desde 2026-05-01 --hasta 2026-05-31
"""

import argparse
import asyncio
import os
import random
import sys
from datetime import date, timedelta

import asyncpg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("INGEST_DATABASE_URL") or os.environ.get("DATABASE_URL")

CANALES = [("Salón", 0), ("Delivery", 0), ("Takeaway", 0), ("Rappi", 25), ("PedidosYa", 22)]
CANAL_PESOS = [55, 18, 12, 8, 7]
CATS = ["Entradas", "Platos de fondo", "Bebidas", "Postres"]
PRODUCTOS = [
    ("Empanada de pino", "Entradas", 3500, 1200),
    ("Tabla para compartir", "Entradas", 14000, 6000),
    ("Lomo a lo pobre", "Platos de fondo", 12900, 5200),
    ("Salmón grillado", "Platos de fondo", 13900, 6500),
    ("Pasta del día", "Platos de fondo", 9900, 3200),
    ("Hamburguesa de la casa", "Platos de fondo", 9500, 3800),
    ("Pisco sour", "Bebidas", 4900, 1400),
    ("Copa de vino", "Bebidas", 5500, 2000),
    ("Bebida/jugo", "Bebidas", 2500, 800),
    ("Cerveza artesanal", "Bebidas", 4500, 1800),
    ("Tiramisú", "Postres", 5500, 1900),
    ("Cheesecake", "Postres", 5200, 1800),
]
GASTOS_MENSUALES = [
    ("Personal",            "Personal",   2200000),
    ("Honorarios contador", "Honorarios",  250000),
    ("Arriendo local",      "Arriendo",   1500000),
    ("Insumos cocina",      "Insumos",    1800000),
    ("Electricidad",        "Servicios",   280000),
    ("Gas",                 "Servicios",   180000),
    ("Internet y telefonía","Servicios",    65000),
    ("Aseo y sanitización", "Servicios",   120000),
]
NO_AFECTO = ("Personal", "Honorarios")
METODOS = ["efectivo", "tarjeta", "transferencia"]
CARGOS_BANCARIOS = [("Comision mantencion cuenta", 8990, 12500),
                    ("Comision tarjetas/POS", 25000, 90000),
                    ("Impuesto al giro", 2000, 9000)]


async def _asegurar_maestros(conn):
    if await conn.fetchval("SELECT COUNT(*) FROM productos") > 0:
        return
    canal_ids = {}
    for nombre, com in CANALES:
        canal_ids[nombre] = await conn.fetchval(
            "INSERT INTO canales_venta (nombre, comision_pct) VALUES ($1,$2) RETURNING id", nombre, com)
    for i in range(1, 13):
        await conn.execute("INSERT INTO mesas (numero, capacidad, sector) VALUES ($1,$2,$3)",
                           str(i), random.choice([2, 4, 6]), random.choice(["Salón", "Terraza"]))
    cat_ids = {c: await conn.fetchval("INSERT INTO categorias_menu (nombre) VALUES ($1) RETURNING id", c)
               for c in CATS}
    for nombre, cat, precio, costo in PRODUCTOS:
        await conn.execute("INSERT INTO productos (categoria_id, nombre, precio, costo) VALUES ($1,$2,$3,$4)",
                           cat_ids[cat], nombre, precio, costo)
    print("  Maestros creados (canales, mesas, productos)")


async def _generar_pedidos(conn, desde, hasta):
    canal_ids = {r["nombre"]: r["id"] for r in await conn.fetch("SELECT id, nombre FROM canales_venta")}
    canales   = [c[0] for c in CANALES if c[0] in canal_ids]
    pesos     = CANAL_PESOS[:len(canales)]
    mesa_ids  = [r["id"] for r in await conn.fetch("SELECT id FROM mesas")]
    prods     = [(r["id"], float(r["precio"]), float(r["costo"]))
                 for r in await conn.fetch("SELECT id, precio, costo FROM productos WHERE activo")]
    n = 0
    dia = desde
    while dia <= hasta:
        ya = await conn.fetchval("SELECT COUNT(*) FROM pedidos WHERE fecha = $1", dia)
        if not ya:
            base = 28 if dia.weekday() in (4, 5) else 16
            for _ in range(base + random.randint(-4, 6)):
                canal = random.choices(canales, weights=pesos)[0]
                mesa = random.choice(mesa_ids) if canal == "Salón" and mesa_ids else None
                comensales = random.randint(1, 4) if canal == "Salón" else 1
                pid = await conn.fetchval(
                    "INSERT INTO pedidos (mesa_id, canal_id, fecha, comensales, estado) "
                    "VALUES ($1,$2,$3,$4,'pagado') RETURNING id", mesa, canal_ids[canal], dia, comensales)
                total = 0
                for _ in range(random.randint(1, 5)):
                    prod, precio, costo = random.choice(prods)
                    cant = random.randint(1, 2)
                    await conn.execute(
                        "INSERT INTO detalle_pedido (pedido_id, producto_id, cantidad, precio_unitario, costo_unitario) "
                        "VALUES ($1,$2,$3,$4,$5)", pid, prod, cant, precio, costo)
                    total += precio * cant
                propina = round(total * 0.10) if canal == "Salón" and random.random() < 0.5 else 0
                if propina:
                    await conn.execute("UPDATE pedidos SET propina=$1 WHERE id=$2", propina, pid)
                await conn.execute(
                    "INSERT INTO pagos (pedido_id, fecha, monto, metodo, propina) VALUES ($1,$2,$3,$4,$5)",
                    pid, dia, total, random.choice(METODOS), propina)
                n += 1
        dia += timedelta(days=1)
    print(f"  Pedidos generados: {n}")


async def _generar_gastos_y_contable(conn, desde, hasta):
    cats = {r["nombre"]: r["id"] for r in await conn.fetch("SELECT id, nombre FROM categorias_gasto")}

    meses = set()
    d = desde
    while d <= hasta:
        meses.add((d.year, d.month)); d = (d.replace(day=1) + timedelta(days=32)).replace(day=1)

    g_n = 0
    for año, mes in sorted(meses):
        if await conn.fetchval("SELECT COUNT(*) FROM gastos WHERE EXTRACT(YEAR FROM fecha)=$1 AND EXTRACT(MONTH FROM fecha)=$2", año, mes):
            continue
        for desc, cat, monto in GASTOS_MENSUALES:
            if cat not in cats:
                cats[cat] = await conn.fetchval("INSERT INTO categorias_gasto (nombre) VALUES ($1) RETURNING id", cat)
            comp = None if random.random() < 0.15 else f"FAC-{random.randint(10000,99999)}"
            m = round(monto * random.uniform(0.95, 1.06))
            await conn.execute("INSERT INTO gastos (categoria_id, fecha, descripcion, monto, proveedor, comprobante) VALUES ($1,$2,$3,$4,$5,$6)",
                               cats[cat], date(año, mes, 5), desc, m, desc, comp)
            g_n += 1
    print(f"  Gastos generados: {g_n}")

    # Documentos = espejo de gastos afectos del mes
    d_n = 0
    for año, mes in sorted(meses):
        if await conn.fetchval("SELECT COUNT(*) FROM documentos_tributarios WHERE EXTRACT(YEAR FROM fecha)=$1 AND EXTRACT(MONTH FROM fecha)=$2", año, mes):
            continue
        afectos = await conn.fetch("""
            SELECT g.fecha, g.monto, g.proveedor, cg.nombre AS categoria
            FROM gastos g LEFT JOIN categorias_gasto cg ON cg.id=g.categoria_id
            WHERE EXTRACT(YEAR FROM g.fecha)=$1 AND EXTRACT(MONTH FROM g.fecha)=$2
              AND COALESCE(cg.nombre,'') <> ALL($3::text[])
        """, año, mes, list(NO_AFECTO))
        for g in afectos:
            neto = float(g["monto"]); iva = round(neto * 0.19)
            estado = "registrado" if random.random() < 0.85 else "pendiente_revision"
            await conn.execute("INSERT INTO documentos_tributarios (fecha,tipo,numero_documento,proveedor,monto_neto,monto_iva,monto_total,estado,categoria_gasto) VALUES ($1,'factura',$2,$3,$4,$5,$6,$7,$8)",
                               g["fecha"], f"F-{random.randint(1000,9999)}", g["proveedor"] or g["categoria"], neto, iva, neto+iva, estado, g["categoria"])
            d_n += 1
    print(f"  Documentos tributarios: {d_n}")


async def _generar_cartola(conn, desde, hasta):
    if await conn.fetchval("SELECT COUNT(*) FROM movimientos_bancarios WHERE fecha BETWEEN $1 AND $2", desde, hasta):
        print("  Movimientos bancarios: 0 (ya existen)"); return
    pagos = await conn.fetch("SELECT fecha, monto FROM pagos WHERE fecha BETWEEN $1 AND $2", desde, hasta)
    gastos = await conn.fetch("SELECT fecha, monto FROM gastos WHERE fecha BETWEEN $1 AND $2", desde, hasta)
    n = 0
    for p in pagos:
        r = random.random()
        if r < 0.90:
            await conn.execute("INSERT INTO movimientos_bancarios (fecha, glosa, monto, referencia) VALUES ($1,$2,$3,$4)",
                               p["fecha"], random.choice(["Abono Transbank", "Abono Getnet", "Transferencia"]), float(p["monto"]), f"AB-{random.randint(10000,99999)}"); n += 1
        elif r < 0.96:
            neto = round(float(p["monto"]) * (1 - random.uniform(0.018, 0.035)))
            await conn.execute("INSERT INTO movimientos_bancarios (fecha, glosa, monto, referencia) VALUES ($1,$2,$3,$4)",
                               p["fecha"], "Abono POS neto comision", neto, f"POSN-{random.randint(10000,99999)}"); n += 1
    for g in gastos:
        if random.random() < 0.92:
            await conn.execute("INSERT INTO movimientos_bancarios (fecha, glosa, monto, referencia) VALUES ($1,$2,$3,$4)",
                               g["fecha"], "Pago proveedor/servicio", -float(g["monto"]), f"PG-{random.randint(10000,99999)}"); n += 1
    for _ in range(int(round(n * 0.04))):
        glosa, lo, hi = random.choice(CARGOS_BANCARIOS)
        await conn.execute("INSERT INTO movimientos_bancarios (fecha, glosa, monto, referencia) VALUES ($1,$2,$3,$4)",
                           desde + timedelta(days=random.randint(0, max(0, (hasta - desde).days))), glosa, -random.randint(lo, hi), f"COM-{random.randint(1000,9999)}"); n += 1
    print(f"  Movimientos bancarios: {n}")


async def main():
    parser = argparse.ArgumentParser(description="Generador de datos de restaurante")
    parser.add_argument("--tenant-id", required=True, help="Schema del tenant (ej. restaurante_xyz)")
    parser.add_argument("--desde", type=date.fromisoformat)
    parser.add_argument("--hasta", type=date.fromisoformat)
    parser.add_argument("--ayer", action="store_true")
    args = parser.parse_args()

    if args.ayer:
        desde = hasta = date.today() - timedelta(days=1)
    elif args.desde and args.hasta:
        desde, hasta = args.desde, args.hasta
    else:
        parser.print_help(); sys.exit(1)

    if not DATABASE_URL:
        print("ERROR: DATABASE_URL no configurado", file=sys.stderr); sys.exit(1)

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(f'SET search_path = "{args.tenant_id}", public')
        print(f"\nGenerando datos de restaurante ({args.tenant_id}): {desde} → {hasta}")
        await _asegurar_maestros(conn)
        await _generar_pedidos(conn, desde, hasta)
        await _generar_gastos_y_contable(conn, desde, hasta)
        await _generar_cartola(conn, desde, hasta)
        print("\n✓ Completado\n")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
