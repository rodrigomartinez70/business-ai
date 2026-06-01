"""
Pool de DB con aislamiento por tenant.

TenantAwarePool envuelve asyncpg.Pool e inyecta
    SET search_path = <tenant_id>, public
en cada conexión adquirida, de forma que todo SQL ejecutado dentro
de un acquire() resuelve automáticamente al schema del tenant activo.

Los agentes no saben nada de multi-tenancy: siguen haciendo
    async with config.db_pool.acquire() as conn:
y obtienen una conexión ya apuntada al schema correcto.

Por qué SET search_path en lugar de un pool por tenant:
- Un pool por tenant escala mal: N tenants × min_size conexiones TCP.
- asyncpg resetea la sesión al devolver la conexión al pool, por lo
  que el search_path del request anterior no contamina al siguiente.
- El overhead de SET search_path es < 0.1 ms por acquire().
"""

import asyncpg
from contextlib import asynccontextmanager

from .tenant import get_tenant


class TenantAwarePool:
    """
    Wrapper de asyncpg.Pool que inyecta search_path por tenant en cada acquire().

    Expone la misma interfaz que asyncpg.Pool para que los callers
    existentes no noten la diferencia.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @asynccontextmanager
    async def acquire(self):
        from .tenant import get_tenant_or_none
        ctx = get_tenant_or_none()
        tenant_id = ctx.tenant_id if ctx is not None else "public"
        async with self._pool.acquire() as conn:
            await conn.execute(f"SET search_path = {tenant_id}, public")
            yield conn

    # ── Métodos de conveniencia (delegados a acquire) ─────────

    async def fetch(self, query: str, *args):
        async with self.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        async with self.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        async with self.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def execute(self, query: str, *args):
        async with self.acquire() as conn:
            return await conn.execute(query, *args)

    async def close(self) -> None:
        await self._pool.close()
