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
from datetime import date, timedelta

import asyncpg

from .. import config
from ..integraciones import google_ads, meta_ads, odoo, toteat
from .tenants import _TENANT_RE

logger = logging.getLogger(__name__)


class AdminError(Exception):
    """Error de validación de integración (→ 400)."""


# Categorías (secciones de la UI), en orden de presentación: (clave, título, ícono)
CATEGORIAS = [
    ("marketing", "Marketing", "📣"),
    ("pos",       "Punto de venta", "🧾"),
    ("erp",       "Contabilidad / ERP", "📒"),
]

# (columna, etiqueta, es_secreto). `sistema` = nombre corto para la caluga;
# `categoria` = sección; `color` = fondo del logo.
PROVEEDORES = {
    "meta": {
        "sistema": "Meta Ads", "categoria": "marketing", "color": "#1877F2",
        "label": "Meta Ads — Marketing",
        "campos": [
            ("access_token", "Access Token", True),
            ("cuenta_id",    "Ad Account ID (act_…)", False),
        ],
    },
    "google_ads": {
        "sistema": "Google Ads", "categoria": "marketing", "color": "#4285F4",
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
        "sistema": "Toteat", "categoria": "pos", "color": "#FF6B35",
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
        "sistema": "Odoo", "categoria": "erp", "color": "#714B67",
        "label": "Odoo — Contabilidad",
        "campos": [
            ("access_token",   "API Key", True),
            ("cuenta_id",      "Base de datos (db)", False),
            ("config.url",     "URL", False),
            ("config.usuario", "Usuario", False),
        ],
    },
    "defontana": {
        "sistema": "Defontana", "categoria": "erp", "color": "#0EA5E9",
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
        sistema = meta.get("sistema", meta["label"])
        items.append({"proveedor": prov, "label": meta["label"], "sistema": sistema,
                      "categoria": meta.get("categoria", "otros"),
                      "color": meta.get("color", "#6b7280"), "sigla": sistema[:1].upper(),
                      "configurado": configurado, "tiene_token": tiene_token,
                      "con_muestra": prov in PROVEEDORES_CON_MUESTRA,
                      "activo": bool(row and row["activo"]), "campos": campos})

    # Agrupar en secciones, en el orden de CATEGORIAS (omite las vacías).
    secciones = []
    for clave, titulo, icono in CATEGORIAS:
        sec_items = [it for it in items if it["categoria"] == clave]
        if sec_items:
            secciones.append({"clave": clave, "titulo": titulo, "icono": icono,
                              "sistemas": sec_items})    # 'items' choca con dict.items en Jinja
    return {"tenant_id": tenant_id, "integraciones": items, "secciones": secciones}


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


# Proveedores con datos de muestra (mock): (función de sync, ventana de días).
_MUESTRA = {
    "meta":       (meta_ads.sincronizar,           120),
    "google_ads": (google_ads.sincronizar,         120),
    "toteat":     (toteat.sincronizar,              30),
    "odoo":       (odoo.sincronizar_contabilidad,   730),
}

PROVEEDORES_CON_MUESTRA = set(_MUESTRA)


async def cargar_muestra(tenant_id: str, proveedor: str) -> dict:
    """Carga datos de muestra (mock) del proveedor en el schema del tenant — como si
    se importaran del cliente. Requiere que existan las tablas del módulo."""
    if proveedor not in _MUESTRA:
        raise AdminError(f"'{proveedor}' no tiene datos de muestra.")
    if not _TENANT_RE.match(tenant_id):
        raise AdminError("ID de empresa inválido.")
    fn, dias = _MUESTRA[proveedor]
    hasta = date.today()
    desde = hasta - timedelta(days=dias)
    async with config.raw_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(f'SET LOCAL search_path = "{tenant_id}", public')
            try:
                res = await fn(conn, tenant_id, desde, hasta, mock=True)
            except Exception as e:                   # noqa: BLE001
                raise AdminError(f"No se pudo cargar la muestra de {proveedor}: {e}")
    logger.info(f"[admin] muestra {proveedor} cargada en {tenant_id}: {res}")
    return res


def _sql_marketing(plataforma: str) -> list[str]:
    """Borra los datos de marketing de UNA plataforma (no toca la otra)."""
    return [
        "DELETE FROM insights_marketing WHERE campana_id IN "
        "(SELECT c.id FROM campanas c JOIN canales_marketing ca ON ca.id = c.canal_id "
        f"WHERE ca.plataforma = '{plataforma}')",
        "DELETE FROM campanas WHERE canal_id IN "
        f"(SELECT id FROM canales_marketing WHERE plataforma = '{plataforma}')",
        f"DELETE FROM canales_marketing WHERE plataforma = '{plataforma}'",
    ]


# DELETEs por proveedor (orden respeta FKs; hijos primero). plataforma es constante.
_LIMPIEZA = {
    "meta":       _sql_marketing("meta"),
    "google_ads": _sql_marketing("google"),
    "odoo":       ["DELETE FROM saldos_cuentas", "DELETE FROM plan_cuentas"],
    "toteat":     ["DELETE FROM detalle_pedido", "DELETE FROM pagos", "DELETE FROM pedidos",
                   "DELETE FROM productos", "DELETE FROM categorias_menu",
                   "DELETE FROM mesas", "DELETE FROM canales_venta"],
}

PROVEEDORES_CON_DATOS = set(_LIMPIEZA)


async def limpiar_datos(tenant_id: str, proveedor: str) -> int:
    """Vacía los datos del módulo de ese proveedor en el schema del tenant (NO toca
    credenciales). Útil antes del cutover mock→real o al cambiar de plataforma.
    Devuelve filas eliminadas. Tolera tablas inexistentes (savepoint por statement)."""
    if proveedor not in _LIMPIEZA:
        raise AdminError(f"'{proveedor}' no tiene datos para limpiar.")
    if not _TENANT_RE.match(tenant_id):
        raise AdminError("ID de empresa inválido.")
    total = 0
    async with config.raw_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(f'SET LOCAL search_path = "{tenant_id}", public')
            for sql in _LIMPIEZA[proveedor]:
                try:
                    async with conn.transaction():        # savepoint
                        r = await conn.execute(sql)
                    total += int(r.rsplit(" ", 1)[-1]) if r.startswith("DELETE") else 0
                except asyncpg.UndefinedTableError:
                    continue                              # el tenant no tiene esa tabla
    logger.info(f"[admin] datos de {proveedor} limpiados en {tenant_id}: {total} filas")
    return total
