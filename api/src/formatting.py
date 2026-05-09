"""
Formateo de respuestas al usuario.
Convierte filas de DB en texto markdown con formato de moneda configurado.
"""

from decimal import Decimal
from . import config


def _es_valor_dinero(clave: str) -> bool:
    clave_lower = clave.lower().replace(" ", "_")
    non_money   = set(config.CONFIG.get("non_money_columns", []))
    money       = set(config.CONFIG.get("money_columns", []))
    if any(p in clave_lower for p in non_money):
        return False
    return any(p in clave_lower for p in money)


def _formatear_moneda(valor: float) -> str:
    cur  = config.CONFIG.get("currency", {})
    sym  = cur.get("symbol", "$")
    tsep = cur.get("thousands_separator", ".")
    dp   = cur.get("decimal_places", 0)
    if dp == 0:
        s = f"{int(round(valor)):,}".replace(",", tsep)
    else:
        s = f"{valor:,.{dp}f}".replace(",", tsep)
    return f"{sym}{s}"


def _formatear_valor(clave: str, valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, (int, float, Decimal)):
        if _es_valor_dinero(clave):
            return _formatear_moneda(float(valor))
        f = float(valor)
        return str(int(f)) if f == int(f) else f"{f:.2f}"
    return str(valor)


def formatear_respuesta(datos: list[dict]) -> str:
    if not datos:
        return "No encontré información que coincida con tu consulta."

    if len(datos) == 1:
        fila   = datos[0]
        lineas = ["**Resultado encontrado:**\n"]
        for clave, valor in fila.items():
            if valor is not None:
                lineas.append(f"- **{clave.replace('_', ' ').title()}:** {_formatear_valor(clave, valor)}")
        return "\n".join(lineas)

    lineas = [f"**Se encontraron {len(datos)} resultado(s):**\n"]
    for i, fila in enumerate(datos, 1):
        lineas.append(f"**{i}.** " + " | ".join(
            f"{k.replace('_', ' ').title()}: {_formatear_valor(k, v)}"
            for k, v in fila.items() if v is not None
        ))
    return "\n".join(lineas)
