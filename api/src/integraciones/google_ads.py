"""
Integración Google Ads — capa de conexión (Marketing).

Trae campañas y sus métricas diarias (costo, impresiones, clics, conversiones)
hacia el MISMO modelo de marketing que Meta Ads (canales_marketing / campanas /
insights_marketing), con `plataforma='google'`. Así el módulo de Marketing agrega
ambas plataformas sin cambios (el dashboard no filtra por plataforma).

- Modo `mock=True`: genera datos de muestra sin llamar a la API (para desarrollar
  y ver el dashboard combinado Meta+Google).
- Modo real: requiere credenciales OAuth2 + developer token (ver `sincronizar`);
  pendiente de cablear, igual que el resto de los conectores mock-first.

NUNCA loguea el refresh token / credenciales.
"""

import logging
import random
from datetime import date, datetime, timedelta
from typing import Optional

# Writers compartidos del esquema de marketing (única fuente de verdad de los upsert).
from .meta_ads import _upsert_campana, _upsert_insight

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Credenciales
# ─────────────────────────────────────────────────────────────

async def obtener_credenciales(conn, tenant_id: str) -> Optional[dict]:
    """Lee las credenciales de Google Ads del tenant desde public.integraciones."""
    row = await conn.fetchrow(
        """SELECT access_token, cuenta_id, config
             FROM public.integraciones
            WHERE tenant_id = $1 AND proveedor = 'google_ads' AND activo = TRUE""",
        tenant_id,
    )
    if not row or not row["access_token"] or not row["cuenta_id"]:
        return None
    return {"refresh_token": row["access_token"], "cuenta_id": row["cuenta_id"],
            "config": row["config"] or {}}


# ─────────────────────────────────────────────────────────────
# Parseo (Google Ads → filas normalizadas, mismo shape que Meta)
# ─────────────────────────────────────────────────────────────

def _to_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def _parse_campana(raw: dict) -> dict:
    # En Google Ads el presupuesto viene en "micros" (1 unidad = 1.000.000 micros).
    micros = raw.get("budget_micros")
    return {
        "id_externo": str(raw["id"]),
        "nombre": raw.get("name", ""),
        "objetivo": raw.get("channel_type"),      # SEARCH / DISPLAY / PERFORMANCE_MAX…
        "estado": raw.get("status"),              # ENABLED / PAUSED / REMOVED
        "presupuesto_diario": (float(micros) / 1_000_000) if micros else None,
        "fecha_inicio": _to_date(raw.get("start_date")),
        "fecha_fin": _to_date(raw.get("end_date")),
    }


def _parse_insight(raw: dict) -> dict:
    # Métricas de Google: las propias de Meta (mensajes/interacciones/reproducciones/
    # visitas de perfil) no aplican → 0. El costo viene en micros.
    return {
        "campana_externa": str(raw.get("campaign_id")),
        "fecha": _to_date(raw.get("date")),
        "gasto": float(raw.get("cost_micros", 0) or 0) / 1_000_000,
        "impresiones": int(raw.get("impressions", 0) or 0),
        "clics": int(raw.get("clicks", 0) or 0),
        "alcance": 0,                             # Google no reporta "reach" en métricas básicas
        "conversiones": float(raw.get("conversions", 0) or 0),
        "mensajes": 0,
        "interacciones": 0,
        "reproducciones": 0,
        "visitas_perfil": 0,
        "moneda": raw.get("currency", "CLP"),
    }


# ─────────────────────────────────────────────────────────────
# Datos de muestra (modo mock, sin API)
# ─────────────────────────────────────────────────────────────

def _mock_campanas() -> list[dict]:
    return [
        {"id": "gads-1001", "name": "Búsqueda — Marca", "channel_type": "SEARCH",
         "status": "ENABLED", "budget_micros": "12000000000",
         "start_date": "2026-03-01", "end_date": None},
        {"id": "gads-1002", "name": "Performance Max — Conversiones", "channel_type": "PERFORMANCE_MAX",
         "status": "ENABLED", "budget_micros": "9000000000",
         "start_date": "2026-04-01", "end_date": None},
        {"id": "gads-1003", "name": "Display — Remarketing", "channel_type": "DISPLAY",
         "status": "PAUSED", "budget_micros": "4000000000",
         "start_date": "2026-02-10", "end_date": None},
    ]


def _mock_insights(desde: date, hasta: date, campanas: list[dict]) -> list[dict]:
    rng = random.Random(77)  # determinista (distinto seed que Meta)
    filas: list[dict] = []
    dia = desde
    while dia <= hasta:
        for c in campanas:
            if c["status"] != "ENABLED":
                continue
            impresiones = rng.randint(5000, 18000)
            clics = int(impresiones * rng.uniform(0.02, 0.06))   # Search/PMax CTR mayor que Meta
            conversiones = round(clics * rng.uniform(0.04, 0.12), 1)
            cpc_micros = rng.randint(150_000_000, 400_000_000)   # ~$150–$400 CPC en micros
            filas.append({
                "campaign_id": c["id"],
                "date": dia.isoformat(),
                "cost_micros": str(clics * cpc_micros),
                "impressions": str(impresiones),
                "clicks": str(clics),
                "conversions": str(conversiones),
                "currency": "CLP",
            })
        dia += timedelta(days=1)
    return filas


# ─────────────────────────────────────────────────────────────
# Llamadas reales a la API (pendiente — mock-first)
# ─────────────────────────────────────────────────────────────

async def _fetch_real(creds: dict, desde: date, hasta: date) -> tuple[list[dict], list[dict]]:
    """Trae campañas + métricas reales vía Google Ads API (GAQL).

    Requiere: developer_token (config.developer_token), OAuth2 client_id/secret +
    refresh_token (access_token = refresh_token), y customer_id (cuenta_id). El flujo
    es: refresh_token → access_token (oauth2.googleapis.com/token) → POST GAQL a
    googleads.googleapis.com/vXX/customers/{id}/googleAds:searchStream con el header
    developer-token. Pendiente de cablear (necesita token de desarrollador aprobado).
    """
    raise NotImplementedError(
        "Google Ads API real pendiente: requiere developer token aprobado + OAuth2 "
        "(client_id/secret, refresh_token) + customer_id. Usá mock=True por ahora.")


# ─────────────────────────────────────────────────────────────
# Ingesta
# ─────────────────────────────────────────────────────────────

async def _canal_google_id(conn) -> int:
    await conn.execute(
        """INSERT INTO canales_marketing (nombre, tipo, plataforma)
           VALUES ('Google', 'pagado', 'google') ON CONFLICT (nombre) DO NOTHING""")
    return await conn.fetchval("SELECT id FROM canales_marketing WHERE nombre='Google'")


async def sincronizar(conn, tenant_id: str, desde: date, hasta: date,
                      *, mock: bool = False) -> dict:
    """Sincroniza campañas + insights de Google Ads al esquema de marketing del tenant.

    Requiere que `conn` tenga el search_path en el schema del tenant + public.
    Escribe con plataforma='google' → el dashboard de Marketing los agrega con Meta.
    """
    if mock:
        camp_raw = _mock_campanas()
        ins_raw = _mock_insights(desde, hasta, camp_raw)
        logger.info(f"[google_ads] modo MOCK para '{tenant_id}'")
    else:
        creds = await obtener_credenciales(conn, tenant_id)
        if not creds:
            raise RuntimeError(
                f"Sin credenciales de Google Ads para '{tenant_id}'. Cargá refresh token "
                f"y customer_id en public.integraciones (proveedor='google_ads') o usá mock=True.")
        camp_raw, ins_raw = await _fetch_real(creds, desde, hasta)
        logger.info(f"[google_ads] '{tenant_id}': {len(camp_raw)} campañas, "
                    f"{len(ins_raw)} registros desde la API")

    canal_id = await _canal_google_id(conn)

    externo_a_id: dict[str, int] = {}
    for raw in camp_raw:
        c = _parse_campana(raw)
        externo_a_id[c["id_externo"]] = await _upsert_campana(conn, canal_id, c)

    insertados = 0
    for raw in ins_raw:
        ins = _parse_insight(raw)
        campana_id = externo_a_id.get(ins["campana_externa"])
        if campana_id is None:
            continue
        await _upsert_insight(conn, campana_id, ins)
        insertados += 1

    return {"tenant": tenant_id, "campanas": len(externo_a_id),
            "insights": insertados, "desde": str(desde), "hasta": str(hasta),
            "modo": "mock" if mock else "api"}
