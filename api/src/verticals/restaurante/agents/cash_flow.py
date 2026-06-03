"""
Agente Cash Flow — restaurante (versión simple).

Mira los últimos 28 días de cobros (pagos) vs egresos (gastos), calcula el flujo
neto semanal promedio y lo proyecta a 8 semanas, con un semáforo de liquidez.
"""

from datetime import date, timedelta

from src import config
from src.agents._common import to_float


async def calcular_cash_flow() -> dict:
    hoy     = date.today()
    hace_28 = hoy - timedelta(days=27)

    async with config.db_pool.acquire() as conn:
        ingresos = to_float(await conn.fetchval(
            "SELECT COALESCE(SUM(monto), 0) FROM pagos WHERE estado = 'pagado' AND fecha BETWEEN $1 AND $2",
            hace_28, hoy) or 0)
        egresos = to_float(await conn.fetchval(
            "SELECT COALESCE(SUM(monto), 0) FROM gastos WHERE fecha BETWEEN $1 AND $2",
            hace_28, hoy) or 0)

    neto_semanal     = round((ingresos - egresos) / 4, 2)
    flujo_proy_8sem  = round(neto_semanal * 8, 2)

    if neto_semanal >= 0:
        semaforo = "ok"
    elif ingresos > 0 and abs(neto_semanal) < (ingresos / 4):
        semaforo = "alerta"
    else:
        semaforo = "critico"

    return {
        "semaforo": semaforo,
        "resumen": {
            "ingresos_28d": ingresos,
            "egresos_28d": egresos,
            "neto_semanal": neto_semanal,
            "flujo_proyectado_8sem": flujo_proy_8sem,
        },
    }
