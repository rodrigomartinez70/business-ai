"""
SII por tenant (back-office MBI Admin) — capacidades activables "bajo request" +
carga del RCV (Fase A, sin certificado).

Las capacidades SII se guardan en `config.sii` (JSONB del tenant), como los toggles
de módulos. La carga de RCV usa `finanzas.rcv.normalizar_rcv` y hace upsert en
`documentos_tributarios` del schema del tenant (vía raw_pool + search_path).
"""

import base64
import json
import logging

from .. import config
from ..finanzas.rcv import normalizar_rcv
from ..integraciones import sii_auth, sii_rcv_api
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

    async with config.raw_pool.acquire() as conn:
        async with conn.transaction():
            insertados, actualizados = await _upsert_docs(conn, tenant_id, docs)
    logger.info(f"[admin] RCV {res['meta']['clase']} cargado en {tenant_id}: "
                f"{insertados} nuevos, {actualizados} actualizados")
    return {"modo": "insertar", "insertados": insertados, "actualizados": actualizados,
            **res["meta"]}


async def _upsert_docs(conn, tenant_id: str, docs: list[dict]) -> tuple[int, int]:
    """Upsert idempotente de documentos en el schema del tenant. Devuelve
    (insertados, actualizados). Reusado por la carga CSV y por la sync del SII."""
    insertados = actualizados = 0
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
    return insertados, actualizados


async def _token_cert(tenant_id: str) -> tuple[str, str, str]:
    """(token, rut, ambiente) del certificado SII guardado. Lanza AdminError si no hay."""
    row = await config.raw_pool.fetchrow(
        "SELECT access_token, cuenta_id, config FROM public.integraciones "
        "WHERE tenant_id = $1 AND proveedor = 'sii'", tenant_id)
    if not row or not row["access_token"]:
        raise AdminError("No hay certificado SII cargado para esta empresa.")
    cfg = row["config"] if isinstance(row["config"], dict) else json.loads(row["config"] or "{}")
    ambiente = cfg.get("ambiente", "certificacion")
    rut = cfg.get("rut") or row["cuenta_id"] or ""
    token = await sii_auth.obtener_token(
        base64.b64decode(row["access_token"]), cfg.get("password", ""), ambiente)
    return token, rut, ambiente


async def _sync_periodo(tenant_id: str, token: str, rut: str, ambiente: str,
                        anio: int, mes: int) -> dict:
    """Consulta RCV de un período (con un token ya obtenido) → upsert."""
    recibidos = await sii_rcv_api.consultar(token, rut, anio, mes, "COMPRA", ambiente)
    emitidos  = await sii_rcv_api.consultar(token, rut, anio, mes, "VENTA", ambiente)
    docs = recibidos + emitidos
    insertados = actualizados = 0
    if docs:
        async with config.raw_pool.acquire() as conn:
            async with conn.transaction():
                insertados, actualizados = await _upsert_docs(conn, tenant_id, docs)
    return {"recibidos": len(recibidos), "emitidos": len(emitidos),
            "insertados": insertados, "actualizados": actualizados}


def _iter_periodos(anio_d: int, mes_d: int, anio_h: int, mes_h: int):
    """(anio, mes) desde→hasta inclusive."""
    cur, fin = anio_d * 12 + (mes_d - 1), anio_h * 12 + (mes_h - 1)
    while cur <= fin:
        yield cur // 12, cur % 12 + 1
        cur += 1


async def sincronizar_rcv(tenant_id: str, anio: int, mes: int) -> dict:
    """Fase B paso 2: token SII → consulta RCV (recibidos+emitidos) del período →
    upsert. Re-ejecutar un período cerrado lo actualiza (upsert idempotente)."""
    if not t._TENANT_RE.match(tenant_id):
        raise AdminError("ID de empresa inválido.")
    token, rut, ambiente = await _token_cert(tenant_id)
    r = await _sync_periodo(tenant_id, token, rut, ambiente, anio, mes)
    logger.info(f"[admin] RCV SII {tenant_id} {anio}-{mes}: {r}")
    return {"periodo": f"{anio}-{mes:02d}", **r}


async def sincronizar_rcv_rango(tenant_id: str, anio_d: int, mes_d: int,
                                anio_h: int, mes_h: int) -> dict:
    """Backfill: trae el RCV de todos los meses del rango con UN solo token. Útil
    para la carga histórica inicial (año actual + anterior). Upsert idempotente."""
    if not t._TENANT_RE.match(tenant_id):
        raise AdminError("ID de empresa inválido.")
    if not (1 <= mes_d <= 12 and 1 <= mes_h <= 12):
        raise AdminError("Período inválido.")
    if anio_h * 12 + mes_h < anio_d * 12 + mes_d:
        raise AdminError("El período 'desde' debe ser anterior o igual a 'hasta'.")
    if (anio_h * 12 + mes_h) - (anio_d * 12 + mes_d) > 35:
        raise AdminError("Rango máximo: 36 meses.")

    token, rut, ambiente = await _token_cert(tenant_id)          # una sola vez
    tot = {"periodos": 0, "recibidos": 0, "emitidos": 0, "insertados": 0, "actualizados": 0}
    for anio, mes in _iter_periodos(anio_d, mes_d, anio_h, mes_h):
        r = await _sync_periodo(tenant_id, token, rut, ambiente, anio, mes)
        tot["periodos"] += 1
        for k in ("recibidos", "emitidos", "insertados", "actualizados"):
            tot[k] += r[k]
    logger.info(f"[admin] backfill RCV {tenant_id} {anio_d}-{mes_d}→{anio_h}-{mes_h}: {tot}")
    return {"desde": f"{anio_d}-{mes_d:02d}", "hasta": f"{anio_h}-{mes_h:02d}", **tot}


# ─────────────────────────────────────────────────────────────
# Certificado SII (Fase B) — guardar en public.integraciones (proveedor='sii')
# ─────────────────────────────────────────────────────────────

async def cert_estado(tenant_id: str) -> dict | None:
    """Info (no sensible) del certificado SII cargado, o None."""
    row = await config.raw_pool.fetchrow(
        "SELECT cuenta_id, config FROM public.integraciones "
        "WHERE tenant_id = $1 AND proveedor = 'sii'", tenant_id)
    if not row:
        return None
    cfg = row["config"] if isinstance(row["config"], dict) else json.loads(row["config"] or "{}")
    return {"rut": cfg.get("rut") or row["cuenta_id"] or "—",
            "titular": cfg.get("titular", ""), "vence": cfg.get("vence", ""),
            "ambiente": cfg.get("ambiente", "certificacion")}


async def guardar_cert(tenant_id: str, pfx_bytes: bytes, password: str,
                       rut: str, ambiente: str) -> dict:
    """Valida que el .pfx abre con su clave y lo guarda (base64) + metadata."""
    if not t._TENANT_RE.match(tenant_id):
        raise AdminError("ID de empresa inválido.")
    if ambiente not in sii_auth.AMBIENTES:
        ambiente = "certificacion"
    _key, cert = sii_auth.cargar_pfx(pfx_bytes, password)     # SiiAuthError si falla
    info = sii_auth.info_cert(cert)
    cfg = {"password": password, "ambiente": ambiente,
           "rut": (rut or info.get("rut") or "").strip(),
           "titular": info.get("titular", ""), "vence": info.get("vence", "")}
    await config.raw_pool.execute(
        """INSERT INTO public.integraciones
               (tenant_id, proveedor, access_token, cuenta_id, config, activo, actualizado_en)
           VALUES ($1, 'sii', $2, $3, $4::jsonb, TRUE, now())
           ON CONFLICT (tenant_id, proveedor) DO UPDATE
               SET access_token = EXCLUDED.access_token, cuenta_id = EXCLUDED.cuenta_id,
                   config = EXCLUDED.config, activo = TRUE, actualizado_en = now()""",
        tenant_id, base64.b64encode(pfx_bytes).decode(), cfg["rut"], json.dumps(cfg))
    logger.info(f"[admin] cert SII guardado para {tenant_id} ({cfg['ambiente']})")
    return info


async def probar_conexion(tenant_id: str) -> str:
    """Carga el cert guardado y obtiene un token del SII (CrSeed→firma→GetToken).
    Devuelve un prefijo del token. Lanza AdminError/SiiAuthError con el detalle."""
    row = await config.raw_pool.fetchrow(
        "SELECT access_token, config FROM public.integraciones "
        "WHERE tenant_id = $1 AND proveedor = 'sii'", tenant_id)
    if not row or not row["access_token"]:
        raise AdminError("No hay certificado SII cargado para esta empresa.")
    cfg = row["config"] if isinstance(row["config"], dict) else json.loads(row["config"] or "{}")
    token = await sii_auth.obtener_token(
        base64.b64decode(row["access_token"]), cfg.get("password", ""),
        cfg.get("ambiente", "certificacion"))
    return token
