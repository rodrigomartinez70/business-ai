"""
Integración SII — Estado de DTE (Chile).

Sección agéntica que verifica el estado de los DTE del mes en curso en el SII y
lista los que NO están en 'DOK' (Documento Recibido OK, datos coinciden).

Flujo real (mock-first por ahora — requiere certificado digital de la empresa):
  1. Autenticación automática: CrSeed.jws (semilla) → firmar la semilla con el
     Certificado Digital → GetTokenFromSeed.jws (Token).
       Cert:  https://maullin.sii.cl/DTEWS/...    Prod: https://palena.sii.cl/DTEWS/...
  2. Fuente de los DTE del período: Consulta RCV (Registro de Compras y Ventas).
  3. Por cada DTE, estado vía QueryEstDteAv (getEstDteAv) → RESP_BODY/ESTADO.

Estados (RESP_BODY/ESTADO del WS QueryEstDteAv): 'DOK' = OK; el resto = a revisar.
"""

import logging
import random
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Ambientes SII (Web Services DTE).
SII_PROD = "https://palena.sii.cl/DTEWS"
SII_CERT = "https://maullin.sii.cl/DTEWS"

ESTADO_OK = "DOK"

# RESP_BODY/ESTADO de QueryEstDteAv (manual SII OIFE2006_QueryEstDteAv).
ESTADOS_DTE = {
    "DOK": "Documento recibido por el SII; datos coinciden con los registrados",
    "DNK": "Documento recibido por el SII pero los datos NO coinciden",
    "FNA": "Documento no autorizado",
    "FAN": "Folio anulado",
    "FAU": "Folio autorizado pero no utilizado / documento no enviado",
    "EMP": "Empresa no autorizada a emitir documentos tributarios electrónicos",
    "TMD": "Existe Nota de Débito que modifica textos del documento",
    "TMC": "Existe Nota de Crédito que modifica textos del documento",
    "MMD": "Existe Nota de Débito que modifica montos del documento",
    "MMC": "Existe Nota de Crédito que modifica montos del documento",
    "AND": "Existe Nota de Débito que anula el documento",
    "ANC": "Existe Nota de Crédito que anula el documento",
}

# Nombres legibles de tipos de DTE del SII.
TIPOS_DTE = {33: "Factura electrónica", 34: "Factura exenta", 39: "Boleta electrónica",
             41: "Boleta exenta", 56: "Nota de débito", 61: "Nota de crédito",
             52: "Guía de despacho"}


# ─────────────────────────────────────────────────────────────
# Credenciales / autenticación
# ─────────────────────────────────────────────────────────────

async def obtener_credenciales(conn, tenant_id: str):
    row = await conn.fetchrow(
        """SELECT access_token, cuenta_id, config FROM public.integraciones
            WHERE tenant_id=$1 AND proveedor='sii' AND activo=TRUE""", tenant_id)
    if not row:
        return None
    cfg = row["config"] or {}
    if isinstance(cfg, str):
        import json
        cfg = json.loads(cfg)
    return {"cert": row["access_token"], "rut_empresa": row["cuenta_id"], "config": cfg}


async def obtener_token(creds: dict) -> str:
    """Autenticación automática SII: CrSeed → firmar semilla con cert → GetTokenFromSeed.
    Pendiente de implementar con el certificado digital real (firma XML-DSig de la semilla)."""
    raise NotImplementedError(
        "Autenticación SII real pendiente: requiere certificado digital para firmar la "
        "semilla (CrSeed → firma → GetTokenFromSeed). Usar mock=True por ahora.")


# ─────────────────────────────────────────────────────────────
# Datos de muestra (mock)
# ─────────────────────────────────────────────────────────────

def _mock_dtes(desde: date, hasta: date) -> list[dict]:
    """DTE del período con estado SII. Determinístico por mes (idempotente)."""
    rng = random.Random(int(desde.strftime("%Y%m")))
    tipos = [33, 39, 61, 56]
    no_dok = ["DNK", "FAU", "FAN", "MMC", "ANC", "FNA"]
    dtes = []
    n = rng.randint(25, 45)
    dia_span = max((hasta - desde).days, 1)
    for i in range(n):
        # ~85% DOK, ~15% con algún reparo
        estado = ESTADO_OK if rng.random() < 0.85 else rng.choice(no_dok)
        tipo = rng.choice(tipos)
        dtes.append({
            "tipo": tipo,
            "folio": 100000 + i,
            "rut": f"7{rng.randint(1000000, 9999999)}-{rng.randint(0,9)}",
            "razon_social": rng.choice(["Proveedor Andes SpA", "Distribuidora Sur Ltda",
                                        "Insumos Gastronómicos SA", "Bebidas del Maipo SpA",
                                        "Cliente Final"]),
            "fecha": str(desde.replace(day=1) + timedelta(days=rng.randint(0, dia_span))),
            "monto": rng.randint(15000, 1200000),
            "estado": estado,
        })
    return dtes


# ─────────────────────────────────────────────────────────────
# Agente: verificar estado DTE del mes en curso
# ─────────────────────────────────────────────────────────────

async def obtener_dtes_periodo(conn, tenant_id, desde, hasta, *, mock=False) -> list[dict]:
    """Lista los DTE del período con su estado SII. mock=True genera datos de muestra;
    el camino real consulta el RCV + QueryEstDteAv (pendiente: certificado)."""
    if mock:
        return _mock_dtes(desde, hasta)
    creds = await obtener_credenciales(conn, tenant_id)
    if not creds:
        raise RuntimeError("Sin credenciales SII para el tenant (certificado digital). Usá mock=True.")
    raise NotImplementedError("Consulta RCV + QueryEstDteAv real pendiente (requiere token con certificado).")


async def verificar_estado_dte(conn, tenant_id: str, hasta: date, *, mock: bool = False) -> dict:
    """Agente: del mes en curso, cuántos DTE ≠ DOK y el listado de esos documentos."""
    desde = hasta.replace(day=1)
    dtes = await obtener_dtes_periodo(conn, tenant_id, desde, hasta, mock=mock)

    por_estado: dict[str, int] = {}
    listado: list[dict] = []
    for d in dtes:
        est = d.get("estado", "")
        por_estado[est] = por_estado.get(est, 0) + 1
        if est != ESTADO_OK:
            listado.append({
                "tipo": TIPOS_DTE.get(d["tipo"], str(d["tipo"])),
                "folio": d["folio"], "rut": d["rut"], "razon_social": d.get("razon_social", ""),
                "fecha": d["fecha"], "monto": d["monto"],
                "estado": est, "glosa": ESTADOS_DTE.get(est, "Estado desconocido"),
            })
    listado.sort(key=lambda x: x["fecha"])
    total = len(dtes)
    return {
        "periodo": {"desde": str(desde), "hasta": str(hasta), "mes": desde.strftime("%Y-%m")},
        "total": total,
        "dok": por_estado.get(ESTADO_OK, 0),
        "no_dok": total - por_estado.get(ESTADO_OK, 0),
        "por_estado": por_estado,
        "listado": listado,
        "modo": "mock" if mock else "api",
    }


# ─────────────────────────────────────────────────────────────
# Render
# ─────────────────────────────────────────────────────────────

def renderizar_estado_dte_html(data: dict, cfg: dict) -> str:
    from src.render import _card, _kpis, _fm, _aviso
    r = data
    sem = "🟢" if r["no_dok"] == 0 else ("🟠" if r["no_dok"] <= 3 else "🔴")
    rows = [
        ("Período", r["periodo"]["mes"]),
        ("DTE del período", str(r["total"])),
        (f"En estado DOK", f"{r['dok']}"),
        (f"Con reparos (≠ DOK) {sem}", f"{r['no_dok']}"),
    ]
    body = _kpis(rows)
    if r["listado"]:
        filas = ""
        for d in r["listado"]:
            filas += (f'<tr><td>{d["estado"]}</td><td>{d["tipo"]}</td>'
                      f'<td style="text-align:right;">{d["folio"]}</td>'
                      f'<td>{d["razon_social"][:24]}</td><td>{d["fecha"][5:]}</td>'
                      f'<td>{_fm(d["monto"], cfg)}</td><td>{d["glosa"]}</td></tr>')
        body += (f'<table class="dt"><tr><th>Estado</th><th>Tipo</th><th>Folio</th>'
                 f'<th>Contraparte</th><th>Fecha</th><th>Monto</th><th>Detalle</th></tr>{filas}</table>')
    else:
        body += _aviso("info", "Todos los DTE del mes están en DOK", "Sin reparos en el SII.")
    return _card("📋 Estado DTE en el SII — mes en curso", body)
