"""
Integraciones por tenant (back-office MBI Admin).

Vincula los sistemas integrables (Meta Ads, Toteat, Odoo, Defontana…) a cada
empresa, con sus credenciales/parámetros. Todo se guarda en public.integraciones
(access_token + cuenta_id + config jsonb). Si una integración no está configurada,
el conector correspondiente devuelve None y el módulo opera con su mock/data default.

Cada proveedor declara sus campos: (columna, etiqueta, secreto?). La columna es
`access_token`, `cuenta_id`, o `config.<clave>` (va al JSONB de config).
"""

import json
import logging

from .. import config

logger = logging.getLogger(__name__)


class AdminError(Exception):
    """Error de validación de integración (→ 400)."""


# (columna, etiqueta, es_secreto)
PROVEEDORES = {
    "meta": {
        "label": "Meta Ads — Marketing",
        "campos": [
            ("access_token", "Access Token", True),
            ("cuenta_id",    "Ad Account ID (act_…)", False),
        ],
    },
    "google_ads": {
        "label": "Google Ads — Marketing",
        "campos": [
            ("access_token",            "Refresh Token (OAuth2)", True),
            ("cuenta_id",               "Customer ID (000-000-0000)", False),
            ("config.developer_token",  "Developer Token", False),
            ("config.client_id",        "OAuth Client ID", False),
            ("config.login_customer_id", "Login Customer ID (opcional)", False),
        ],
    },
    "toteat": {
        "label": "Toteat — Punto de venta gastronómico",
        "campos": [
            ("access_token",    "API Token (xapitoken)", True),
            ("cuenta_id",       "Restaurant ID (xir)", False),
            ("config.xil",      "Location ID (xil)", False),
            ("config.xiu",      "Middleware / User ID (xiu)", False),
            ("config.base_url", "Base URL (opcional)", False),
        ],
    },
    "odoo": {
        "label": "Odoo — Contabilidad",
        "campos": [
            ("access_token",   "API Key", True),
            ("cuenta_id",      "Base de datos (db)", False),
            ("config.url",     "URL", False),
            ("config.usuario", "Usuario", False),
        ],
    },
    "defontana": {
        "label": "Defontana — Contabilidad",
        "campos": [
            ("access_token",  "Password", True),
            ("cuenta_id",     "Company (empresa)", False),
            ("config.client", "Client ID", False),
            ("config.usuario", "Usuario", False),
            ("config.url",    "URL (opcional)", False),
        ],
    },
}


def _norm_cfg(cfg) -> dict:
    if cfg is None:
        return {}
    return cfg if isinstance(cfg, dict) else json.loads(cfg)


async def estado(tenant_id: str) -> dict:
    """Estado de todas las integraciones del tenant (para la UI)."""
    rows = await config.raw_pool.fetch(
        """SELECT proveedor, access_token, cuenta_id, config, activo
             FROM public.integraciones WHERE tenant_id = $1""", tenant_id)
    por_prov = {r["proveedor"]: r for r in rows}

    items = []
    for prov, meta in PROVEEDORES.items():
        row = por_prov.get(prov)
        cfg = _norm_cfg(row["config"]) if row else {}
        tiene_token = bool(row and row["access_token"])
        configurado = bool(tiene_token and row["cuenta_id"])
        campos = []
        for col, label, secreto in meta["campos"]:
            if col == "access_token":
                valor = ""               # nunca devolvemos el secreto
            elif col == "cuenta_id":
                valor = (row["cuenta_id"] if row else "") or ""
            else:
                valor = str(cfg.get(col.split(".", 1)[1], "") or "")
            campos.append({"col": col, "label": label, "secreto": secreto,
                           "valor": valor})
        items.append({"proveedor": prov, "label": meta["label"],
                      "configurado": configurado, "tiene_token": tiene_token,
                      "activo": bool(row and row["activo"]), "campos": campos})
    return {"tenant_id": tenant_id, "integraciones": items}


async def guardar(tenant_id: str, proveedor: str, valores: dict) -> None:
    if proveedor not in PROVEEDORES:
        raise AdminError(f"Proveedor desconocido: {proveedor}.")
    existe = await config.raw_pool.fetchval(
        "SELECT 1 FROM public.tenants WHERE id = $1", tenant_id)
    if not existe:
        raise AdminError(f"No existe la empresa '{tenant_id}'.")

    prev = await config.raw_pool.fetchrow(
        "SELECT access_token FROM public.integraciones WHERE tenant_id=$1 AND proveedor=$2",
        tenant_id, proveedor)
    token_prev = prev["access_token"] if prev else None

    access_token = token_prev
    cuenta_id = None
    cfg: dict = {}
    for col, _label, secreto in PROVEEDORES[proveedor]["campos"]:
        v = (valores.get(col) or "").strip()
        if col == "access_token":
            access_token = v or token_prev      # vacío = mantener el secreto guardado
        elif col == "cuenta_id":
            cuenta_id = v or None
        else:                                    # config.<clave>
            clave = col.split(".", 1)[1]
            if v:
                cfg[clave] = v

    activo = bool(access_token and cuenta_id)
    await config.raw_pool.execute(
        """INSERT INTO public.integraciones
               (tenant_id, proveedor, access_token, cuenta_id, config, activo, actualizado_en)
           VALUES ($1, $2, $3, $4, $5::jsonb, $6, now())
           ON CONFLICT (tenant_id, proveedor) DO UPDATE
               SET access_token = EXCLUDED.access_token, cuenta_id = EXCLUDED.cuenta_id,
                   config = EXCLUDED.config, activo = EXCLUDED.activo, actualizado_en = now()""",
        tenant_id, proveedor, access_token, cuenta_id, json.dumps(cfg), activo)
    logger.info(f"[admin] integración {proveedor} de {tenant_id} guardada (activo={activo})")


async def desconectar(tenant_id: str, proveedor: str) -> None:
    """Borra la integración → el módulo vuelve a operar con mock/data default."""
    await config.raw_pool.execute(
        "DELETE FROM public.integraciones WHERE tenant_id=$1 AND proveedor=$2",
        tenant_id, proveedor)
    logger.info(f"[admin] integración {proveedor} de {tenant_id} desconectada")
