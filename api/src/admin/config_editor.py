"""
Editor del config del tenant (back-office). Carga/valida/guarda el config como
YAML; valida los KPIs por fórmula contra el catálogo de métricas antes de guardar.
"""

import json
import logging

import yaml

from .. import config, tenant_registry
from ..metricas import kpis as mk
from ..metricas.registry import catalogo
from .tenants import _cargar_config_efectivo, AdminError  # reutiliza la carga efectiva

logger = logging.getLogger(__name__)

_SCAFFOLD_KPIS = """
# ── KPIs particulares (descomentá y editá) ─────────────────────
# kpis:
#   - clave: food_cost_pct
#     nombre: "Food cost %"
#     formula: "costo_ventas / ventas * 100"
#     unidad: "%"
#     umbral_max: 35
#   - clave: gasto_sobre_ingreso
#     nombre: "Gasto / Ingreso %"
#     formula: "gastos_total / ingresos * 100"
#     unidad: "%"
#     umbral_max: 70
"""


async def vertical_de(tenant_id: str) -> str | None:
    return await config.raw_pool.fetchval(
        "SELECT vertical FROM public.tenants WHERE id=$1", tenant_id)


def catalogo_metricas(vertical: str | None) -> list[dict]:
    return [{"nombre": m.nombre, "label": m.label, "unidad": m.unidad}
            for m in catalogo(vertical)]


# Orden canónico para mostrar el config igual en todos los tenants (jsonb no
# preserva el orden de claves, así que normalizamos en la vista del editor).
_ORDEN_TOP = ["business", "currency", "report", "kpis", "pnl", "roles", "schema",
              "tributario", "money_columns", "non_money_columns", "table_aliases",
              "income_keywords", "expense_keywords"]
_ORDEN_SEC = {
    "business": ["name", "vertical"],
    "report": ["email_to", "modulos"],
}


def _reordenar(d: dict, orden: list[str]) -> dict:
    out = {k: d[k] for k in orden if k in d}
    for k, v in d.items():            # claves no listadas: al final, en su orden
        out.setdefault(k, v)
    return out


def normalizar_config(cfg: dict) -> dict:
    """Reordena el config a un orden canónico (top-level + secciones conocidas)."""
    if not isinstance(cfg, dict):
        return cfg
    cfg = _reordenar(cfg, _ORDEN_TOP)
    for sec, orden in _ORDEN_SEC.items():
        if isinstance(cfg.get(sec), dict):
            cfg[sec] = _reordenar(cfg[sec], orden)
    return cfg


async def cargar_yaml(tenant_id: str) -> str:
    cfg = normalizar_config(await _cargar_config_efectivo(tenant_id))
    texto = yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False)
    if "kpis" not in cfg:                  # scaffold para no arrancar en blanco
        texto += _SCAFFOLD_KPIS
    return texto


def validar(texto: str, vertical: str | None) -> tuple[dict | None, list[str]]:
    try:
        cfg = yaml.safe_load(texto)
    except yaml.YAMLError as e:
        return None, [f"YAML inválido: {e}"]
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, dict):
        return None, ["El config debe ser un objeto (clave: valor)."]
    errores = mk.validar(vertical, cfg.get("kpis", []))
    return (None, errores) if errores else (cfg, [])


async def guardar(tenant_id: str, texto: str) -> list[str]:
    """Valida y guarda el config (JSONB) + recarga el registry. Devuelve errores (vacío = ok)."""
    row = await config.raw_pool.fetchrow(
        "SELECT vertical FROM public.tenants WHERE id=$1", tenant_id)
    if not row:
        raise AdminError(f"No existe la empresa '{tenant_id}'.")
    cfg, errores = validar(texto, row["vertical"])
    if errores:
        return errores
    # Prueba de carga ANTES de persistir: un config que rompe el schema cache
    # no debe guardarse nunca (rompería el tenant en la recarga del registry).
    from ..schema import build_schema_cache_for_tenant
    try:
        await build_schema_cache_for_tenant(config.raw_pool, cfg, tenant_id)
    except Exception as e:                            # noqa: BLE001
        return [f"El config no es válido para el tenant: {e}"]
    await config.raw_pool.execute(
        "UPDATE public.tenants SET config = $2::jsonb WHERE id = $1",
        tenant_id, json.dumps(cfg))
    await tenant_registry.load_all_tenants(
        pool=config.raw_pool, legacy_api_keys=config.API_KEYS,
        legacy_config=config.CONFIG, legacy_tenant_id="hotel_mbi")
    logger.info(f"[admin] config de {tenant_id} actualizado vía editor")
    return []
