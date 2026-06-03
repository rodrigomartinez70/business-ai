"""
Conciliación bancaria — restaurante.

La lógica es agnóstica al vertical (cruza pagos/gastos/movimientos vía el
search_path del tenant), así que se reexporta la del vertical hotel.
"""

from src.verticals.hotel.agents.conciliacion import (  # noqa: F401
    calcular_conciliacion,
    renderizar_conciliacion_markdown,
)
