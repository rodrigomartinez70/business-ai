"""
Integración Meta Ads (Marketing API / Graph API) — solo INSIGHTS de performance.

Trae campañas y sus métricas diarias (gasto, impresiones, clics, alcance,
conversiones) de una cuenta publicitaria de Meta y las guarda en el esquema de
marketing del tenant (tablas `canales_marketing`, `campanas`, `insights_marketing`).

- Credenciales por tenant en `public.integraciones` (proveedor='meta').
- Modo `mock=True`: genera datos de muestra sin llamar a la API (para desarrollar
  el pipeline antes de tener el token real).
- Ingesta idempotente: upsert por id externo de campaña y por (campaña, fecha).

NO trae Lead Ads (sin PII en esta integración). El access_token nunca se loguea.
"""

import logging
import random
from datetime import date, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GRAPH_VERSION = "v21.0"
_BASE = "https://graph.facebook.com"

# action_types de Meta que contamos como "conversión" (leads).
_CONVERSION_ACTIONS = {
    "lead",
    "onsite_conversion.lead_grouped",
    "offsite_conversion.fb_pixel_lead",
    "leadgen_grouped",
}


# ─────────────────────────────────────────────────────────────
# Credenciales
# ─────────────────────────────────────────────────────────────

async def obtener_credenciales(conn, tenant_id: str) -> Optional[dict]:
    """Lee las credenciales de Meta del tenant desde public.integraciones."""
    row = await conn.fetchrow(
        """SELECT access_token, cuenta_id, config
             FROM public.integraciones
            WHERE tenant_id = $1 AND proveedor = 'meta' AND activo = TRUE""",
        tenant_id,
    )
    if not row or not row["access_token"] or not row["cuenta_id"]:
        return None
    return {"access_token": row["access_token"], "cuenta_id": row["cuenta_id"],
            "config": row["config"] or {}}


# ─────────────────────────────────────────────────────────────
# Llamadas a la Graph API (con paginación)
# ─────────────────────────────────────────────────────────────

async def _fetch_paginado(client: httpx.AsyncClient, url: str, params: dict) -> list[dict]:
    """GET con seguimiento de paginación (paging.next). Acumula todos los `data`."""
    filas: list[dict] = []
    while True:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        body = resp.json()
        filas.extend(body.get("data", []))
        siguiente = body.get("paging", {}).get("next")
        if not siguiente:
            break
        url, params = siguiente, {}  # `next` ya trae todos los query params
    return filas


async def fetch_campanas(creds: dict, version: str = GRAPH_VERSION) -> list[dict]:
    cuenta = creds["cuenta_id"]
    url = f"{_BASE}/{version}/{cuenta}/campaigns"
    params = {
        "fields": "id,name,objective,status,daily_budget,start_time,stop_time",
        "access_token": creds["access_token"],
        "limit": 200,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        return await _fetch_paginado(client, url, params)


async def fetch_insights(creds: dict, desde: date, hasta: date,
                         version: str = GRAPH_VERSION) -> list[dict]:
    cuenta = creds["cuenta_id"]
    url = f"{_BASE}/{version}/{cuenta}/insights"
    params = {
        "level": "campaign",
        "time_increment": 1,  # un registro por día
        "time_range": f'{{"since":"{desde:%Y-%m-%d}","until":"{hasta:%Y-%m-%d}"}}',
        "fields": "campaign_id,spend,impressions,clicks,reach,actions,account_currency",
        "access_token": creds["access_token"],
        "limit": 500,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        return await _fetch_paginado(client, url, params)


# ─────────────────────────────────────────────────────────────
# Parseo (Graph API → filas normalizadas)
# ─────────────────────────────────────────────────────────────

def _parse_campana(raw: dict) -> dict:
    def _fecha(v):
        return v[:10] if v else None
    daily = raw.get("daily_budget")
    return {
        "id_externo": raw["id"],
        "nombre": raw.get("name", ""),
        "objetivo": raw.get("objective"),
        "estado": raw.get("status"),
        # daily_budget viene en la unidad menor de la moneda (centavos) → a unidad.
        "presupuesto_diario": (float(daily) / 100) if daily else None,
        "fecha_inicio": _fecha(raw.get("start_time")),
        "fecha_fin": _fecha(raw.get("stop_time")),
    }


def _conversiones_de_actions(actions) -> float:
    if not actions:
        return 0.0
    total = 0.0
    for a in actions:
        if a.get("action_type") in _CONVERSION_ACTIONS:
            try:
                total += float(a.get("value", 0))
            except (TypeError, ValueError):
                pass
    return total


def _parse_insight(raw: dict) -> dict:
    return {
        "campana_externa": raw.get("campaign_id"),
        "fecha": raw.get("date_start"),
        "gasto": float(raw.get("spend", 0) or 0),
        "impresiones": int(raw.get("impressions", 0) or 0),
        "clics": int(raw.get("clicks", 0) or 0),
        "alcance": int(raw.get("reach", 0) or 0),
        "conversiones": _conversiones_de_actions(raw.get("actions")),
        "moneda": raw.get("account_currency", "CLP"),
    }


# ─────────────────────────────────────────────────────────────
# Datos de muestra (modo mock, sin API)
# ─────────────────────────────────────────────────────────────

def _mock_campanas() -> list[dict]:
    return [
        {"id": "23851000000000001", "name": "Proyecto Mirador — Leads",
         "objective": "OUTCOME_LEADS", "status": "ACTIVE", "daily_budget": "5000000",
         "start_time": "2026-03-01T00:00:00-0300", "stop_time": None},
        {"id": "23851000000000002", "name": "Proyecto Costanera — Tráfico",
         "objective": "OUTCOME_TRAFFIC", "status": "ACTIVE", "daily_budget": "3000000",
         "start_time": "2026-04-01T00:00:00-0300", "stop_time": None},
        {"id": "23851000000000003", "name": "Remarketing — Visitantes web",
         "objective": "OUTCOME_LEADS", "status": "PAUSED", "daily_budget": "2000000",
         "start_time": "2026-02-15T00:00:00-0300", "stop_time": None},
    ]


def _mock_insights(desde: date, hasta: date, campanas: list[dict]) -> list[dict]:
    rng = random.Random(42)  # determinista
    filas: list[dict] = []
    dia = desde
    while dia <= hasta:
        for c in campanas:
            if c["status"] != "ACTIVE":
                continue
            base = rng.randint(30000, 60000)
            impresiones = rng.randint(8000, 25000)
            clics = int(impresiones * rng.uniform(0.01, 0.04))
            leads = int(clics * rng.uniform(0.03, 0.10))
            filas.append({
                "campaign_id": c["id"],
                "date_start": dia.isoformat(),
                "spend": str(base),
                "impressions": str(impresiones),
                "clicks": str(clics),
                "reach": str(int(impresiones * rng.uniform(0.6, 0.9))),
                "actions": [{"action_type": "lead", "value": str(leads)}],
                "account_currency": "CLP",
            })
        dia += timedelta(days=1)
    return filas


# ─────────────────────────────────────────────────────────────
# Ingesta (upsert idempotente)
# ─────────────────────────────────────────────────────────────

async def _canal_meta_id(conn) -> int:
    await conn.execute(
        """INSERT INTO canales_marketing (nombre, tipo, plataforma)
           VALUES ('Meta', 'pagado', 'meta') ON CONFLICT (nombre) DO NOTHING""")
    return await conn.fetchval("SELECT id FROM canales_marketing WHERE nombre='Meta'")


async def _upsert_campana(conn, canal_id: int, c: dict) -> int:
    return await conn.fetchval(
        """INSERT INTO campanas
               (canal_id, id_externo, nombre, objetivo, estado,
                presupuesto_diario, fecha_inicio, fecha_fin, actualizado_en)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8, CURRENT_TIMESTAMP)
           ON CONFLICT (id_externo) DO UPDATE SET
               nombre = EXCLUDED.nombre, objetivo = EXCLUDED.objetivo,
               estado = EXCLUDED.estado, presupuesto_diario = EXCLUDED.presupuesto_diario,
               fecha_inicio = EXCLUDED.fecha_inicio, fecha_fin = EXCLUDED.fecha_fin,
               actualizado_en = CURRENT_TIMESTAMP
           RETURNING id""",
        canal_id, c["id_externo"], c["nombre"], c["objetivo"], c["estado"],
        c["presupuesto_diario"], c["fecha_inicio"], c["fecha_fin"],
    )


async def _upsert_insight(conn, campana_id: int, ins: dict) -> None:
    await conn.execute(
        """INSERT INTO insights_marketing
               (campana_id, fecha, gasto, impresiones, clics, alcance,
                conversiones, moneda, actualizado_en)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8, CURRENT_TIMESTAMP)
           ON CONFLICT (campana_id, fecha) DO UPDATE SET
               gasto = EXCLUDED.gasto, impresiones = EXCLUDED.impresiones,
               clics = EXCLUDED.clics, alcance = EXCLUDED.alcance,
               conversiones = EXCLUDED.conversiones, moneda = EXCLUDED.moneda,
               actualizado_en = CURRENT_TIMESTAMP""",
        campana_id, ins["fecha"], ins["gasto"], ins["impresiones"], ins["clics"],
        ins["alcance"], ins["conversiones"], ins["moneda"],
    )


async def sincronizar(conn, tenant_id: str, desde: date, hasta: date,
                      *, mock: bool = False) -> dict:
    """Sincroniza campañas + insights de Meta al esquema de marketing del tenant.

    Requiere que `conn` tenga el search_path en el schema del tenant + public.
    Devuelve un resumen con los conteos. NUNCA loguea el access_token.
    """
    if mock:
        camp_raw = _mock_campanas()
        ins_raw = _mock_insights(desde, hasta, camp_raw)
        logger.info(f"[meta_ads] modo MOCK para '{tenant_id}'")
    else:
        creds = await obtener_credenciales(conn, tenant_id)
        if not creds:
            raise RuntimeError(
                f"Sin credenciales de Meta para '{tenant_id}'. Cargá token y cuenta_id "
                f"en public.integraciones (proveedor='meta') o usá mock=True.")
        camp_raw = await fetch_campanas(creds)
        ins_raw = await fetch_insights(creds, desde, hasta)
        logger.info(f"[meta_ads] '{tenant_id}': {len(camp_raw)} campañas, "
                    f"{len(ins_raw)} registros de insights desde la API")

    canal_id = await _canal_meta_id(conn)

    externo_a_id: dict[str, int] = {}
    for raw in camp_raw:
        c = _parse_campana(raw)
        externo_a_id[c["id_externo"]] = await _upsert_campana(conn, canal_id, c)

    insertados = 0
    for raw in ins_raw:
        ins = _parse_insight(raw)
        campana_id = externo_a_id.get(ins["campana_externa"])
        if campana_id is None:
            continue  # insight de una campaña que no vino en el listado
        await _upsert_insight(conn, campana_id, ins)
        insertados += 1

    return {"tenant": tenant_id, "campanas": len(externo_a_id),
            "insights": insertados, "desde": str(desde), "hasta": str(hasta),
            "modo": "mock" if mock else "api"}
