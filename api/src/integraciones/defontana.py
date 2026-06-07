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

logger = logging.getLogger(__name__)

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
    return {"secret": row["access_token"], "empresa": row["cuenta_id"],
            "url": cfg.get("url"), "usuario": cfg.get("usuario")}


# ─────────────────────────────────────────────────────────────
# Camino real (pendiente de la doc de la API de Defontana)
# ─────────────────────────────────────────────────────────────

async def _fetch_real(creds: dict, desde: date, hasta: date) -> dict:
    raise NotImplementedError(
        "Integración Defontana real pendiente: falta cablear autenticación y endpoints "
        "según la doc oficial de la API. Usar mock=True por ahora.")


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
