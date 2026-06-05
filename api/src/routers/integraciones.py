"""
Endpoints de integraciones externas (Meta Ads, etc.).

El cron dispara estos endpoints; la lógica de sincronización vive en
src.integraciones.*. La autenticación define el tenant (cada negocio sincroniza
su propia cuenta, con sus credenciales en public.integraciones).
"""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import config
from ..auth import get_tenant_ctx
from ..integraciones import meta_ads, toteat
from ..tenant import TenantContext

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/integraciones", tags=["integraciones"])


@router.post("/meta/sync")
async def sync_meta(
    dias: int = Query(120, ge=1, le=365, description="Ventana a sincronizar hacia atrás"),
    ctx: TenantContext = Depends(get_tenant_ctx),
):
    """
    Sincroniza los insights de Meta Ads del tenant autenticado hacia Postgres.

    Idempotente (upsert). Lee las credenciales de public.integraciones para ese
    tenant. Pensado para ejecutarse a diario desde el cron. Sincroniza una ventana
    amplia (default 120 días) para que las comparativas del dashboard tengan
    cobertura suficiente.
    """
    hasta = date.today()
    desde = hasta - timedelta(days=dias)
    try:
        async with config.db_pool.acquire() as conn:
            res = await meta_ads.sincronizar(conn, ctx.tenant_id, desde, hasta, mock=False)
    except RuntimeError as e:
        # Sin credenciales cargadas para el tenant.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Sync Meta falló para '{ctx.tenant_id}': {e}")
        raise HTTPException(status_code=502, detail="No se pudo sincronizar con Meta.")
    logger.info(f"Sync Meta OK '{ctx.tenant_id}': {res}")
    return res


@router.post("/toteat/sync")
async def sync_toteat(
    dias: int = Query(7, ge=1, le=800, description="Ventana a sincronizar hacia atrás"),
    mock: bool = Query(False, description="Genera datos de muestra (sin llamar a Toteat)"),
    ctx: TenantContext = Depends(get_tenant_ctx),
):
    """
    Sincroniza ventas/menú de Toteat hacia las tablas del vertical del tenant.

    Pensado para el cron DIARIO (ventana chica, ej. 7 días — idempotente). El
    backfill histórico (ej. 2 años) conviene correrlo como script one-off, no por
    HTTP, porque con el throttle de Toteat (3/min) puede tardar ~16 min.
    """
    hasta = date.today()
    desde = hasta - timedelta(days=dias)
    try:
        async with config.db_pool.acquire() as conn:
            res = await toteat.sincronizar(conn, ctx.tenant_id, desde, hasta, mock=mock)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Sync Toteat falló para '{ctx.tenant_id}': {e}")
        raise HTTPException(status_code=502, detail="No se pudo sincronizar con Toteat.")
    logger.info(f"Sync Toteat OK '{ctx.tenant_id}': {res}")
    return res
