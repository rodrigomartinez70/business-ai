"""
Consulta del RCV al SII con token (Fase B, paso 2).

Trae los documentos del Registro de Compras y Ventas de un período:
  - VENTA   = documentos emitidos  → IVA débito
  - COMPRA  = documentos recibidos → IVA crédito
y los normaliza al mismo shape que `finanzas.rcv` (para reusar el upsert).

PARAMETRIZADO PARA ITERAR: el endpoint, el payload y el mapeo de campos están
aislados (`_RCV_BASE`, `consultar`, `_CAMPOS`/`_mapear_item`). El formato exacto de
la respuesta del SII (facade JSON de consdcv) se confirma con un certificado real
contra maullin — ahí se ajustan `_RCV_BASE`/`_CAMPOS` si difieren, sin tocar la
orquestación ni el guardado. El mapeo es tolerante a variantes de nombres de campo.
"""

from __future__ import annotations

import logging

import httpx

from ..finanzas.cartola import num_cl, parse_fecha
from ..finanzas.rcv import _TIPO_DTE

logger = logging.getLogger(__name__)

# Base del facade de consulta RCV por ambiente. AJUSTAR si el endpoint real difiere.
_RCV_BASE = {
    "certificacion": "https://www4c.sii.cl/consdcvinternetui/services/data/facadeService",
    "produccion":    "https://www4.sii.cl/consdcvinternetui/services/data/facadeService",
}

# Mapeo campo-del-SII → campo nuestro. Se prueban varias claves (el SII varía nombres
# entre versiones). Ajustar acá cuando veamos la respuesta real.
_CAMPOS = {
    "tipo":   ("detTipoDoc", "dcvTipoDoc", "tipoDoc", "tipoDte"),
    "folio":  ("detNroDoc", "nroDoc", "folio"),
    "rut":    ("detRutDoc", "rutDoc", "rut"),
    "dv":     ("detDvDoc", "dvDoc", "dv"),
    "razon":  ("detRznSoc", "rznSoc", "razonSocial"),
    "fecha":  ("detFchDoc", "fchDoc", "fechaDocto", "fechaEmision"),
    "neto":   ("detMntNeto", "mntNeto", "montoNeto"),
    "iva":    ("detMntIVA", "mntIVA", "mntIva", "montoIva"),
    "total":  ("detMntTotal", "mntTotal", "montoTotal"),
}


def _g(item: dict, campo: str):
    for k in _CAMPOS[campo]:
        v = item.get(k)
        if v not in (None, ""):
            return v
    return None


def _mapear_item(item: dict, registro: str) -> dict:
    """Una fila del detalle RCV del SII → documento (shape de finanzas.rcv)."""
    tipo_cod = _g(item, "tipo")
    rut = _g(item, "rut")
    dv = _g(item, "dv")
    rut_full = f"{rut}-{dv}" if (rut and dv) else (str(rut) if rut else None)
    folio = _g(item, "folio")
    try:
        tipo = _TIPO_DTE.get(int(str(tipo_cod)), "factura") if tipo_cod is not None else "factura"
    except (TypeError, ValueError):
        tipo = "factura"
    return {
        "clase": "compra" if registro.upper() == "COMPRA" else "venta",
        "tipo": tipo,
        "numero_documento": (str(folio)[:50] if folio is not None else None),
        "rut_contraparte": (rut_full[:20] if rut_full else None),
        "proveedor": (str(_g(item, "razon"))[:100] if _g(item, "razon") else "—"),
        "fecha": parse_fecha(str(_g(item, "fecha") or "")),
        "monto_neto": round(num_cl(_g(item, "neto")), 2),
        "monto_iva": round(num_cl(_g(item, "iva")), 2),
        "monto_total": round(num_cl(_g(item, "total")), 2),
    }


def _rut_partes(rut: str) -> tuple[str, str]:
    limpio = (rut or "").replace(".", "").replace(" ", "").strip()
    if "-" in limpio:
        cuerpo, dv = limpio.rsplit("-", 1)
    else:
        cuerpo, dv = limpio[:-1], limpio[-1:]
    return cuerpo, dv


def _extraer_detalle(payload: dict) -> list[dict]:
    """Saca la lista de filas de la respuesta del SII (tolerante a la estructura)."""
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("detalle", "detalleCompra", "detalleVenta", "items", "rows"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


async def consultar(token: str, rut: str, anio: int, mes: int, registro: str,
                    ambiente: str = "certificacion") -> list[dict]:
    """Consulta el detalle del RCV (registro COMPRA|VENTA) de un período →
    lista de documentos normalizados. Devuelve [] si el SII no trae filas.

    AJUSTAR contra la respuesta real: la URL (`getDetalleCompra`/`getDetalleVenta`),
    el payload y `_CAMPOS`. La firma y el guardado no cambian."""
    base = _RCV_BASE.get(ambiente, _RCV_BASE["certificacion"])
    op = "COMPRA" if registro.upper() == "COMPRA" else "VENTA"
    metodo = "getDetalleCompra" if op == "COMPRA" else "getDetalleVenta"
    cuerpo, dv = _rut_partes(rut)
    periodo = f"{anio}{mes:02d}"
    payload = {
        "metaData": {"namespace": f"cl.sii.sdi.lob.diii.consdcv.data.api.interfaces.FacadeService/{metodo}",
                     "conversationId": "1", "transactionId": "1"},
        "data": {"rutEmisor": cuerpo, "dvEmisor": dv, "ptributario": periodo,
                 "operacion": op, "estadoContab": "REGISTRO"},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{base}/{metodo}", json=payload,
                                 headers={"Cookie": f"TOKEN={token}",
                                          "Content-Type": "application/json"})
        resp.raise_for_status()
        filas = _extraer_detalle(resp.json())
    docs = [_mapear_item(f, op) for f in filas]
    docs = [d for d in docs if d["numero_documento"] and d["fecha"]]
    logger.info(f"[sii-rcv] {op} {periodo}: {len(docs)} documentos")
    return docs
