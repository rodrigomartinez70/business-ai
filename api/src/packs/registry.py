"""
Registro de packs de datos componibles.

Un pack es una capacidad estructural de una empresa: aporta TABLAS (un fragmento
`schema.sql`) y FUENTES (un módulo de métricas opcional). Una empresa es la
composición de los packs que tiene — `base` siempre, más los que correspondan a
sus sistemas de datos (POS, ERP, …).

Ver `doc/design-packs.md`. Durante la transición (P1-P2), el `vertical` del tenant
se mantiene y mapea a un set de packs vía `VERTICAL_PACKS`; el alta sigue
funcionando por vertical mientras la UI por packs (P2) no esté.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_DIR = Path(__file__).resolve().parent          # .../api/src/packs


@dataclass(frozen=True)
class Pack:
    id: str
    label: str
    descripcion: str
    metricas_mod: str | None = None             # módulo a importar para registrar sus fuentes
    requiere: tuple = field(default_factory=tuple)   # packs prerequisito (ej. todo requiere base)


# Catálogo. El orden importa para el ensamblado del schema: base primero (las demás
# tablas no dependen de él, pero deja un DDL legible y estable).
PACKS: dict[str, Pack] = {
    "base": Pack(
        id="base", label="Base",
        descripcion="Gastos, facturas, banco, presupuesto y auditoría. Siempre activo.",
    ),
    "pos_gastronomico": Pack(
        id="pos_gastronomico", label="POS Gastronómico",
        descripcion="Menú, pedidos y cobros del POS de restaurante (Toteat u otro).",
        metricas_mod="src.verticals.restaurante.metricas",
        requiere=("base",),
    ),
    "pos_hotelero": Pack(
        id="pos_hotelero", label="POS Hotelero",
        descripcion="Habitaciones, reservas, cobros y consumos (PMS de hotel).",
        metricas_mod="src.verticals.hotel.metricas",
        requiere=("base",),
    ),
    "erp": Pack(
        id="erp", label="ERP / Contabilidad",
        descripcion="Plan de cuentas y saldos mensuales (Odoo, Defontana). Habilita P&L contable.",
        requiere=("base",),
    ),
}

# Mapeo de transición: vertical histórico → set de packs equivalente.
VERTICAL_PACKS: dict[str, list[str]] = {
    "restaurante": ["base", "pos_gastronomico", "erp"],
    "hotel":       ["base", "pos_hotelero", "erp"],
}


class PackError(Exception):
    """Pack desconocido o composición inválida."""


def existe(pack_id: str) -> bool:
    return pack_id in PACKS


def catalogo() -> list[Pack]:
    return list(PACKS.values())


def packs_de_vertical(vertical: str | None) -> list[str]:
    """Set de packs equivalente a un vertical histórico (transición)."""
    return list(VERTICAL_PACKS.get((vertical or "").lower(), ["base"]))


def normalizar(packs: list[str] | None) -> list[str]:
    """Valida, agrega prerequisitos (base) y deduplica, preservando el orden del catálogo."""
    pedidos = set(packs or [])
    pedidos.add("base")
    for pid in list(pedidos):
        if pid not in PACKS:
            raise PackError(f"Pack desconocido: '{pid}'. Opciones: {', '.join(PACKS)}.")
        pedidos.update(PACKS[pid].requiere)
    return [pid for pid in PACKS if pid in pedidos]      # orden canónico del catálogo


def schema_ddl(packs: list[str]) -> str:
    """Concatena los fragmentos schema.sql de los packs (normalizados). Todos los
    CREATE son IF NOT EXISTS, así que el resultado es idempotente y los solapes no
    rompen (gana el primero; los packs no deben definir la misma tabla distinto)."""
    partes = []
    for pid in normalizar(packs):
        frag = _DIR / pid / "schema.sql"
        if frag.exists():
            partes.append(f"-- ── pack: {pid} ──\n{frag.read_text()}")
    return "\n\n".join(partes)


def cargar_packs(packs: list[str]) -> None:
    """Importa los módulos de fuentes de los packs activos (registra sus métricas/tablas).
    Hoy delega en los módulos de métricas por-vertical existentes; en P3 las fuentes
    vivirán físicamente en el pack."""
    for pid in normalizar(packs):
        mod = PACKS[pid].metricas_mod
        if not mod:
            continue
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError:
            logger.info(f"[packs] '{pid}' sin módulo de fuentes ({mod})")
