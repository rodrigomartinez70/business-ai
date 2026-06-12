"""
Integración Odoo (ERP) — capa de conexión (Paso 1, horizontal).

Trae facturas (account.move), ventas (sale.order / pos.order), productos
(product.product) y clientes/proveedores (res.partner), y los normaliza a
estructuras Python. El mapeo a un vertical + persistencia + endpoint + cron van
cuando se ate a un tenant (Paso 2).

API: Odoo External API por JSON-RPC (async, sin dependencias extra):
  POST {url}/jsonrpc  service=common  method=authenticate  → uid
  POST {url}/jsonrpc  service=object   method=execute_kw    → search_read, etc.

Credenciales por tenant en public.integraciones (proveedor='odoo'):
  access_token = API key (u password) ; cuenta_id = base de datos ; config = {url, usuario}
Modo mock=True: genera datos de muestra sin llamar a Odoo.
"""

import logging
import random
from datetime import date, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# account.move.move_type → etiqueta legible.
TIPOS_MOVE = {
    "out_invoice": "Factura de venta", "in_invoice": "Factura de compra",
    "out_refund": "Nota de crédito (venta)", "in_refund": "Nota de crédito (compra)",
    "entry": "Asiento contable",
}


# ─────────────────────────────────────────────────────────────
# Credenciales
# ─────────────────────────────────────────────────────────────

async def obtener_credenciales(conn, tenant_id: str) -> Optional[dict]:
    row = await conn.fetchrow(
        """SELECT access_token, cuenta_id, config FROM public.integraciones
            WHERE tenant_id=$1 AND proveedor='odoo' AND activo=TRUE""", tenant_id)
    if not row or not row["access_token"] or not row["cuenta_id"]:
        return None
    cfg = row["config"] or {}
    if isinstance(cfg, str):
        import json
        cfg = json.loads(cfg)
    if not cfg.get("url") or not cfg.get("usuario"):
        return None
    return {"api_key": row["access_token"], "db": row["cuenta_id"],
            "url": cfg["url"], "usuario": cfg["usuario"]}


# ─────────────────────────────────────────────────────────────
# JSON-RPC
# ─────────────────────────────────────────────────────────────

async def _jsonrpc(client: httpx.AsyncClient, url: str, service: str, method: str, args: list):
    payload = {"jsonrpc": "2.0", "method": "call",
               "params": {"service": service, "method": method, "args": args}}
    r = await client.post(url.rstrip("/") + "/jsonrpc", json=payload)
    r.raise_for_status()
    body = r.json()
    if body.get("error"):
        data = body["error"].get("data", {})
        raise RuntimeError(f"Odoo error: {data.get('message') or body['error'].get('message')}")
    return body.get("result")


async def _authenticate(client, creds: dict) -> int:
    uid = await _jsonrpc(client, creds["url"], "common", "authenticate",
                         [creds["db"], creds["usuario"], creds["api_key"], {}])
    if not uid:
        raise RuntimeError("Odoo: autenticación falló (revisá db/usuario/API key).")
    return uid


async def _search_read(client, creds, uid, model, domain, fields, limit=0) -> list[dict]:
    return await _jsonrpc(
        client, creds["url"], "object", "execute_kw",
        [creds["db"], uid, creds["api_key"], model, "search_read",
         [domain], {"fields": fields, "limit": limit}]) or []


def _m2o(v):
    """Campo many2one de Odoo: viene como [id, 'nombre'] o False."""
    return v[1] if isinstance(v, (list, tuple)) and len(v) == 2 else None


# ─────────────────────────────────────────────────────────────
# Parseo → estructuras normalizadas
# ─────────────────────────────────────────────────────────────

def _parse_factura(r: dict) -> dict:
    return {
        "id_externo": str(r.get("id")),
        "tipo": r.get("move_type"),
        "tipo_label": TIPOS_MOVE.get(r.get("move_type"), r.get("move_type")),
        "numero": r.get("name"),
        "fecha": r.get("invoice_date") or r.get("date"),
        "partner": _m2o(r.get("partner_id")),
        "monto_neto": float(r.get("amount_untaxed", 0) or 0),
        "monto_iva": float(r.get("amount_tax", 0) or 0),
        "monto_total": float(r.get("amount_total", 0) or 0),
        "estado": r.get("state"),
        "estado_pago": r.get("payment_state"),
    }


def _parse_venta(r: dict, origen: str) -> dict:
    return {
        "id_externo": f"{origen}:{r.get('id')}",
        "origen": origen,            # 'sale' | 'pos'
        "numero": r.get("name"),
        "fecha": (r.get("date_order") or "")[:10],
        "partner": _m2o(r.get("partner_id")),
        "monto_total": float(r.get("amount_total", 0) or 0),
        "estado": r.get("state"),
    }


def _parse_producto(r: dict) -> dict:
    return {
        "id_externo": str(r.get("id")),
        "nombre": r.get("name", ""),
        "codigo": r.get("default_code") or None,
        "precio": float(r.get("list_price", 0) or 0),
        "costo": float(r.get("standard_price", 0) or 0),
        "categoria": _m2o(r.get("categ_id")),
    }


def _parse_cliente(r: dict) -> dict:
    return {
        "id_externo": str(r.get("id")),
        "nombre": r.get("name", ""),
        "rut": r.get("vat") or None,
        "email": r.get("email") or None,
        "es_cliente": (r.get("customer_rank", 0) or 0) > 0,
        "es_proveedor": (r.get("supplier_rank", 0) or 0) > 0,
    }


# ─────────────────────────────────────────────────────────────
# Fetchers (Odoo real)
# ─────────────────────────────────────────────────────────────

async def _fetch_real(creds: dict, desde: date, hasta: date) -> dict:
    async with httpx.AsyncClient(timeout=120.0) as client:
        uid = await _authenticate(client, creds)
        d1, d2 = desde.isoformat(), hasta.isoformat()
        facturas = await _search_read(
            client, creds, uid, "account.move",
            [["move_type", "in", ["out_invoice", "in_invoice", "out_refund", "in_refund"]],
             ["invoice_date", ">=", d1], ["invoice_date", "<=", d2]],
            ["name", "move_type", "invoice_date", "date", "partner_id",
             "amount_untaxed", "amount_tax", "amount_total", "state", "payment_state"])
        ventas_so = await _search_read(
            client, creds, uid, "sale.order",
            [["date_order", ">=", d1], ["date_order", "<=", d2 + " 23:59:59"]],
            ["name", "date_order", "partner_id", "amount_total", "state"])
        ventas_pos = await _search_read(
            client, creds, uid, "pos.order",
            [["date_order", ">=", d1], ["date_order", "<=", d2 + " 23:59:59"]],
            ["name", "date_order", "partner_id", "amount_total", "state"])
        productos = await _search_read(
            client, creds, uid, "product.product", [],
            ["name", "default_code", "list_price", "standard_price", "categ_id"], limit=2000)
        clientes = await _search_read(
            client, creds, uid, "res.partner", [["active", "=", True]],
            ["name", "vat", "email", "customer_rank", "supplier_rank"], limit=5000)
    return {"facturas": facturas, "ventas_so": ventas_so, "ventas_pos": ventas_pos,
            "productos": productos, "clientes": clientes}


# ─────────────────────────────────────────────────────────────
# Datos de muestra (mock)
# ─────────────────────────────────────────────────────────────

def _mock(desde: date, hasta: date) -> dict:
    rng = random.Random(int(desde.strftime("%Y%m%d")))
    partners = ["Comercial Andes SpA", "Proveedor Sur Ltda", "Cliente Final",
                "Distribuidora Maipo SA", "Servicios Cordillera EIRL"]
    span = max((hasta - desde).days, 1)

    def fch():
        return str(desde + timedelta(days=rng.randint(0, span)))

    facturas = []
    for i in range(rng.randint(20, 40)):
        tipo = rng.choice(["out_invoice", "in_invoice", "out_refund", "in_refund"])
        neto = rng.randint(20000, 1500000)
        facturas.append({"id": 5000 + i, "move_type": tipo, "name": f"INV/{2026}/{i:04d}",
                         "invoice_date": fch(), "partner_id": [10 + i % 5, rng.choice(partners)],
                         "amount_untaxed": neto, "amount_tax": round(neto * 0.19),
                         "amount_total": round(neto * 1.19), "state": "posted",
                         "payment_state": rng.choice(["paid", "not_paid", "partial"])})
    ventas_so = [{"id": 700 + i, "name": f"S0{i:04d}", "date_order": fch() + " 13:00:00",
                  "partner_id": [10 + i % 5, rng.choice(partners)],
                  "amount_total": rng.randint(15000, 900000), "state": "sale"}
                 for i in range(rng.randint(15, 30))]
    productos = [{"id": 300 + i, "name": n, "default_code": f"P{i:03d}",
                  "list_price": p, "standard_price": c, "categ_id": [1, "Productos"]}
                 for i, (n, p, c) in enumerate(
                     [("Producto A", 8990, 3200), ("Producto B", 10990, 3800),
                      ("Servicio C", 25000, 9000), ("Insumo D", 4500, 1500)])]
    clientes = [{"id": 10 + i, "name": p, "vat": f"7{rng.randint(1000000,9999999)}-{rng.randint(0,9)}",
                 "email": None, "customer_rank": 1, "supplier_rank": i % 2}
                for i, p in enumerate(partners)]
    return {"facturas": facturas, "ventas_so": ventas_so, "ventas_pos": [],
            "productos": productos, "clientes": clientes}


# ─────────────────────────────────────────────────────────────
# Obtención normalizada (fetch + parse, con modo mock)
# ─────────────────────────────────────────────────────────────

async def obtener_datos(creds: Optional[dict], desde: date, hasta: date,
                        *, mock: bool = False) -> dict:
    if mock:
        raw = _mock(desde, hasta)
        logger.info(f"[odoo] modo MOCK {desde}→{hasta}")
    else:
        if not creds:
            raise RuntimeError("Sin credenciales de Odoo (url/db/usuario/API key). Usá mock=True.")
        raw = await _fetch_real(creds, desde, hasta)
        logger.info(f"[odoo] {len(raw['facturas'])} facturas, "
                    f"{len(raw['ventas_so']) + len(raw['ventas_pos'])} ventas desde Odoo")

    ventas = ([_parse_venta(r, "sale") for r in raw["ventas_so"]]
              + [_parse_venta(r, "pos") for r in raw["ventas_pos"]])
    return {
        "facturas": [_parse_factura(r) for r in raw["facturas"]],
        "ventas": ventas,
        "productos": [_parse_producto(r) for r in raw["productos"]],
        "clientes": [_parse_cliente(r) for r in raw["clientes"]],
    }


# ─────────────────────────────────────────────────────────────
# Contabilidad: plan de cuentas + saldos mensuales (para el P&L contable)
# ─────────────────────────────────────────────────────────────

_MAP_TIPO = {                       # account_type Odoo → tipo normalizado nuestro
    "income": "income", "income_other": "income", "other_income": "income",
    "expense_direct_cost": "cogs", "cost_of_revenue": "cogs",
    "expense": "expense", "expense_depreciation": "expense",
}
_TIPOS_RESULTADO = ["income", "income_other", "expense", "expense_direct_cost", "expense_depreciation"]


def _tipo_cuenta(account_type: str | None) -> str:
    return _MAP_TIPO.get(account_type or "", "otro")


def _grupo_de(codigo: str | None) -> str:
    return codigo.rsplit(".", 1)[0] if codigo and "." in codigo else (codigo or "")


_MOCK_PLAN = [                        # (codigo, nombre, tipo)
    ("4.1.01", "Ventas",                  "income"),
    ("5.1.01", "Costo de Ventas",         "cogs"),
    ("6.1.01", "Gastos de Marketing",     "expense"),
    ("6.2.01", "Sueldos Administración",  "expense"),
    ("6.2.02", "Honorarios",              "expense"),
    ("6.3.01", "Gastos Generales",        "expense"),
    ("6.9.01", "Impuesto a la Renta",     "tax"),
]


async def obtener_plan_cuentas(creds: Optional[dict], *, mock: bool = False) -> list[dict]:
    if mock:
        return [{"id_externo": c, "codigo": c, "nombre": n, "tipo": t, "grupo": _grupo_de(c)}
                for c, n, t in _MOCK_PLAN]
    async with httpx.AsyncClient(timeout=120.0) as client:
        uid = await _authenticate(client, creds)
        rows = await _search_read(
            client, creds, uid, "account.account",
            [["account_type", "in", _TIPOS_RESULTADO]],
            ["code", "name", "account_type"], limit=5000)
    return [{"id_externo": str(r["id"]), "codigo": r.get("code"), "nombre": r.get("name"),
             "tipo": _tipo_cuenta(r.get("account_type")), "grupo": _grupo_de(r.get("code"))}
            for r in rows]


def _mock_saldos(desde: date, hasta: date) -> list[dict]:
    base = {"4.1.01": 7_500_000, "5.1.01": 2_700_000, "6.1.01": 1_500_000,
            "6.2.01": 4_000_000, "6.2.02": 1_200_000, "6.3.01": 2_500_000, "6.9.01": 800_000}
    out, y, m = [], desde.year, desde.month
    while (y, m) <= (hasta.year, hasta.month):
        rng = random.Random(y * 100 + m)
        for c, amt in base.items():
            v = int(amt * (0.9 + rng.random() * 0.2))
            if c.startswith("4."):                       # income → haber
                out.append({"cuenta_externa": c, "anio": y, "mes": m, "debe": 0, "haber": v})
            else:                                        # costo/gasto/impuesto → debe
                out.append({"cuenta_externa": c, "anio": y, "mes": m, "debe": v, "haber": 0})
        m, y = (1, y + 1) if m == 12 else (m + 1, y)
    return out


async def obtener_saldos(creds: Optional[dict], desde: date, hasta: date,
                         *, mock: bool = False) -> list[dict]:
    if mock:
        return _mock_saldos(desde, hasta)
    import datetime as _dt
    async with httpx.AsyncClient(timeout=120.0) as client:
        uid = await _authenticate(client, creds)
        rows = await _jsonrpc(
            client, creds["url"], "object", "execute_kw",
            [creds["db"], uid, creds["api_key"], "account.move.line", "read_group",
             [[["parent_state", "=", "posted"], ["date", ">=", desde.isoformat()],
               ["date", "<=", hasta.isoformat()]],
              ["debit:sum", "credit:sum"], ["account_id", "date:month"]],
             {"lazy": False}]) or []
    saldos = []
    for r in rows:
        acc = r.get("account_id")
        if not isinstance(acc, (list, tuple)):
            continue
        try:
            d = _dt.datetime.strptime(r.get("date:month") or "", "%B %Y")
        except ValueError:
            continue
        saldos.append({"cuenta_externa": str(acc[0]), "anio": d.year, "mes": d.month,
                       "debe": float(r.get("debit", 0) or 0), "haber": float(r.get("credit", 0) or 0)})
    return saldos


async def sincronizar_contabilidad(conn, tenant_id: str, desde: date, hasta: date,
                                   *, mock: bool = False) -> dict:
    """Trae plan de cuentas + saldos y los upserta en plan_cuentas / saldos_cuentas del tenant."""
    creds = None
    if not mock:
        creds = await obtener_credenciales(conn, tenant_id)
        if not creds:
            raise RuntimeError("Sin credenciales de Odoo. Usá mock=true.")
    plan = await obtener_plan_cuentas(creds, mock=mock)
    saldos = await obtener_saldos(creds, desde, hasta, mock=mock)

    idmap = {}
    for c in plan:
        cid = await conn.fetchval(
            """INSERT INTO plan_cuentas (id_externo, codigo, nombre, tipo, grupo)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (id_externo) DO UPDATE
                   SET codigo=EXCLUDED.codigo, nombre=EXCLUDED.nombre,
                       tipo=EXCLUDED.tipo, grupo=EXCLUDED.grupo
               RETURNING id""",
            c["id_externo"], c["codigo"], c["nombre"], c["tipo"], c["grupo"])
        idmap[c["id_externo"]] = cid
    n = 0
    for s in saldos:
        cid = idmap.get(s["cuenta_externa"])
        if not cid:
            continue
        await conn.execute(
            """INSERT INTO saldos_cuentas (cuenta_id, anio, mes, debe, haber)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (cuenta_id, anio, mes) DO UPDATE
                   SET debe=EXCLUDED.debe, haber=EXCLUDED.haber""",
            cid, s["anio"], s["mes"], s["debe"], s["haber"])
        n += 1
    return {"tenant": tenant_id, "cuentas": len(plan), "saldos": n,
            "modo": "mock" if mock else "api"}
