"""
Integración Defontana (ERP cloud chileno) — capa de conexión (Paso 1, horizontal).

Trae documentos (facturas/boletas/notas), ventas, productos y clientes/proveedores
y los normaliza a las mismas estructuras que usan las demás integraciones, para
alimentar tributario / P&L / ventas del vertical.

Estado: MOCK-FIRST. El camino real (autenticación + endpoints + mapeo de campos) se
completa contra la documentación oficial de la API de Defontana (pendiente de recibir).
Las estructuras normalizadas (lo que consume el dashboard) ya quedan definidas acá.

Credenciales por tenant en public.integraciones (proveedor='defontana'):
  access_token = secret/clave API ; cuenta_id = empresa/rut ; config = {url, usuario/client_id}
"""

import logging
import random
from datetime import date, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://api.defontana.com"


def _first(d: dict, *keys):
    """Primer valor no vacío entre `keys` (tolerante a variantes de nombres de campo)."""
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return None

# Tipos de documento (normalizados, estilo SII/Chile).
TIPOS_DOC = {
    "factura_venta": "Factura de venta", "factura_compra": "Factura de compra",
    "boleta": "Boleta electrónica", "nota_credito": "Nota de crédito",
    "nota_debito": "Nota de débito",
}


# ─────────────────────────────────────────────────────────────
# Credenciales
# ─────────────────────────────────────────────────────────────

async def obtener_credenciales(conn, tenant_id: str) -> Optional[dict]:
    row = await conn.fetchrow(
        """SELECT access_token, cuenta_id, config FROM public.integraciones
            WHERE tenant_id=$1 AND proveedor='defontana' AND activo=TRUE""", tenant_id)
    if not row or not row["access_token"] or not row["cuenta_id"]:
        return None
    cfg = row["config"] or {}
    if isinstance(cfg, str):
        import json
        cfg = json.loads(cfg)
    # Defontana auth: client + company + user + password.
    return {"client": cfg.get("client"), "company": row["cuenta_id"],
            "user": cfg.get("usuario"), "password": row["access_token"],
            "url": cfg.get("url", DEFAULT_URL)}


# ─────────────────────────────────────────────────────────────
# Camino real — API REST de Defontana (swagger api.defontana.com)
#   Auth: GET /api/Auth?client&company&user&password → token
#   Docs: GET /api/Accounting/GetVoucherList (FromDate/ToDate)
#   Productos: POST /api/Inventory/List
# Nota: los nombres de campos de respuesta se afinan contra una respuesta real
# (el swagger los referencia por $ref); el parseo es tolerante a variantes.
# ─────────────────────────────────────────────────────────────

async def _autenticar(client: httpx.AsyncClient, creds: dict) -> str:
    r = await client.get(creds["url"].rstrip("/") + "/api/Auth",
                         params={"client": creds["client"], "company": creds["company"],
                                 "user": creds["user"], "password": creds["password"]})
    r.raise_for_status()
    body = r.json()
    tok = (_first(body, "token", "access_token", "sessionId", "Token", "TokenBearer")
           or _first(body.get("data") or {}, "token", "access_token", "sessionId"))
    if not tok:
        raise RuntimeError(f"Defontana: autenticación sin token. Respuesta: {str(body)[:200]}")
    return tok


def _parse_factura_real(v: dict) -> dict:
    neto = float(_first(v, "net", "amountNet", "montoNeto", "neto") or 0)
    iva = float(_first(v, "tax", "iva", "amountTax", "montoIva") or 0)
    total = float(_first(v, "total", "amountTotal", "montoTotal") or (neto + iva))
    return {
        "id_externo": str(_first(v, "id", "voucherId", "number", "Number") or ""),
        "tipo": _first(v, "documentType", "voucherType", "tipo") or "documento",
        "tipo_label": _first(v, "documentTypeName", "voucherTypeName") or "Documento",
        "numero": _first(v, "number", "Number", "folio", "Folio"),
        "fecha": str(_first(v, "date", "Date", "fecha", "voucherDate") or "")[:10],
        "partner": _first(v, "clientName", "client", "razonSocial", "partner"),
        "rut": _first(v, "clientRut", "rut", "vat"),
        "monto_neto": neto, "monto_iva": iva, "monto_total": total,
        "estado": _first(v, "status", "estado") or None,
    }


def _parse_producto_real(p: dict) -> dict:
    return {
        "id_externo": str(_first(p, "id", "code", "codigo") or ""),
        "nombre": _first(p, "name", "nombre", "description") or "",
        "codigo": _first(p, "code", "codigo", "sku"),
        "precio": float(_first(p, "price", "salePrice", "precio") or 0),
        "costo": float(_first(p, "cost", "standardCost", "costo") or 0),
        "categoria": _first(p, "category", "categoryName", "categoria"),
    }


async def _fetch_real(creds: dict, desde: date, hasta: date) -> dict:
    async with httpx.AsyncClient(timeout=120.0) as client:
        token = await _autenticar(client, creds)
        headers = {"Authorization": f"Bearer {token}"}
        base = creds["url"].rstrip("/")

        vr = await client.get(base + "/api/Accounting/GetVoucherList", headers=headers,
                              params={"FromDate": desde.isoformat(), "ToDate": hasta.isoformat(),
                                      "ItemsPerPage": 1000, "Page": 0})
        vr.raise_for_status()
        vb = vr.json()
        vitems = (vb.get("data") or vb.get("items") or vb.get("voucherList")
                  or (vb if isinstance(vb, list) else []))
        facturas = [_parse_factura_real(v) for v in vitems]

        productos = []
        try:
            pr = await client.post(base + "/api/Inventory/List", headers=headers,
                                   json={"itemsPerPage": 1000, "page": 0})
            pr.raise_for_status()
            pb = pr.json()
            pitems = pb.get("data") or pb.get("items") or (pb if isinstance(pb, list) else [])
            productos = [_parse_producto_real(p) for p in pitems]
        except Exception as e:
            logger.warning(f"[defontana] productos no disponibles aún: {e}")

    # ventas y clientes: se mapean cuando se valide el esquema real (endpoints por cliente)
    return {"facturas": facturas, "ventas": [], "productos": productos, "clientes": []}


# ─────────────────────────────────────────────────────────────
# Datos de muestra (mock) — devuelven estructuras YA normalizadas
# ─────────────────────────────────────────────────────────────

_PARTNERS = ["Comercial Andes SpA", "Proveedor Sur Ltda", "Cliente Final",
             "Distribuidora Maipo SA", "Servicios Cordillera EIRL"]


def _mock(desde: date, hasta: date) -> dict:
    rng = random.Random(int(desde.strftime("%Y%m%d")))
    span = max((hasta - desde).days, 1)

    def fch():
        return str(desde + timedelta(days=rng.randint(0, span)))

    facturas = []
    for i in range(rng.randint(20, 40)):
        tipo = rng.choice(["factura_venta", "factura_compra", "boleta", "nota_credito"])
        neto = rng.randint(20000, 1500000)
        iva = round(neto * 0.19)
        facturas.append({
            "id_externo": f"DF-{i:05d}", "tipo": tipo, "tipo_label": TIPOS_DOC[tipo],
            "numero": 1000 + i, "fecha": fch(), "partner": rng.choice(_PARTNERS),
            "rut": f"7{rng.randint(1000000,9999999)}-{rng.randint(0,9)}",
            "monto_neto": neto, "monto_iva": iva, "monto_total": neto + iva,
            "estado": rng.choice(["emitido", "pagado", "pendiente"]),
        })
    ventas = [{"id_externo": f"V-{i:05d}", "numero": 5000 + i, "fecha": fch(),
               "partner": rng.choice(_PARTNERS), "monto_total": rng.randint(15000, 900000),
               "estado": "cerrada"} for i in range(rng.randint(15, 30))]
    productos = [{"id_externo": f"P{i:03d}", "nombre": n, "codigo": f"P{i:03d}",
                  "precio": p, "costo": c, "categoria": cat}
                 for i, (n, p, c, cat) in enumerate(
                     [("Producto A", 8990, 3200, "Mercadería"),
                      ("Producto B", 10990, 3800, "Mercadería"),
                      ("Servicio C", 25000, 9000, "Servicios"),
                      ("Insumo D", 4500, 1500, "Insumos")])]
    clientes = [{"id_externo": f"C{i:03d}", "nombre": p,
                 "rut": f"7{rng.randint(1000000,9999999)}-{rng.randint(0,9)}",
                 "email": None, "es_cliente": True, "es_proveedor": i % 2 == 0}
                for i, p in enumerate(_PARTNERS)]
    return {"facturas": facturas, "ventas": ventas, "productos": productos, "clientes": clientes}


# ─────────────────────────────────────────────────────────────
# Obtención normalizada
# ─────────────────────────────────────────────────────────────

async def obtener_datos(creds: Optional[dict], desde: date, hasta: date,
                        *, mock: bool = False) -> dict:
    """Devuelve {facturas, ventas, productos, clientes} normalizados. No persiste."""
    if mock:
        logger.info(f"[defontana] modo MOCK {desde}→{hasta}")
        return _mock(desde, hasta)
    if not creds:
        raise RuntimeError("Sin credenciales de Defontana. Usá mock=True.")
    return await _fetch_real(creds, desde, hasta)
