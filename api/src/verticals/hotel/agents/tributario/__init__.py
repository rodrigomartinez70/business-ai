"""
Copiloto Tributario para PyMEs en Chile — plataforma de 4 agentes especializados.

Fase 1 (computacionales, sin LLM):
  - Agente IVA          → débito, crédito, saldo, proyección y F29   (iva.py)
  - Agente Cumplimiento → calendario tributario, DJs, vencimientos   (cumplimiento.py)
  - Agente Riesgo       → inconsistencias, fiscalización, alertas    (riesgo.py)

Fase 2 (interactivo, con LLM):
  - Agente Conversacional → Q&A en lenguaje natural (se integra en Open WebUI)

`calcular_tributario_semanal()` orquesta los 3 agentes computacionales y arma
el dict que consume el dashboard semanal.
"""

from datetime import date, timedelta

from src import config
from .iva import calcular_iva
from .cumplimiento import calcular_cumplimiento
from .riesgo import calcular_riesgo

__all__ = ["calcular_tributario_semanal", "renderizar_tributario_markdown"]


async def calcular_tributario_semanal(hasta: date) -> dict:
    """Ejecuta los agentes IVA, Cumplimiento y Riesgo para la fecha de corte."""
    desde      = hasta - timedelta(days=6)
    inicio_mes = date(hasta.year, hasta.month, 1)

    async with config.db_pool.acquire() as conn:
        iva    = await calcular_iva(conn, hasta)
        riesgo = await calcular_riesgo(conn, hasta, iva)

    cumplimiento = calcular_cumplimiento(hasta)

    return {
        "periodo": {
            "semana": {"inicio": str(desde), "fin": str(hasta)},
            "mes":    {"inicio": str(inicio_mes), "fin": str(hasta)},
        },
        "agente_iva":          iva,
        "agente_cumplimiento": cumplimiento,
        "agente_riesgo":       riesgo,
    }


def renderizar_tributario_markdown(data: dict) -> str:
    """Render markdown del resultado de los agentes tributarios."""
    iva = data.get("agente_iva", {})
    cum = data.get("agente_cumplimiento", {})
    rie = data.get("agente_riesgo", {})

    acum = iva.get("acumulado_mes", {})
    f29  = iva.get("f29", {})

    out = ["# Copiloto Tributario\n"]

    out.append("## Agente IVA")
    out.append(f"- IVA débito (mes): ${acum.get('iva_debito_acum', 0):,.0f}")
    out.append(f"- IVA crédito (mes): ${acum.get('iva_credito_acum', 0):,.0f}")
    out.append(f"- Saldo IVA: ${acum.get('saldo_iva', 0):,.0f} "
               f"({acum.get('saldo_iva_uf', 0):.1f} UF) — {acum.get('estado', '')}")
    out.append(f"- F29 período {f29.get('periodo', '')}: a pagar ${f29.get('monto_estimado', 0):,.0f} "
               f"· vence {f29.get('vencimiento', '')} (en {f29.get('dias_para_vencimiento', 0)} días)\n")

    out.append("## Agente Cumplimiento — próximos vencimientos")
    venc = cum.get("proximos_vencimientos", [])
    if venc:
        for v in venc:
            out.append(f"- {v['fecha']} · {v['nombre']} (en {v['dias_restantes']} días)")
    else:
        out.append("- Sin vencimientos en el horizonte.")
    out.append("")

    out.append(f"## Agente Riesgo — nivel: {rie.get('score_riesgo', 'n/a')}")
    for i in rie.get("inconsistencias", []):
        out.append(f"- [{i['nivel']}] {i['titulo']}: {i['descripcion']}")
    for a in rie.get("alertas", []):
        out.append(f"- ALERTA [{a['nivel']}] {a['titulo']}: {a['descripcion']}")
    if not rie.get("inconsistencias") and not rie.get("alertas"):
        out.append("- Sin inconsistencias ni alertas detectadas.")

    return "\n".join(out)
