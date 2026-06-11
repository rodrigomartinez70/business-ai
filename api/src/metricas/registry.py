"""
Registro del catálogo de métricas. Claves por (vertical, nombre); vertical=None
son horizontales. Lookup: primero la del vertical del tenant, si no la horizontal.
"""

import importlib
import logging
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class Metrica:
    nombre: str
    fn: Callable                       # async (conn, ini, fin) -> float
    unidad: str = "moneda"             # 'moneda' | '%' | 'numero'
    label: str = ""
    vertical: str | None = None        # None = horizontal


_REGISTRO: dict[tuple, Metrica] = {}   # (vertical_or_None, nombre) -> Metrica
_VERTICALES_CARGADOS: set[str] = set()


def metrica(nombre: str, *, unidad: str = "moneda", label: str = "",
            vertical: str | None = None):
    def deco(fn):
        _REGISTRO[(vertical, nombre)] = Metrica(nombre, fn, unidad, label or nombre, vertical)
        return fn
    return deco


def cargar_vertical(vertical: str | None) -> None:
    """Importa el módulo de métricas del vertical (registra sus métricas)."""
    if not vertical or vertical in _VERTICALES_CARGADOS:
        return
    try:
        importlib.import_module(f"src.verticals.{vertical}.metricas")
        _VERTICALES_CARGADOS.add(vertical)
    except ModuleNotFoundError:
        logger.info(f"[metricas] vertical '{vertical}' sin módulo de métricas")
        _VERTICALES_CARGADOS.add(vertical)


def obtener(nombre: str, vertical: str | None = None) -> Metrica | None:
    cargar_vertical(vertical)
    return _REGISTRO.get((vertical, nombre)) or _REGISTRO.get((None, nombre))


def catalogo(vertical: str | None = None) -> list[Metrica]:
    """Métricas disponibles para un vertical (horizontales + las del vertical)."""
    cargar_vertical(vertical)
    out: dict[str, Metrica] = {n: m for (v, n), m in _REGISTRO.items() if v is None}
    if vertical:
        out.update({n: m for (v, n), m in _REGISTRO.items() if v == vertical})
    return sorted(out.values(), key=lambda m: m.nombre)
