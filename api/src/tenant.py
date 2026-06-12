"""
Contexto de tenant para requests async.

Cada request autentica una API key que resuelve a un TenantContext.
El contexto se propaga por el call stack via contextvars — asyncio copia
el Context por coroutine, por lo que cada request ve su propio tenant
sin pasar parámetros explícitos.

Uso:
    # En el middleware/dependency (auth.py):
    token = set_tenant(ctx)

    # En cualquier punto del call stack del mismo request:
    ctx = get_tenant()
    ctx.biz("name")        → nombre del negocio
    ctx.schema_for("gerente") → schema text para el LLM
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TenantContext:
    tenant_id:    str    # 'hotel_mbi', 'restaurante_xyz'
    rol:          str    # 'gerente', 'administracion', 'recepcion'
    vertical:     str    # 'hotel', 'restaurante'
    config:       dict   # contenido del config.yaml del tenant
    schema_cache: dict   # {rol: schema_text} — schema PostgreSQL para el LLM
    packs:        list = field(default_factory=list)   # packs de datos activos (base, pos_*, erp)

    # ── Helpers de acceso al config ───────────────────────────

    def biz(self, key: str, default: str = "") -> str:
        return self.config.get("business", {}).get(key, default)

    def schema_for(self, rol: str) -> str:
        return self.schema_cache.get(rol, self.schema_cache.get("default", ""))

    def kpis_text(self) -> str:
        kpis = self.config.get("kpis", [])
        if not kpis:
            return ""
        return "\n".join(
            ["KPIs del dominio:"] + [f"- {k['name']}: {k['description']}" for k in kpis]
        )

    def aliases_text(self) -> str:
        aliases = self.config.get("table_aliases", {})
        if not aliases:
            return ""
        return "Aliases sugeridos: " + ", ".join(f"{t}→{a}" for t, a in aliases.items())

    def currency_hint(self) -> str:
        cur  = self.config.get("currency", {})
        sym  = cur.get("symbol", "$")
        tsep = cur.get("thousands_separator", ".")
        dp   = cur.get("decimal_places", 0)
        if dp == 0:
            return f"Formato moneda: {sym}1{tsep}234{tsep}567 (sin decimales)"
        dsep = cur.get("decimal_separator", ",")
        return f"Formato moneda: {sym}1{tsep}234{tsep}567{dsep}{dp * '0'}"

    def get_config(self) -> dict:
        return self.config


# ── Contextvar ────────────────────────────────────────────────
# Default=None para poder detectar llamadas fuera de un request.

_current_tenant: contextvars.ContextVar[Optional[TenantContext]] = \
    contextvars.ContextVar("current_tenant", default=None)


def get_tenant() -> TenantContext:
    """
    Retorna el TenantContext del request actual.
    Lanza RuntimeError si se llama fuera de un request (ej. lifespan, tests sin fixture).
    """
    ctx = _current_tenant.get()
    if ctx is None:
        raise RuntimeError(
            "TenantContext no inicializado. "
            "¿Llamada fuera de un request o fixture de test sin set_tenant()?"
        )
    return ctx


def set_tenant(ctx: TenantContext) -> contextvars.Token:
    """
    Setea el TenantContext para el request actual.
    Retorna el Token necesario para restaurar el estado anterior con reset_tenant().
    """
    return _current_tenant.set(ctx)


def reset_tenant(token: contextvars.Token) -> None:
    """
    Restaura el contextvar al estado anterior al set_tenant().
    Solo válido si se llama desde el mismo asyncio Context que creó el token.
    Para fixtures de pytest-asyncio usar clear_tenant() en su lugar.
    """
    _current_tenant.reset(token)


def clear_tenant() -> None:
    """
    Limpia el TenantContext activo sin necesitar el token original.
    Seguro para usar en teardown de fixtures pytest-asyncio donde setup
    y teardown pueden correr en distintos asyncio Context.
    """
    _current_tenant.set(None)


def get_tenant_or_none() -> Optional[TenantContext]:
    """Versión que no lanza — útil para código que puede correr dentro o fuera de request."""
    return _current_tenant.get()
