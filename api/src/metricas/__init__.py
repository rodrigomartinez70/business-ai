"""
Capa semántica de métricas (F0).

Un catálogo de métricas nombradas y vetadas por dev: cada una calcula UN número
para un período (conn, ini, fin) -> float. Los KPIs particulares de cada empresa
se construyen como fórmulas sobre estos nombres (nunca SQL del usuario).

Importar este paquete registra las métricas horizontales. Las de cada vertical se
cargan on-demand vía `cargar_vertical(vertical)`.
"""

from .registry import metrica, obtener, catalogo, cargar_vertical  # noqa: F401
from . import horizontal  # noqa: F401  (registra las métricas horizontales al importar)
