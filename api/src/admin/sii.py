"""
SII por tenant (back-office MBI Admin) — capacidades activables "bajo request" +
carga del RCV (Fase A, sin certificado).

Las capacidades SII se guardan en `config.sii` (JSONB del tenant), como los toggles
de módulos. La carga de RCV usa `finanzas.rcv.normalizar_rcv` y hace upsert en
`documentos_tributarios` del schema del tenant (vía raw_pool + search_path).
"""

import json
import logging

from .. import config
from ..finanzas.rcv import normalizar_rcv
from . import tenants as t

logger = logging.getLogger(__name__)

AdminError = t.AdminError

# Capacidades del SII (clave, título, descripción, default). default=False = "bajo
# request"; estado_dte queda True para no cambiar el comportamiento actual.
CAPS = [
    {"clave": "rcv", "titulo": "Carga de RCV (Compras y Ventas)",
     "desc": "Subí el CSV que bajás del portal del SII → IVA real, sin certificado.",
     "default": False},
    {"clave": "estado_dte", "titulo": "Estado de DTE",
     "desc": "Muestra en el informe los DTE del mes que no están en estado DOK.",
     "default": True},
]
_DEFAULTS = {c["clave"]: c["default"] for c in CAPS}


def activa(cfg: dict, clave: str) -> bool:
    """Si una capacidad SII está activa para un tenant (con su default)."""
    return ((cfg or {}).get("sii") or {}).get(clave, _DEFAULTS.get(clave, False))


async def estado(tenant_id: str) -> dict:
    cfg = await t._cargar_config_efectivo(tenant_id)
    return {"tenant_id": tenant_id,
            "sii_caps": [{**c, "activo": activa(cfg, c["clave"])} for c in CAPS]}


async def set_cap(tenant_id: str, clave: str, activo: bool) -> None:
    if clave not in _DEFAULTS:
        raise AdminError(f"Capacidad SII desconocida: {clave}.")
    cfg = await t._cargar_config_efectivo(tenant_id)
    cfg.setdefault("sii", {})[clave] = activo
    await config.raw_pool.execute(
        "UPDATE public.tenants SET config = $2::jsonb WHERE id = $1",
        tenant_id, json.dumps(cfg))
    await t._recargar_registry()
    logger.info(f"[admin] {tenant_id} SII {clave} → {'on' if activo else 'off'}")


_UPSERT = """
INSERT INTO documentos_tributarios
    (clase, tipo, numero_documento, rut_contraparte, proveedor,
     fecha, monto_neto, monto_iva, monto_total, estado)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'registrado')
ON CONFLICT (clase, tipo, numero_documento, rut_contraparte)
    WHERE numero_documento IS NOT NULL AND rut_contraparte IS NOT NULL
DO UPDATE SET monto_neto = EXCLUDED.monto_neto, monto_iva = EXCLUDED.monto_iva,
              monto_total = EXCLUDED.monto_total, fecha = EXCLUDED.fecha,
              proveedor = EXCLUDED.proveedor, estado = 'registrado', updated_at = now()
RETURNING (xmax = 0)
"""


async def subir_rcv(tenant_id: str, contenido: bytes, modo: str = "insertar") -> dict:
    """Normaliza el RCV y (modo insertar) hace upsert en documentos_tributarios del
    tenant. `normalizar_rcv` puede lanzar ValueError (CSV inválido)."""
    if not t._TENANT_RE.match(tenant_id):
        raise AdminError("ID de empresa inválido.")
    res = normalizar_rcv(contenido)
    docs = res["documentos"]
    if not docs:
        raise AdminError("No se detectaron documentos en el RCV.")
    if modo == "validar":
        return {"modo": "validar", **res["meta"], "preview": docs[:5]}

    if not await config.raw_pool.fetchval("SELECT 1 FROM public.tenants WHERE id = $1", tenant_id):
        raise AdminError(f"No existe la empresa '{tenant_id}'.")

    insertados = actualizados = 0
    async with config.raw_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(f'SET LOCAL search_path = "{tenant_id}"')
            for d in docs:
                try:
                    nuevo = await conn.fetchval(
                        _UPSERT, d["clase"], d["tipo"], d["numero_documento"],
                        d["rut_contraparte"], d["proveedor"], d["fecha"],
                        d["monto_neto"], d["monto_iva"], d["monto_total"])
                except Exception as e:                       # noqa: BLE001
                    raise AdminError(f"No se pudo cargar en '{tenant_id}': {e}")
                insertados += 1 if nuevo else 0
                actualizados += 0 if nuevo else 1
    logger.info(f"[admin] RCV {res['meta']['clase']} cargado en {tenant_id}: "
                f"{insertados} nuevos, {actualizados} actualizados")
    return {"modo": "insertar", "insertados": insertados, "actualizados": actualizados,
            **res["meta"]}
