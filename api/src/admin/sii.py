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
import random
from datetime import date, timedelta

from .. import config
from ..agents._common import to_float
from ..finanzas.conciliacion import conciliar_y_marcar
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
            from ..finanzas.categorizacion import aplicar as _aplicar_cat
            await _aplicar_cat(conn, tenant_id)        # categoriza por reglas de proveedor
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


async def conciliar(tenant_id: str, dias: int = 90) -> dict:
    """Cruza los DTE del tenant con su cartola y marca cobradas/pagadas → CxC/CxP
    reflejan lo realmente pendiente (camino sin ERP: SII + banco)."""
    if not t._TENANT_RE.match(tenant_id):
        raise AdminError("ID de empresa inválido.")
    async with config.raw_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(f'SET LOCAL search_path = "{tenant_id}", public')
            res = await conciliar_y_marcar(conn, date.today(), dias=dias)
    logger.info(f"[admin] conciliación {tenant_id}: {res}")
    return res


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


# ─────────────────────────────────────────────────────────────
# Datos de muestra (demo) — etiquetados para poder reemplazarlos por data real
#   DTE:        observaciones = 'mock'
#   movimientos: referencia    = 'MOCK'
# La carga real (RCV por cert / cartola subida) NO lleva esas etiquetas → "Limpiar
# muestra" borra solo lo mock y deja intacta la data real.
# ─────────────────────────────────────────────────────────────

_CLIENTES = ["Comercial Andes Ltda", "Distribuidora Sur SpA", "Servicios Norte SA", "Retail Pacífico EIRL"]
_PROVS    = ["Insumos Centro SpA", "Logística del Sur Ltda", "Energía y Gas SA", "Oficina Total EIRL"]


def _rut(rng) -> str:
    return f"{rng.randint(60,79)}.{rng.randint(100,999)}.{rng.randint(100,999)}-{rng.randint(0,9)}"


def _mes_menos(hoy: date, k: int) -> tuple[int, int]:
    tot = hoy.year * 12 + (hoy.month - 1) - k
    return tot // 12, tot % 12 + 1


def _gen_dtes_mock(hoy: date) -> list[dict]:
    """DTE de muestra: ventas (facturas/boletas) + compras de los últimos 3 meses."""
    rng = random.Random(20260613)
    docs, fv, fc = [], 9100, 8100
    for k in range(3):
        y, m = _mes_menos(hoy, k)
        dmax = hoy.day if k == 0 else 28
        if dmax < 1:
            continue
        for _ in range(3):
            neto = rng.randint(300, 2500) * 1000
            docs.append({"clase": "venta", "tipo": ("boleta" if rng.random() < 0.35 else "factura"),
                         "numero_documento": str(fv), "rut_contraparte": _rut(rng),
                         "proveedor": rng.choice(_CLIENTES), "fecha": date(y, m, rng.randint(1, dmax)),
                         "monto_neto": neto, "monto_iva": round(neto * 0.19), "monto_total": round(neto * 1.19)})
            fv += 1
        for _ in range(3):
            neto = rng.randint(150, 1500) * 1000
            docs.append({"clase": "compra", "tipo": "factura",
                         "numero_documento": str(fc), "rut_contraparte": _rut(rng),
                         "proveedor": rng.choice(_PROVS), "fecha": date(y, m, rng.randint(1, dmax)),
                         "monto_neto": neto, "monto_iva": round(neto * 0.19), "monto_total": round(neto * 1.19)})
            fc += 1
    return docs


def _filas(status: str) -> int:
    try:
        return int(status.rsplit(" ", 1)[-1])
    except ValueError:
        return 0


async def cargar_muestra_sii(tenant_id: str) -> dict:
    """Inserta DTE de muestra (etiquetados 'mock') en documentos_tributarios."""
    if not t._TENANT_RE.match(tenant_id):
        raise AdminError("ID de empresa inválido.")
    docs = _gen_dtes_mock(date.today())
    ins = 0
    async with config.raw_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(f'SET LOCAL search_path = "{tenant_id}", public')
            for d in docs:
                try:
                    r = await conn.execute(
                        "INSERT INTO documentos_tributarios (clase,tipo,numero_documento,rut_contraparte,"
                        "proveedor,fecha,monto_neto,monto_iva,monto_total,estado,observaciones) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'registrado','mock') "
                        "ON CONFLICT (clase,tipo,numero_documento,rut_contraparte) "
                        "WHERE numero_documento IS NOT NULL AND rut_contraparte IS NOT NULL DO NOTHING",
                        d["clase"], d["tipo"], d["numero_documento"], d["rut_contraparte"], d["proveedor"],
                        d["fecha"], d["monto_neto"], d["monto_iva"], d["monto_total"])
                except Exception as e:                       # noqa: BLE001
                    raise AdminError(f"No se pudo cargar la muestra SII en '{tenant_id}': {e}")
                ins += _filas(r)
    logger.info(f"[admin] muestra SII en {tenant_id}: {ins}/{len(docs)} DTE")
    return {"documentos": len(docs), "insertados": ins}


async def cargar_muestra_banco(tenant_id: str) -> dict:
    """Genera movimientos bancarios (etiquetados 'MOCK') que calzan con un subconjunto
    de los DTE → la conciliación matchea y CxC/CxP reflejan lo pendiente. Reemplaza la
    muestra de banco previa. Requiere DTE cargados."""
    if not t._TENANT_RE.match(tenant_id):
        raise AdminError("ID de empresa inválido.")
    rng = random.Random(7720)
    hoy = date.today()
    movs: list = []
    async with config.raw_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(f'SET LOCAL search_path = "{tenant_id}", public')
            try:
                docs = await conn.fetch(
                    "SELECT clase, fecha, monto_total, proveedor FROM documentos_tributarios "
                    "WHERE clase IN ('venta','compra') AND fecha <= $1 "
                    "AND LOWER(COALESCE(estado,'')) NOT IN ('anulado','anulada','rechazado','rechazada') "
                    "ORDER BY fecha", hoy)
            except Exception:                                # noqa: BLE001
                raise AdminError("Cargá primero los datos de muestra del SII.")
            if not docs:
                raise AdminError("No hay DTE para conciliar; cargá la muestra del SII primero.")
            await conn.execute("DELETE FROM movimientos_bancarios WHERE referencia = 'MOCK'")
            for d in docs:
                edad = (hoy - d["fecha"]).days
                prob = 0.9 if edad > 30 else 0.55 if edad >= 7 else 0.2
                if rng.random() > prob:
                    continue
                fpago = d["fecha"] + timedelta(days=rng.randint(2, max(2, min(edad, 45))))
                if fpago > hoy:
                    fpago = hoy
                signo = 1 if d["clase"] == "venta" else -1
                glosa = ("Cobro " if signo > 0 else "Pago ") + (d["proveedor"] or "")
                movs.append((fpago, glosa[:200], round(signo * to_float(d["monto_total"]), 2)))
            for f, g, mt in movs:
                await conn.execute(
                    "INSERT INTO movimientos_bancarios (fecha,glosa,monto,referencia) VALUES ($1,$2,$3,'MOCK')",
                    f, g, mt)
    logger.info(f"[admin] muestra banco en {tenant_id}: {len(movs)} movimientos")
    return {"movimientos": len(movs)}


async def limpiar_muestra(tenant_id: str) -> dict:
    """Borra SOLO la data de muestra (DTE 'mock' + movimientos 'MOCK'); la data real
    (RCV por cert / cartola subida) queda intacta."""
    if not t._TENANT_RE.match(tenant_id):
        raise AdminError("ID de empresa inválido.")
    async with config.raw_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(f'SET LOCAL search_path = "{tenant_id}", public')
            try:
                d1 = await conn.execute("DELETE FROM documentos_tributarios WHERE observaciones = 'mock'")
            except Exception:                                # noqa: BLE001
                d1 = "DELETE 0"
            d2 = await conn.execute("DELETE FROM movimientos_bancarios WHERE referencia = 'MOCK'")
    return {"documentos": _filas(d1), "movimientos": _filas(d2)}
