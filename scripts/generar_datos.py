#!/usr/bin/env python3
"""
Generador de datos de prueba — Business AI Platform
Genera reservas, pagos, consumos y gastos con patrones realistas.

Uso:
  python scripts/generar_datos.py --desde 2025-01-01 --hasta 2025-12-31
  python scripts/generar_datos.py --ayer
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

# ─── Patrones de negocio ──────────────────────────────────────────────────────
# (nombre, peso_dist, lead_time_días, tasa_cancelación, tasa_noshow)
CANALES_CONFIG = [
    ("Directo",      0.40, (1,  14), 0.05, 0.02),
    ("Booking.com",  0.25, (7,  45), 0.15, 0.04),
    ("Airbnb",       0.20, (7,  30), 0.10, 0.03),
    ("Agencia",      0.10, (14, 60), 0.08, 0.02),
    ("Despegar",     0.05, (3,  21), 0.12, 0.05),
]

NOCHES_POR_TIPO = {
    "Suite":   (3, 6),
    "Doble":   (2, 5),
    "Simple":  (1, 3),
}

ITEMS_FRIGOBAR = [
    ("Agua mineral",   1500,  800),
    ("Cerveza",        2500, 1200),
    ("Gaseosa",        2000,  900),
    ("Snack",          3000, 1500),
    ("Jugo",           2200, 1000),
    ("Vino miniatura", 5000, 2500),
]

SERVICIOS = [
    ("Lavandería",      8000, 4000),
    ("Estacionamiento", 6000, 2000),
    ("Traslado",       15000, 8000),
    ("Desayuno extra",  5000, 2000),
]

GASTOS_FIJOS = [
    ("Personal",            "Personal",    800000),
    ("Electricidad",        "Servicios",   120000),
    ("Agua",                "Servicios",    45000),
    ("Gas",                 "Servicios",    35000),
    ("Internet",            "Servicios",    25000),
    ("Telefonía",           "Servicios",    35000),
    ("Televisión por cable","Servicios",    22000),
    ("Seguridad y alarmas", "Servicios",   160000),
]

GASTOS_VARIABLES = [
    ("Suministros limpieza",          "Suministros",    80000, 120000),
    ("Mantenimiento general",         "Mantenimiento",  50000, 200000),
    ("Mantenimiento aire acond. (A/C)","Mantenimiento", 60000, 150000),
    ("Amenities",                     "Suministros",    40000,  80000),
    ("Lavandería",                    "Servicios",      60000, 130000),
    ("Artículos de aseo",             "Suministros",    30000,  90000),
    ("Gastos generales",              "Administración",  20000,  70000),
]

# Categorías de gasto NO afectas a IVA (no generan crédito): remuneraciones.
NO_AFECTO_IVA = {"Personal"}

# Cargos bancarios que no tienen respaldo en los libros (excepciones típicas)
CARGOS_BANCARIOS = [
    ("Comision mantencion cuenta",        8990,  12500),
    ("Comision por transferencias",       1500,   4500),
    ("Impuesto al giro / timbres",        2000,   9000),
    ("Comision administracion tarjeta",  15000,  45000),
    ("PAC servicios no contabilizado",   20000,  90000),
]

# Abonos sin contraparte en los libros
ABONOS_SIN_RESPALDO = [
    "Abono no identificado",
    "Deposito en efectivo por identificar",
    "Reverso/devolucion bancaria",
]

NOMBRES = [
    ("Carlos",    "García"),    ("María",     "López"),
    ("Juan",      "Martínez"),  ("Ana",       "González"),
    ("Pedro",     "Rodríguez"), ("Laura",     "Sánchez"),
    ("Diego",     "Pérez"),     ("Valentina", "Torres"),
    ("Andrés",    "Ramírez"),   ("Sofía",     "Flores"),
    ("Roberto",   "Díaz"),      ("Isabella",  "Morales"),
    ("Miguel",    "Jiménez"),   ("Camila",    "Castro"),
    ("Luis",      "Vargas"),    ("Fernanda",  "Herrera"),
    ("Pablo",     "Mendoza"),   ("Daniela",   "Núñez"),
    ("Sebastian", "Ramos"),     ("Catalina",  "Moreno"),
    ("James",     "Wilson"),    ("Emma",      "Johnson"),
    ("Thomas",    "Brown"),     ("Sophie",    "Martin"),
    ("Lucas",     "Silva"),     ("Valentina", "Costa"),
    ("Felipe",    "Oliveira"),  ("Mariana",   "Santos"),
    ("Gabriel",   "Lima"),      ("Carolina",  "Alves"),
    ("Rodrigo",   "Gutiérrez"), ("Patricia",  "Romero"),
    ("Eduardo",   "Navarro"),   ("Alejandra", "Medina"),
    ("Francisco", "Reyes"),     ("Natalia",   "Cruz"),
]

TIPOS_DOC     = ["DNI", "Pasaporte", "RUT"]
NACIONALIDADES = ["Argentina", "Chilena", "Uruguaya", "Brasileña",
                  "Colombiana", "Española", "Estadounidense", "Mexicana"]
METODOS_PAGO  = ["efectivo", "tarjeta", "transferencia"]


# ─── Lógica de ocupación ──────────────────────────────────────────────────────

def ocupacion_objetivo(d: date) -> float:
    mes, dia = d.month, d.day

    if mes in (12, 1, 2, 3):
        base = random.uniform(0.72, 0.87)
    elif mes == 9 and 8 <= dia <= 21:          # semanas 2-3 de septiembre
        base = random.uniform(0.72, 0.87)
    elif mes in (6, 7, 8, 10):
        base = random.uniform(0.48, 0.65)
    else:                                       # abr, may, nov, sep resto
        base = random.uniform(0.32, 0.48)

    if d.weekday() in (4, 5):                  # viernes y sábado +12 %
        base = min(0.95, base + 0.12)

    return base


# ─── Helpers ─────────────────────────────────────────────────────────────────

def elegir_canal(canales_db: dict) -> tuple:
    nombres = [c[0] for c in CANALES_CONFIG]
    pesos   = [c[1] for c in CANALES_CONFIG]
    nombre  = random.choices(nombres, weights=pesos)[0]
    cfg     = next(c for c in CANALES_CONFIG if c[0] == nombre)
    canal_id = canales_db.get(nombre)
    return canal_id, cfg[2], cfg[3], cfg[4]   # id, lead_range, cancel, noshow


def redondear_tarifa(tarifa: float) -> int:
    return round(tarifa / 1000) * 1000


def _comprobante() -> str | None:
    """Nº de comprobante para ~85% de los gastos; el resto queda sin respaldo."""
    if random.random() < 0.85:
        return f"FAC-{random.randint(10000, 99999)}"
    return None


# ─── Generación principal ─────────────────────────────────────────────────────

async def generar_periodo(conn, desde: date, hasta: date):
    hoy = date.today()

    # Apuntar al schema del tenant (multi-tenant)
    await conn.execute("SET search_path = hotel_mbi, public")

    # ── Datos maestros ──────────────────────────────────────────────────────
    habitaciones = await conn.fetch(
        "SELECT id, numero, tipo, tarifa_base FROM habitaciones WHERE activa = true"
    )
    canales_rows = await conn.fetch("SELECT id, nombre FROM canales_venta WHERE activo = true")
    canales_db   = {r["nombre"]: r["id"] for r in canales_rows}
    categorias   = await conn.fetch("SELECT id, nombre FROM categorias_gasto")
    cats_db      = {r["nombre"]: r["id"] for r in categorias}

    # ── Días que ya tienen datos (por created_at) ───────────────────────────
    existing = await conn.fetch(
        "SELECT DISTINCT DATE(created_at) AS dia FROM reservas "
        "WHERE created_at::date BETWEEN $1 AND $2",
        desde, hasta,
    )
    dias_con_datos = {r["dia"] for r in existing}

    # ── Calendario de ocupación (evita doble-booking) ───────────────────────
    reservas_prev = await conn.fetch(
        """SELECT habitacion_id, fecha_entrada, fecha_salida FROM reservas
           WHERE estado NOT IN ('cancelada','no_show')
             AND fecha_salida > $1 AND fecha_entrada < $2""",
        desde, hasta + timedelta(days=90),
    )
    ocupado: dict[int, set] = {h["id"]: set() for h in habitaciones}
    for r in reservas_prev:
        d = r["fecha_entrada"]
        while d < r["fecha_salida"]:
            if r["habitacion_id"] in ocupado:
                ocupado[r["habitacion_id"]].add(d)
            d += timedelta(days=1)

    # ── Pool de huéspedes ───────────────────────────────────────────────────
    huesped_ids = [r["id"] for r in await conn.fetch("SELECT id FROM huespedes")]
    faltan = max(0, 60 - len(huesped_ids))
    for nombre, apellido in random.sample(NOMBRES, min(faltan, len(NOMBRES))):
        hid = await conn.fetchval(
            """INSERT INTO huespedes (nombre, apellido, tipo_documento, documento, nacionalidad)
               VALUES ($1,$2,$3,$4,$5) RETURNING id""",
            nombre, apellido,
            random.choice(TIPOS_DOC),
            str(random.randint(10_000_000, 99_999_999)),
            random.choice(NACIONALIDADES),
        )
        huesped_ids.append(hid)

    # ── Generar reservas día a día ──────────────────────────────────────────
    reservas_nuevas: list[dict] = []
    fecha = desde

    while fecha <= hasta:
        if fecha not in dias_con_datos:
            target   = round(len(habitaciones) * ocupacion_objetivo(fecha))
            actuales = sum(1 for h in habitaciones if fecha in ocupado[h["id"]])
            por_gen  = max(0, target - actuales)

            disponibles = [h for h in habitaciones if fecha not in ocupado[h["id"]]]
            random.shuffle(disponibles)

            for hab in disponibles[:por_gen]:
                canal_id, lead_range, t_cancel, t_noshow = elegir_canal(canales_db)
                if not canal_id:
                    continue

                noches       = random.randint(*NOCHES_POR_TIPO.get(hab["tipo"], (2, 4)))
                fecha_salida = fecha + timedelta(days=noches)
                lead_time    = random.randint(*lead_range)
                created_at   = fecha - timedelta(days=lead_time)

                if random.random() < t_cancel:
                    estado = "cancelada"
                elif random.random() < t_noshow:
                    estado = "no_show"
                elif fecha_salida <= hoy:
                    estado = "checkout"
                elif fecha <= hoy:
                    estado = "checkin"
                else:
                    estado = "confirmada"

                tarifa = redondear_tarifa(float(hab["tarifa_base"]) * random.uniform(0.85, 1.15))

                rid = await conn.fetchval(
                    """INSERT INTO reservas
                       (habitacion_id, huesped_id, canal_id, fecha_entrada, fecha_salida,
                        tarifa_noche, estado, created_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id""",
                    hab["id"], random.choice(huesped_ids), canal_id,
                    fecha, fecha_salida, tarifa, estado, created_at,
                )

                reservas_nuevas.append({
                    "id": rid, "estado": estado,
                    "fecha_entrada": fecha, "fecha_salida": fecha_salida,
                    "created_at": created_at, "tarifa": tarifa, "noches": noches,
                })

                if estado not in ("cancelada", "no_show"):
                    d = fecha
                    while d < fecha_salida:
                        ocupado[hab["id"]].add(d)
                        d += timedelta(days=1)

        fecha += timedelta(days=1)

    print(f"  Reservas generadas:  {len(reservas_nuevas)}")

    # ── Pagos ───────────────────────────────────────────────────────────────
    pagos_n = 0
    for r in reservas_nuevas:
        if r["estado"] in ("cancelada", "no_show"):
            continue
        total    = r["tarifa"] * r["noches"]
        anticipo = redondear_tarifa(total * 0.30)
        saldo    = total - anticipo

        await conn.execute(
            """INSERT INTO pagos (reserva_id, fecha, monto, metodo, concepto, estado)
               VALUES ($1,$2,$3,$4,'anticipo','pagado')""",
            r["id"], r["created_at"], anticipo, random.choice(METODOS_PAGO),
        )
        if r["estado"] == "checkout":
            await conn.execute(
                """INSERT INTO pagos (reserva_id, fecha, monto, metodo, concepto, estado)
                   VALUES ($1,$2,$3,$4,'hospedaje','pagado')""",
                r["id"], r["fecha_salida"], saldo, random.choice(METODOS_PAGO),
            )
        pagos_n += 1

    print(f"  Pagos generados:     {pagos_n}")

    # ── Frigobar y servicios ────────────────────────────────────────────────
    fb_n = svc_n = 0
    for r in reservas_nuevas:
        if r["estado"] != "checkout":
            continue

        for noche in range(r["noches"]):
            if random.random() < 0.55:
                desc, precio, costo = random.choice(ITEMS_FRIGOBAR)
                cantidad = random.randint(1, 3)
                await conn.execute(
                    """INSERT INTO consumos_frigobar
                       (reserva_id, fecha, descripcion, cantidad, precio_unitario, costo_unitario)
                       VALUES ($1,$2,$3,$4,$5,$6)""",
                    r["id"], r["fecha_entrada"] + timedelta(days=noche),
                    desc, cantidad, precio, costo,
                )
                fb_n += 1

        if random.random() < 0.35:
            svc, precio, costo = random.choice(SERVICIOS)
            await conn.execute(
                """INSERT INTO consumos_servicios
                   (reserva_id, fecha, servicio, cantidad, precio_unitario, costo_unitario)
                   VALUES ($1,$2,$3,1,$4,$5)""",
                r["id"], r["fecha_entrada"] + timedelta(days=1), svc, precio, costo,
            )
            svc_n += 1

    print(f"  Frigobar: {fb_n}, Servicios: {svc_n}")

    # ── Gastos mensuales ────────────────────────────────────────────────────
    meses: set[tuple] = set()
    d = desde
    while d <= hasta:
        meses.add((d.year, d.month))
        d += timedelta(days=32)
        d = d.replace(day=1)

    gastos_n = 0
    for año, mes in sorted(meses):
        existe = await conn.fetchval(
            "SELECT COUNT(*) FROM gastos "
            "WHERE EXTRACT(YEAR FROM fecha)=$1 AND EXTRACT(MONTH FROM fecha)=$2",
            año, mes,
        )
        if existe:
            continue

        for concepto, cat, monto_base in GASTOS_FIJOS:
            monto = redondear_tarifa(monto_base * random.uniform(0.95, 1.05))
            await conn.execute(
                "INSERT INTO gastos (categoria_id, fecha, descripcion, monto, proveedor, comprobante) "
                "VALUES ($1,$2,$3,$4,$5,$6)",
                cats_db.get(cat), date(año, mes, 5), concepto, monto, concepto,
                _comprobante(),
            )
            gastos_n += 1

        for concepto, cat, mn, mx in GASTOS_VARIABLES:
            if random.random() < 0.80:
                monto = redondear_tarifa(random.randint(mn, mx))
                await conn.execute(
                    "INSERT INTO gastos (categoria_id, fecha, descripcion, monto, proveedor, comprobante) "
                    "VALUES ($1,$2,$3,$4,$5,$6)",
                    cats_db.get(cat), date(año, mes, 15), concepto, monto, "Proveedor varios",
                    _comprobante(),
                )
                gastos_n += 1

    print(f"  Gastos generados:    {gastos_n}")


# ── Datos contables: documentos tributarios + cartola bancaria ────────────────

async def generar_contable(conn, desde: date, hasta: date):
    """
    Genera datos contables para que los agentes Tributario y Conciliación
    sigan teniendo información:
      - documentos_tributarios: facturas/boletas de compra (mensual).
      - movimientos_bancarios:  cartola espejo de pagos (abonos) y gastos
        (cargos), con algunas comisiones sin respaldo para que la conciliación
        no sea trivialmente 100%.
    """
    await conn.execute("SET search_path = hotel_mbi, public")

    # ── A) Documentos tributarios = facturas de compra que respaldan los
    #       gastos AFECTOS a IVA del mes (coherentes con el crédito). ─────────
    meses: set[tuple] = set()
    d = desde
    while d <= hasta:
        meses.add((d.year, d.month))
        d += timedelta(days=32)
        d = d.replace(day=1)

    docs_n = 0
    for año, mes in sorted(meses):
        existe = await conn.fetchval(
            "SELECT COUNT(*) FROM documentos_tributarios "
            "WHERE EXTRACT(YEAR FROM fecha)=$1 AND EXTRACT(MONTH FROM fecha)=$2",
            año, mes,
        )
        if existe:
            continue
        gastos_afectos = await conn.fetch("""
            SELECT g.fecha, g.monto, g.proveedor, cg.nombre AS categoria
            FROM gastos g LEFT JOIN categorias_gasto cg ON cg.id = g.categoria_id
            WHERE EXTRACT(YEAR FROM g.fecha)=$1 AND EXTRACT(MONTH FROM g.fecha)=$2
              AND COALESCE(cg.nombre, '') <> ALL($3::text[])
        """, año, mes, list(NO_AFECTO_IVA))
        for g in gastos_afectos:
            neto  = float(g["monto"])                 # gasto tratado como neto
            iva   = round(neto * 0.19)
            tipo  = "boleta" if neto < 30000 else "factura"
            # La mayoría ya contabilizadas; algunas quedan por revisar.
            estado = "registrado" if random.random() < 0.85 else "pendiente_revision"
            await conn.execute(
                "INSERT INTO documentos_tributarios "
                "(fecha, tipo, numero_documento, proveedor, monto_neto, monto_iva, "
                " monto_total, estado, categoria_gasto) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                g["fecha"], tipo, f"{tipo[0].upper()}-{random.randint(1000, 9999)}",
                g["proveedor"] or g["categoria"], neto, iva, neto + iva,
                estado, g["categoria"],
            )
            docs_n += 1
    print(f"  Documentos tributarios: {docs_n}")

    # ── B) Movimientos bancarios (cartola con excepciones realistas) ────────
    existe_mov = await conn.fetchval(
        "SELECT COUNT(*) FROM movimientos_bancarios WHERE fecha BETWEEN $1 AND $2",
        desde, hasta,
    )
    mov_n = 0
    rango_dias = max(1, (hasta - desde).days + 1)

    async def _mov(fecha, glosa, monto, ref):
        await conn.execute(
            "INSERT INTO movimientos_bancarios (fecha, glosa, monto, referencia) "
            "VALUES ($1,$2,$3,$4)", fecha, glosa, float(monto), ref)

    def _fecha_rand():
        return desde + timedelta(days=random.randint(0, rango_dias - 1))

    if not existe_mov:
        # Abonos (pagos): exactos / netos de comisión / sin movimiento
        pagos = await conn.fetch(
            "SELECT fecha, monto FROM pagos WHERE fecha BETWEEN $1 AND $2", desde, hasta)
        for p in pagos:
            r = random.random()
            if r < 0.90:                          # calza exacto
                await _mov(p["fecha"],
                           random.choice(["Abono Transbank", "Transferencia recibida", "Abono Webpay"]),
                           p["monto"], f"AB-{random.randint(10000, 99999)}")
                mov_n += 1
            elif r < 0.96:                        # llega NETO de comisión → no calza por monto
                neto = round(float(p["monto"]) * (1 - random.uniform(0.015, 0.03)))
                await _mov(p["fecha"], "Abono Transbank neto comision",
                           neto, f"TBKN-{random.randint(10000, 99999)}")
                mov_n += 1
            # ~4% restante: sin movimiento bancario → excepción de libro

        # Cargos (gastos): exactos / sin movimiento
        gastos = await conn.fetch(
            "SELECT fecha, monto FROM gastos WHERE fecha BETWEEN $1 AND $2", desde, hasta)
        for g in gastos:
            if random.random() < 0.92:
                await _mov(g["fecha"], "Pago proveedor/servicio",
                           -float(g["monto"]), f"PG-{random.randint(10000, 99999)}")
                mov_n += 1

        # Excepciones bancarias sin respaldo (~4% del total): comisiones, impuestos,
        # PAC no contabilizados y abonos no identificados.
        for _ in range(int(round(mov_n * 0.04))):
            if random.random() < 0.75:
                glosa, lo, hi = random.choice(CARGOS_BANCARIOS)
                await _mov(_fecha_rand(), glosa, -random.randint(lo, hi),
                           f"COM-{random.randint(1000, 9999)}")
            else:
                await _mov(_fecha_rand(), random.choice(ABONOS_SIN_RESPALDO),
                           random.randint(20000, 200000), f"ABX-{random.randint(1000, 9999)}")
            mov_n += 1

        # Comisión de mantención mensual garantizada en backfills largos
        if rango_dias >= 20:
            await _mov(hasta, "Comision mantencion cuenta",
                       -random.choice([8990, 9990, 12500]), f"COM-{random.randint(100, 999)}")
            mov_n += 1
    print(f"  Movimientos bancarios:  {mov_n}")


# ── Actualización de estados para cron diario ─────────────────────────────────

async def actualizar_estados(conn, ayer: date):
    checkins = await conn.execute(
        "UPDATE reservas SET estado='checkin' "
        "WHERE estado='confirmada' AND fecha_entrada=$1",
        ayer,
    )
    checkouts = await conn.execute(
        "UPDATE reservas SET estado='checkout' "
        "WHERE estado='checkin' AND fecha_salida=$1",
        ayer,
    )
    print(f"  Check-ins actualizados:  {checkins.split()[-1]}")
    print(f"  Check-outs actualizados: {checkouts.split()[-1]}")


# ─── Entry point ─────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Generador de datos de prueba")
    parser.add_argument("--desde", type=date.fromisoformat, help="Fecha inicio YYYY-MM-DD")
    parser.add_argument("--hasta", type=date.fromisoformat, help="Fecha fin YYYY-MM-DD")
    parser.add_argument("--ayer",  action="store_true", help="Generar datos de ayer + actualizar estados")
    args = parser.parse_args()

    if args.ayer:
        desde = hasta = date.today() - timedelta(days=1)
    elif args.desde and args.hasta:
        desde, hasta = args.desde, args.hasta
    else:
        parser.print_help()
        sys.exit(1)

    if not DATABASE_URL:
        print("ERROR: INGEST_DATABASE_URL o DATABASE_URL no configurado", file=sys.stderr)
        sys.exit(1)

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        print(f"\nGenerando datos: {desde} → {hasta}")
        await generar_periodo(conn, desde, hasta)
        await generar_contable(conn, desde, hasta)
        if args.ayer:
            await actualizar_estados(conn, desde)
        print("\n✓ Completado\n")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
