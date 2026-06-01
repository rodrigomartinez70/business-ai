"""
Contexto económico — Índice de Precios al Consumidor (IPC) de Chile.

Fuente: API BDE del Banco Central de Chile (requiere credenciales registradas).
Se cachea en memoria para no llamarla en cada request y para resistir caídas puntuales.

Variables de entorno requeridas:
  - BCENTRAL_IPC_USER: usuario API BDE (rodrigo.martinez@majorbi.com)
  - BCENTRAL_IPC_PASS: contraseña API BDE
  - BCENTRAL_IPC_SERIES: código de serie (G073.IPC.V12.2023.M = variación anual del IPC)
"""

import logging
import os
import time
from datetime import date, timedelta

import httpx

logger = logging.getLogger(__name__)

_BCENTRAL_URL = "https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx"
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
    Devuelve los últimos `meses` de variación mensual del IPC de Chile
    desde la API BDE del Banco Central.

    Estructura:
        {
          "serie": [{"mes": "2025-01", "valor": 0.4}, ...],   # cronológico ascendente
          "acumulado_pct": 3.8,        # inflación compuesta del período
          "ultimo_mes": "2025-12",
          "fuente": "Banco Central de Chile",
        }
    Retorna None si la fuente no está disponible o credenciales no configuradas.
    """
    now = time.time()
    if _cache and now - _cache["ts"] < _CACHE_TTL:
        return _cache["data"]

    # Verificar credenciales
    user = os.environ.get("BCENTRAL_IPC_USER", "").strip()
    password = os.environ.get("BCENTRAL_IPC_PASS", "").strip()
    series_code = os.environ.get("BCENTRAL_IPC_SERIES", "").strip()

    if not (user and password and series_code):
        logger.warning(
            "IPC: no configuradas credenciales Banco Central "
            "(BCENTRAL_IPC_USER, BCENTRAL_IPC_PASS, BCENTRAL_IPC_SERIES)"
        )
        return _cache["data"] if _cache else None

    try:
        # Fechas: últimos 15 meses para garantizar N meses completos
        today = date.today()
        last_date = today.replace(day=1) - timedelta(days=1)  # Último día del mes anterior
        first_date = (last_date - timedelta(days=30 * (meses + 3))).replace(day=1)

        params = {
            "user": user,
            "pass": password,
            "function": "GetSeries",
            "timeseries": series_code,
            "firstdate": first_date.strftime("%Y-%m-%d"),
            "lastdate": last_date.strftime("%Y-%m-%d"),
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_BCENTRAL_URL, params=params)
            resp.raise_for_status()
            # El Banco Central a veces devuelve caracteres con encoding incorrecto; usar 'replace' para ignorarlos
            try:
                raw = resp.json()
            except UnicodeDecodeError:
                text = resp.content.decode('utf-8', errors='replace')
                import json
                raw = json.loads(text)
    except Exception as e:
        logger.warning(f"IPC: error consultando API BDE Banco Central: {e}")
        return _cache["data"] if _cache else None

    # Estructura esperada: {"Series": [...]} con cada entrada: {"Periodo": "2025-01", "Valor": "0.4"}
    series_data = raw.get("Series", [])
    if not series_data:
        logger.warning(f"IPC: respuesta vacía de API BDE para serie {series_code}")
        return _cache["data"] if _cache else None

    # Extraer y ordenar: tomar últimos N meses, ordenar cronológicamente ascendente
    serie = [
        {"mes": p["Periodo"][:7], "valor": float(p["Valor"])}
        for p in series_data
        if p.get("Valor")
    ]
    serie = sorted(serie, key=lambda x: x["mes"])[-meses:]

    if not serie:
        return _cache["data"] if _cache else None

    data = {
        "serie":         serie,
        "acumulado_pct": _acumulado_pct([p["valor"] for p in serie]),
        "ultimo_mes":    serie[-1]["mes"] if serie else None,
        "fuente":        "Banco Central de Chile",
    }
    _cache.update(ts=now, data=data)
    return data
