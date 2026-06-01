"""
Contexto económico — Índice de Precios al Consumidor (IPC) de Chile.

Fuente: mindicador.cl (API pública, sin credenciales). Se cachea en memoria
para no llamarla en cada request y para resistir caídas puntuales del servicio.
"""

import logging
import time

import httpx

logger = logging.getLogger(__name__)

_IPC_URL   = "https://mindicador.cl/api/ipc"
_CACHE_TTL = 6 * 3600   # 6 horas (el IPC se publica una vez al mes)

# Cache en memoria: {"ts": epoch, "data": dict}
_cache: dict = {}


def _acumulado_pct(valores: list[float]) -> float:
    """Inflación compuesta de una lista de variaciones mensuales (%)."""
    factor = 1.0
    for v in valores:
        factor *= (1 + v / 100)
    return round((factor - 1) * 100, 1)


async def obtener_ipc(meses: int = 12) -> dict | None:
    """
    Devuelve los últimos `meses` de variación mensual del IPC de Chile.

    Estructura:
        {
          "serie": [{"mes": "2025-01", "valor": 0.4}, ...],   # cronológico
          "acumulado_pct": 3.8,        # inflación compuesta del período
          "ultimo_mes": "2025-12",
          "fuente": "mindicador.cl",
        }
    Retorna None si la fuente no está disponible (la sección simplemente se omite).
    """
    now = time.time()
    if _cache and now - _cache["ts"] < _CACHE_TTL:
        return _cache["data"]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_IPC_URL)
            resp.raise_for_status()
            raw = resp.json()
    except Exception as e:
        logger.warning(f"No se pudo obtener el IPC desde mindicador.cl: {e}")
        # Si hay cache vieja, devolverla aunque haya expirado (mejor que nada)
        return _cache["data"] if _cache else None

    serie_raw = raw.get("serie", [])
    if not serie_raw:
        return _cache["data"] if _cache else None

    # La serie viene de más reciente a más antigua: tomar N últimos, invertir a cronológico ascendente
    ultimos = serie_raw[:meses][::-1]
    serie = sorted([{"mes": p["fecha"][:7], "valor": float(p["valor"])} for p in ultimos],
                   key=lambda x: x["mes"])

    data = {
        "serie":         serie,
        "acumulado_pct": _acumulado_pct([p["valor"] for p in serie]),
        "ultimo_mes":    serie[-1]["mes"] if serie else None,
        "fuente":        "mindicador.cl",
    }
    _cache.update(ts=now, data=data)
    return data
