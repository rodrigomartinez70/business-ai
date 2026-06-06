"""
Integración Toteat (POS gastronómico) — capa de conexión (Paso 1).

Trae ventas (/sales), menú (/products) y recaudación diaria (/collection) del POS
y las normaliza a estructuras Python. El mapeo al vertical restaurante
(pedidos/detalle_pedido/pagos/productos) y la persistencia van en el Paso 2.

Auth: 4 query params por restaurante (xapitoken, xir, xil, xiu) — sin headers/OAuth.
Restricciones respetadas: ventana máx 15 días por llamada y rate limit (/sales 3/min).
Toteat opera por turno: el período filtra por turnos, no por fecha calendario.

Credenciales por tenant en public.integraciones (proveedor='toteat'):
  access_token = xapitoken ; cuenta_id = xir ; config = {xil, xiu, base_url}
Modo mock=True: genera datos de muestra sin llamar a la API.
"""

import asyncio
import logging
import random
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL_DEFAULT = "https://api.toteat.com/mw/or/1.0/"
_MAX_DIAS = 15          # ventana máxima por llamada a /sales
_THROTTLE_SEG = 21      # /sales: 3 req/min → 1 cada ~20s

# Medios de pago de Toteat (id → nombre).
MEDIOS_PAGO = {
    1000: "Efectivo", 1001: "Efectivo Moneda Extranjera", 2000: "Tarjeta Crédito",
    3000: "Tarjeta Débito", 4000: "Convenio", 5000: "Web Pay", 5001: "PayPal",
    6000: "Móvil", 7000: "Mensaje", 8001: "Factura/Contra Entrega", 9000: "Cheque",
    9001: "Transferencia", 10001: "Ticket Restaurant", 10020: "Cheque Restaurant",
    10030: "Multicaja", 10040: "Voucher BBG",
}


# ─────────────────────────────────────────────────────────────
# Credenciales
# ─────────────────────────────────────────────────────────────

async def obtener_credenciales(conn, tenant_id: str) -> Optional[dict]:
    row = await conn.fetchrow(
        """SELECT access_token, cuenta_id, config
             FROM public.integraciones
            WHERE tenant_id = $1 AND proveedor = 'toteat' AND activo = TRUE""",
        tenant_id,
    )
    if not row or not row["access_token"] or not row["cuenta_id"]:
        return None
    cfg = row["config"] or {}
    if isinstance(cfg, str):
        import json
        cfg = json.loads(cfg)
    if not cfg.get("xil") or not cfg.get("xiu"):
        return None
    return {
        "xapitoken": row["access_token"],
        "xir": row["cuenta_id"],
        "xil": cfg["xil"],
        "xiu": cfg["xiu"],
        "base_url": cfg.get("base_url", BASE_URL_DEFAULT),
    }


def _auth_params(creds: dict) -> dict:
    return {"xapitoken": creds["xapitoken"], "xir": creds["xir"],
            "xil": creds["xil"], "xiu": creds["xiu"]}


# ─────────────────────────────────────────────────────────────
# Utilidades de período (ventana máx 15 días)
# ─────────────────────────────────────────────────────────────

def _chunks(desde: date, hasta: date, max_dias: int = _MAX_DIAS):
    """Divide [desde, hasta] en tramos de a lo sumo `max_dias` días (inclusive)."""
    ini = desde
    while ini <= hasta:
        fin = min(ini + timedelta(days=max_dias - 1), hasta)
        yield ini, fin
        ini = fin + timedelta(days=1)


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


# ─────────────────────────────────────────────────────────────
# Llamadas a la API
# ─────────────────────────────────────────────────────────────

async def _get(client: httpx.AsyncClient, base: str, path: str, params: dict) -> dict:
    url = base.rstrip("/") + "/" + path.lstrip("/")
    resp = await client.get(url, params=params)
    if resp.status_code == 429:
        raise RuntimeError("Toteat rate limit (429) — reintentar más tarde.")
    resp.raise_for_status()
    body = resp.json()
    if isinstance(body, dict) and body.get("ok") is False:
        raise RuntimeError(f"Toteat respondió error: {body.get('msg')}")
    return body


async def fetch_sales(creds: dict, desde: date, hasta: date) -> list[dict]:
    """Pagos de órdenes cerradas en el período. Trocea en ≤15 días y respeta 3/min."""
    base = creds["base_url"]
    filas: list[dict] = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        primero = True
        for ini, fin in _chunks(desde, hasta):
            if not primero:
                await asyncio.sleep(_THROTTLE_SEG)  # rate limit 3/min
            primero = False
            params = {**_auth_params(creds), "ini": _ymd(ini), "end": _ymd(fin)}
            body = await _get(client, base, "sales", params)
            filas.extend(body.get("data", []) or [])
    return filas


async def fetch_products(creds: dict, solo_activos: bool = True) -> list[dict]:
    base = creds["base_url"]
    params = {**_auth_params(creds), "activeProducts": "true" if solo_activos else "false"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        body = await _get(client, base, "products", params)
    return body.get("data", []) or []


async def fetch_collection(creds: dict, dia: date) -> dict:
    base = creds["base_url"]
    params = {**_auth_params(creds), "date": _ymd(dia)}
    async with httpx.AsyncClient(timeout=60.0) as client:
        body = await _get(client, base, "collection", params)
    return body.get("data", {}) or {}


# ─────────────────────────────────────────────────────────────
# Parseo → estructuras normalizadas
# ─────────────────────────────────────────────────────────────

def _parse_producto(raw: dict) -> dict:
    return {
        "id_externo": str(raw.get("id") or raw.get("localCode") or ""),
        "nombre": raw.get("name", ""),
        "precio": float(raw.get("price", 0) or 0),
        "precio_referencia": (float(raw["referencePrice"])
                              if raw.get("referencePrice") not in (None, "") else None),
        "categoria": raw.get("category"),
        "categoria_id": str(raw.get("categoryId")) if raw.get("categoryId") is not None else None,
        "costo": float(raw.get("cost", 0) or 0),   # Toteat /products NO trae costo → 0 (real)
        "es_modificador": bool(raw.get("isModifier", False)),
        "sorting": raw.get("sorting"),
    }


def _parse_venta(raw: dict) -> dict:
    """Normaliza una venta de /sales. Tolerante a campos ausentes (el detalle fino
    del schema se afina con una respuesta real)."""
    pagos = []
    for p in raw.get("payments", []) or []:
        mid = p.get("paymentMethodId", p.get("id"))
        try:
            mid = int(mid) if mid is not None else None
        except (TypeError, ValueError):
            mid = None
        pagos.append({
            "medio_id": mid,
            "medio": MEDIOS_PAGO.get(mid, p.get("paymentMethod") or "Otro"),
            "monto": float(p.get("amount", p.get("total", 0)) or 0),
            "propina": float(p.get("tip", 0) or 0),
            "fiscal_type": p.get("fiscalType"),  # 'NC' → montos en negativo
        })
    lineas = []
    for ln in raw.get("line", raw.get("lines", []) or []) or []:
        cant = float(ln.get("quantity", 1) or 1)
        precio = float(ln.get("price", ln.get("unitPrice", 0)) or 0)
        lineas.append({
            "producto": ln.get("productName", ln.get("name", "")),
            "codigo": str(ln.get("productCode", ln.get("localCode", "")) or ""),
            "cantidad": cant,
            "precio_unitario": precio,
            "total": float(ln.get("total", precio * cant) or 0),
        })
    return {
        "order_id": str(raw.get("orderId", "") or ""),
        "order_reference": str(raw.get("orderReference", "") or ""),
        "fecha": raw.get("closeDate") or raw.get("operationDate") or raw.get("date"),
        "estado": raw.get("orderStatus", "CLOSED"),
        "mesa": raw.get("tableId") or raw.get("table"),
        "canal": raw.get("channel"),
        "comensales": int(raw.get("guests") or raw.get("pax") or raw.get("diners") or 1),
        "propina": sum(p["propina"] for p in pagos) or float(raw.get("tip", 0) or 0),
        "total": float(raw.get("total", 0) or 0) or sum(p["monto"] for p in pagos),
        "lineas": lineas,
        "pagos": pagos,
    }


# ─────────────────────────────────────────────────────────────
# Datos de muestra (modo mock)
# ─────────────────────────────────────────────────────────────

_MOCK_MENU = [
    ("Hamburguesa Clásica", "Platos de fondo", 8990, 3200),
    ("Pizza Margarita", "Pizzas", 10990, 3800),
    ("Pasta del día", "Pastas", 9490, 2900),
    ("Ensalada César", "Entradas", 6990, 2100),
    ("Cerveza artesanal", "Bebidas", 4500, 1500),
    ("Bebida/jugo", "Bebidas", 2500, 700),
    ("Tabla para compartir", "Entradas", 14000, 5200),
    ("Empanada de pino", "Entradas", 3500, 1100),
]


def _mock_products() -> list[dict]:
    out = []
    for i, (nombre, cat, precio, costo) in enumerate(_MOCK_MENU):
        out.append({"id": 9000 + i, "name": nombre, "price": precio, "cost": costo,
                    "referencePrice": None, "category": cat, "categoryId": 100 + (i % 4),
                    "localCode": f"P{i:03d}", "isModifier": False, "sorting": f"{i:03d}"})
    return out


def _mock_sales(desde: date, hasta: date) -> list[dict]:
    medios = [1000, 2000, 3000, 5000]
    canales = ["salon", "delivery", "takeaway"]
    ventas = []
    dia = desde
    while dia <= hasta:
        # Semilla por día → mismos orderId y valores en cada corrida (idempotente).
        rng = random.Random(int(dia.strftime("%Y%m%d")))
        n_ordenes = rng.randint(8, 16)
        for j in range(n_ordenes):  # órdenes del turno
            oid = int(dia.strftime("%Y%m%d")) * 1000 + j
            n = rng.randint(1, 4)
            line = []
            total = 0
            for _ in range(n):
                nombre, cat, precio, _c = rng.choice(_MOCK_MENU)
                cant = rng.randint(1, 3)
                line.append({"productName": nombre, "productCode": nombre, "quantity": cant,
                             "price": precio, "total": precio * cant})
                total += precio * cant
            ventas.append({
                "orderId": oid, "orderReference": str(oid),
                "closeDate": f"{dia.isoformat()}T{rng.randint(12,23):02d}:{rng.randint(0,59):02d}:00",
                "orderStatus": "CLOSED",
                "tableId": rng.randint(1, 20), "channel": rng.choice(canales),
                "guests": rng.randint(1, 5),
                "total": total,
                "line": line,
                "payments": [{"paymentMethodId": rng.choice(medios), "amount": total,
                              "tip": int(total * rng.uniform(0, 0.10)), "fiscalType": "BOL"}],
            })
        dia += timedelta(days=1)
    return ventas


def _mock_collection(dia: date) -> dict:
    return {"date": dia.isoformat(), "localID": 1, "restaurantID": 7245392520658112,
            "shifts": {"1": {"efectivo": 350000, "tarjeta": 820000}}}


# ─────────────────────────────────────────────────────────────
# Obtención normalizada (fetch + parse, con modo mock)
# ─────────────────────────────────────────────────────────────

async def obtener_datos(creds: Optional[dict], desde: date, hasta: date,
                        *, mock: bool = False) -> dict:
    """Devuelve {productos, ventas, recaudaciones} normalizados. No persiste."""
    if mock:
        prod_raw = _mock_products()
        sales_raw = _mock_sales(desde, hasta)
        colecciones = [_mock_collection(hasta)]
        logger.info(f"[toteat] modo MOCK {desde}→{hasta}")
    else:
        if not creds:
            raise RuntimeError("Sin credenciales de Toteat. Cargá xapitoken/xir/xil/xiu "
                               "en public.integraciones (proveedor='toteat') o usá mock=True.")
        prod_raw = await fetch_products(creds)
        sales_raw = await fetch_sales(creds, desde, hasta)
        colecciones = [await fetch_collection(creds, hasta)]
        logger.info(f"[toteat] {len(prod_raw)} productos, {len(sales_raw)} ventas desde la API")

    return {
        "productos": [_parse_producto(p) for p in prod_raw if not p.get("isModifier")],
        "ventas": [_parse_venta(v) for v in sales_raw],
        "recaudaciones": colecciones,
    }


# ─────────────────────────────────────────────────────────────
# Mapeo al vertical restaurante (pedidos/detalle_pedido/pagos/productos)
# ─────────────────────────────────────────────────────────────

_CANAL_MAP = {"salon": "Salón", "salón": "Salón", "delivery": "Delivery",
              "takeaway": "Takeaway", "pickup": "Takeaway", "pos": "Salón"}


def _metodo_pago(medio: str) -> str:
    m = (medio or "").lower()
    if "efectivo" in m:
        return "efectivo"
    if "tarjeta" in m or "web pay" in m or "paypal" in m or "débito" in m or "crédito" in m:
        return "tarjeta"
    if "transfer" in m:
        return "transferencia"
    return m[:30] or "otro"


def _solo_fecha(s) -> date:
    if not s:
        return date.today()
    return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


async def _ensure_id(conn, cache: dict, tabla: str, nombre: str, insert_sql: str) -> int:
    if nombre in cache:
        return cache[nombre]
    row = await conn.fetchrow(f"SELECT id FROM {tabla} WHERE nombre = $1 LIMIT 1", nombre)
    cache[nombre] = row["id"] if row else await conn.fetchval(insert_sql, nombre)
    return cache[nombre]


async def sincronizar(conn, tenant_id: str, desde: date, hasta: date,
                      *, mock: bool = False) -> dict:
    """Trae datos de Toteat y los mapea a las tablas del vertical restaurante.
    Idempotente (upsert por id_externo). Requiere search_path en el schema del tenant."""
    creds = None if mock else await obtener_credenciales(conn, tenant_id)
    data = await obtener_datos(creds, desde, hasta, mock=mock)

    cat_cache: dict = {}
    prod_por_clave: dict = {}   # id_externo y nombre → producto_id
    prod_costo: dict = {}       # producto_id → costo unitario

    # Toteat /products NO entrega costo → si falta, se estima food cost (35%).
    FOOD_COST_PCT = 0.35

    # 1) Productos → categorias_menu + productos
    for p in data["productos"]:
        cat_id = None
        if p.get("categoria"):
            cat_id = await _ensure_id(
                conn, cat_cache, "categorias_menu", p["categoria"],
                "INSERT INTO categorias_menu (nombre) VALUES ($1) RETURNING id")
        costo = p["costo"] if p.get("costo", 0) > 0 else round(p["precio"] * FOOD_COST_PCT, 2)
        pid = await conn.fetchval(
            """INSERT INTO productos (id_externo, categoria_id, nombre, precio, costo, activo)
               VALUES ($1,$2,$3,$4,$5,TRUE)
               ON CONFLICT (id_externo) WHERE id_externo IS NOT NULL DO UPDATE SET
                   categoria_id = EXCLUDED.categoria_id, nombre = EXCLUDED.nombre,
                   precio = EXCLUDED.precio, costo = EXCLUDED.costo
               RETURNING id""",
            p["id_externo"], cat_id, p["nombre"], p["precio"], costo)
        prod_por_clave[p["id_externo"]] = pid
        prod_por_clave[p["nombre"]] = pid
        prod_costo[pid] = costo

    # 2) Ventas → pedidos / detalle_pedido / pagos
    canal_cache: dict = {}
    n_ped = 0
    for v in data["ventas"]:
        canal_nombre = _CANAL_MAP.get((v.get("canal") or "").lower(), "Salón")
        canal_id = await _ensure_id(
            conn, canal_cache, "canales_venta", canal_nombre,
            "INSERT INTO canales_venta (nombre) VALUES ($1) RETURNING id")
        fecha = _solo_fecha(v["fecha"])
        estado = "anulado" if v["estado"] in ("CANCELLED", "CANCELED") else "pagado"

        ped_id = await conn.fetchval(
            """INSERT INTO pedidos (id_externo, canal_id, fecha, estado, comensales, propina)
               VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (id_externo) WHERE id_externo IS NOT NULL DO UPDATE SET
                   canal_id = EXCLUDED.canal_id, fecha = EXCLUDED.fecha, estado = EXCLUDED.estado,
                   comensales = EXCLUDED.comensales, propina = EXCLUDED.propina
               RETURNING id""",
            v["order_id"], canal_id, fecha, estado,
            max(1, int(v.get("comensales", 1))), v.get("propina", 0))

        # Reemplazo idempotente del detalle y pagos de la orden
        await conn.execute("DELETE FROM detalle_pedido WHERE pedido_id = $1", ped_id)
        await conn.execute("DELETE FROM pagos WHERE pedido_id = $1", ped_id)

        det_rows = []
        for ln in v["lineas"]:
            pid = prod_por_clave.get(ln["codigo"]) or prod_por_clave.get(ln["producto"])
            if pid is None:  # producto fuera del menú → crearlo al vuelo
                costo_ln = round(ln["precio_unitario"] * FOOD_COST_PCT, 2)
                pid = await conn.fetchval(
                    "INSERT INTO productos (nombre, precio, costo, activo) VALUES ($1,$2,$3,TRUE) RETURNING id",
                    ln["producto"] or "Producto", ln["precio_unitario"], costo_ln)
                prod_por_clave[ln["producto"]] = pid
                prod_costo[pid] = costo_ln
            det_rows.append((ped_id, pid, int(ln["cantidad"]), ln["precio_unitario"], prod_costo.get(pid, 0)))
        if det_rows:
            await conn.executemany(
                "INSERT INTO detalle_pedido (pedido_id, producto_id, cantidad, precio_unitario, costo_unitario) "
                "VALUES ($1,$2,$3,$4,$5)", det_rows)

        pago_rows = [(ped_id, fecha, pg["monto"], _metodo_pago(pg["medio"]), pg.get("propina", 0))
                     for pg in v["pagos"]]
        if pago_rows:
            await conn.executemany(
                "INSERT INTO pagos (pedido_id, fecha, monto, metodo, propina, estado) "
                "VALUES ($1,$2,$3,$4,$5,'pagado')", pago_rows)
        n_ped += 1

    return {"tenant": tenant_id, "productos": len(data["productos"]), "pedidos": n_ped,
            "desde": str(desde), "hasta": str(hasta), "modo": "mock" if mock else "api"}
