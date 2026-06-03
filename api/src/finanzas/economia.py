"""
Contexto económico — Índice de Precios al Consumidor (IPC) de Chile.

Fuente: API BDE del Banco Central de Chile (requiere credenciales registradas).
Se cachea en memoria para no llamarla en cada request y para resistir caídas puntuales.

Variables de entorno requeridas:
  - BCENTRAL_IPC_USER: usuario API BDE (rodrigo.martinez@majorbi.com)
  - BCENTRAL_IPC_PASS: contraseña API BDE
  - BCENTRAL_IPC_SERIES: código de serie (G073.IPC.VAR.2023.M = variación mensual del IPC)
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

    # Estructura esperada: {"Series": {"Obs": [{"indexDateString": "2025-01", "value": "0.4"}, ...]}}
    series_obj = raw.get("Series", {})
    series_data = series_obj.get("Obs", []) if isinstance(series_obj, dict) else []

    if not series_data:
        logger.warning(f"IPC: respuesta vacía de API BDE para serie {series_code}")
        return _cache["data"] if _cache else None

    # Extraer y ordenar: tomar últimos N meses, ordenar cronológicamente ascendente
    # indexDateString viene en formato "DD-MM-YYYY"
    serie = []
    for p in series_data:
        if p.get("value") and p.get("statusCode") == "OK":
            date_str = p["indexDateString"]  # "01-04-2026"
            # Convertir DD-MM-YYYY a YYYY-MM
            parts = date_str.split("-")
            if len(parts) == 3:
                mes = f"{parts[2]}-{parts[1]}"  # "2026-04"
                serie.append({"mes": mes, "valor": float(p["value"])})

    serie = sorted(serie, key=lambda x: x["mes"])[-meses:]

    if not serie:
        return _cache["data"] if _cache else None

    # Usar variación mensual más reciente, no acumulada
    ultimo_valor = serie[-1]["valor"] if serie else None

    data = {
        "serie":         serie,
        "acumulado_pct": ultimo_valor,  # Variación mensual del último mes disponible
        "ultimo_mes":    serie[-1]["mes"] if serie else None,
        "fuente":        "Banco Central de Chile",
    }
    _cache.update(ts=now, data=data)
    return data


# ─────────────────────────────────────────────────────────────
# UF — Unidad de Fomento (valor diario)
# ─────────────────────────────────────────────────────────────

_UF_CACHE_TTL = 12 * 3600   # 12 horas (la UF se publica una vez al día)
_uf_cache: dict = {}        # {"ts": epoch, "valor": float}


async def obtener_uf() -> float | None:
    """
    Devuelve el último valor de la UF (en pesos) desde la API BDE del Banco
    Central. Reutiliza las credenciales BCENTRAL_IPC_USER/PASS (misma cuenta BDE).
    Serie por defecto: F073.UFF.PRE.Z.D (UF diaria). Cacheado 12h.

    Retorna None si la fuente no responde o no hay credenciales.
    """
    now = time.time()
    if _uf_cache and now - _uf_cache["ts"] < _UF_CACHE_TTL:
        return _uf_cache["valor"]

    user       = os.environ.get("BCENTRAL_IPC_USER", "").strip()
    password   = os.environ.get("BCENTRAL_IPC_PASS", "").strip()
    series_uf  = os.environ.get("BCENTRAL_UF_SERIES", "F073.UFF.PRE.Z.D").strip()

    if not (user and password and series_uf):
        logger.warning("UF: credenciales Banco Central no configuradas")
        return _uf_cache.get("valor") if _uf_cache else None

    try:
        today      = date.today()
        first_date = today - timedelta(days=10)   # margen para tomar el último valor publicado
        params = {
            "user": user, "pass": password,
            "function": "GetSeries", "timeseries": series_uf,
            "firstdate": first_date.strftime("%Y-%m-%d"),
            "lastdate":  today.strftime("%Y-%m-%d"),
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_BCENTRAL_URL, params=params)
            resp.raise_for_status()
            try:
                raw = resp.json()
            except UnicodeDecodeError:
                import json
                raw = json.loads(resp.content.decode("utf-8", errors="replace"))
    except Exception as e:
        logger.warning(f"UF: error consultando API BDE Banco Central: {e}")
        return _uf_cache.get("valor") if _uf_cache else None

    series_obj = raw.get("Series", {})
    obs = series_obj.get("Obs", []) if isinstance(series_obj, dict) else []

    # indexDateString viene en DD-MM-YYYY; tomar la observación OK más reciente
    valores = []
    for p in obs:
        if p.get("value") and p.get("statusCode") == "OK":
            parts = p["indexDateString"].split("-")
            if len(parts) == 3:
                clave = f"{parts[2]}-{parts[1]}-{parts[0]}"  # YYYY-MM-DD para ordenar
                valores.append((clave, float(p["value"])))

    if not valores:
        logger.warning("UF: respuesta vacía de API BDE")
        return _uf_cache.get("valor") if _uf_cache else None

    valor = sorted(valores, key=lambda x: x[0])[-1][1]
    _uf_cache.update(ts=now, valor=valor)
    return valor
