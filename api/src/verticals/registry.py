"""
Contrato de vertical — define qué debe proveer cada vertical y cómo se descubre.

Un vertical (hotel, restaurante, …) debe exponer:

  Runtime (módulos Python):
    - <vertical>.dashboard                 → calcular_dashboard(), renderizar_dashboard_html(data, cfg)
    - <vertical>.agents.tributario         → calcular_tributario_semanal(hasta), renderizar_tributario_markdown(data)
    - <vertical>.agents.tributario.conversacional → responder_tributario(pregunta, historial)
    - <vertical>.insights_prompts          → SYSTEM, PROMPTS, RESUMIDORES

  Datos (archivos, para provisioning):
    - <vertical>/schema.sql                → tablas del tenant
    - <vertical>/config.template.yaml      → plantilla de config

Lo COMÚN (motor tributario, conciliación, control de gastos, economía, render,
insights/alertas) vive en src/finanzas, src/render y src/agents — NO en el vertical.
El vertical solo aporta sus diferenciadores + el hook `ingresos()` del tributario.
"""

import importlib
from dataclasses import dataclass
from pathlib import Path

# Verticales registrados en la plataforma.
VERTICALS = ("hotel", "restaurante")

# Atributos requeridos por módulo (el "contrato").
_REQUERIDOS = {
    "dashboard":       ("calcular_dashboard", "renderizar_dashboard_html"),
    "tributario":      ("calcular_tributario_semanal", "renderizar_tributario_markdown"),
    "conversacional":  ("responder_tributario",),
    "insights_prompts": ("SYSTEM", "PROMPTS", "RESUMIDORES"),
}
_ARCHIVOS = ("schema.sql", "config.template.yaml")


@dataclass(frozen=True)
class Vertical:
    nombre: str
    dashboard: object
    tributario: object
    conversacional: object
    insights_prompts: object


_cache: dict[str, Vertical] = {}


def _incumplimientos(nombre: str, mods: dict) -> list[str]:
    faltan = []
    for mod_key, attrs in _REQUERIDOS.items():
        mod = mods[mod_key]
        for a in attrs:
            if not hasattr(mod, a):
                faltan.append(f"{mod_key}.{a}")
    base_dir = Path(mods["dashboard"].__file__).parent
    for archivo in _ARCHIVOS:
        if not (base_dir / archivo).exists():
            faltan.append(f"archivo {archivo}")
    return faltan


def cargar(nombre: str) -> Vertical:
    """Importa y valida un vertical contra el contrato. Cachea el resultado."""
    if nombre in _cache:
        return _cache[nombre]

    base = f"src.verticals.{nombre}"
    mods = {
        "dashboard":        importlib.import_module(f"{base}.dashboard"),
        "tributario":       importlib.import_module(f"{base}.agents.tributario"),
        "conversacional":   importlib.import_module(f"{base}.agents.tributario.conversacional"),
        "insights_prompts": importlib.import_module(f"{base}.insights_prompts"),
    }
    faltan = _incumplimientos(nombre, mods)
    if faltan:
        raise RuntimeError(f"Vertical '{nombre}' no cumple el contrato: faltan {faltan}")

    v = Vertical(
        nombre=nombre,
        dashboard=mods["dashboard"],
        tributario=mods["tributario"],
        conversacional=mods["conversacional"],
        insights_prompts=mods["insights_prompts"],
    )
    _cache[nombre] = v
    return v
