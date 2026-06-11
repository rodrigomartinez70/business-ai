"""
Programación de reportes por correo (DB-driven, gestionable desde MBI Admin).

Reemplaza los crons-archivo por filas en public.report_schedules. Un cron lector
golpea POST /api/admin/schedules/tick cada ~15 min; `ejecutar_pendientes()` recorre
los schedules activos, renderiza el reporte de cada tenant (seteando su contexto) y
lo envía a sus destinatarios. Todo en hora de Chile, con dedupe por `last_run`.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import config, tenant_registry
from ..tenant import set_tenant, reset_tenant
from ..delivery import enviar_dashboard_email

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("America/Santiago")

DIAS = {1: "Lunes", 2: "Martes", 3: "Miércoles", 4: "Jueves",
        5: "Viernes", 6: "Sábado", 7: "Domingo"}
REPORTES = {"informe_financiero": "Informe Financiero"}


class AdminError(Exception):
    """Error de validación de schedule (→ 400)."""


def _parse_dest(s: str | None) -> list[str]:
    return [e.strip() for e in (s or "").replace(";", ",").split(",") if e.strip()]


# ─────────────────────────────────────────────────────────────
# Render dispatch — qué HTML/asunto produce cada tipo de reporte.
# Asume que el contexto de tenant ya está seteado.
# ─────────────────────────────────────────────────────────────

async def _render(reporte: str) -> tuple[str, str, dict]:
    from datetime import date
    from ..finanzas.informe import calcular_informe, renderizar_informe_html
    cfg = config.get_config()
    biz = cfg.get("business", {}).get("name", "Negocio")
    if reporte == "informe_financiero":
        corte = date.today()
        data = await calcular_informe(corte)
        html = renderizar_informe_html(data, cfg, biz)
        return html, f"Informe Financiero — {biz} — {corte:%d/%m/%Y}", cfg
    raise AdminError(f"Reporte desconocido: {reporte}")


# ─────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────

async def listar() -> list[dict]:
    rows = await config.raw_pool.fetch(
        """SELECT s.*, t.nombre AS tenant_nombre, t.activo AS tenant_activo
             FROM public.report_schedules s
             JOIN public.tenants t ON t.id = s.tenant_id
            ORDER BY s.tenant_id, s.dia_semana, s.hora""")
    return [dict(r) for r in rows]


async def crear(*, tenant_id: str, reporte: str, dia_semana: int,
                hora: int, minuto: int, destinatarios: str | None) -> dict:
    if reporte not in REPORTES:
        raise AdminError(f"Reporte inválido. Opciones: {', '.join(REPORTES)}.")
    if not (1 <= dia_semana <= 7):
        raise AdminError("Día de la semana inválido (1=lunes … 7=domingo).")
    if not (0 <= hora <= 23) or not (0 <= minuto <= 59):
        raise AdminError("Hora inválida.")
    existe = await config.raw_pool.fetchval(
        "SELECT 1 FROM public.tenants WHERE id = $1", tenant_id)
    if not existe:
        raise AdminError(f"No existe la empresa '{tenant_id}'.")
    dest = ", ".join(_parse_dest(destinatarios))
    sid = await config.raw_pool.fetchval(
        """INSERT INTO public.report_schedules
               (tenant_id, reporte, dia_semana, hora, minuto, destinatarios)
           VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
        tenant_id, reporte, dia_semana, hora, minuto, dest or None)
    logger.info(f"[admin] schedule creado #{sid} {tenant_id} {reporte} d{dia_semana} {hora:02d}:{minuto:02d}")
    return {"id": sid}


async def obtener(sid: int) -> dict | None:
    r = await config.raw_pool.fetchrow(
        """SELECT s.*, t.nombre AS tenant_nombre
             FROM public.report_schedules s
             JOIN public.tenants t ON t.id = s.tenant_id
            WHERE s.id = $1""", sid)
    return dict(r) if r else None


async def actualizar(*, sid: int, dia_semana: int, hora: int, minuto: int,
                     destinatarios: str | None) -> None:
    if not (1 <= dia_semana <= 7):
        raise AdminError("Día de la semana inválido (1=lunes … 7=domingo).")
    if not (0 <= hora <= 23) or not (0 <= minuto <= 59):
        raise AdminError("Hora inválida.")
    dest = ", ".join(_parse_dest(destinatarios))
    await config.raw_pool.execute(
        """UPDATE public.report_schedules
              SET dia_semana = $2, hora = $3, minuto = $4, destinatarios = $5
            WHERE id = $1""",
        sid, dia_semana, hora, minuto, dest or None)
    logger.info(f"[admin] schedule #{sid} actualizado → d{dia_semana} {hora:02d}:{minuto:02d}")


async def set_activo(sid: int, activo: bool) -> None:
    await config.raw_pool.execute(
        "UPDATE public.report_schedules SET activo = $2 WHERE id = $1", sid, activo)


async def eliminar(sid: int) -> None:
    await config.raw_pool.execute(
        "DELETE FROM public.report_schedules WHERE id = $1", sid)


# ─────────────────────────────────────────────────────────────
# Ejecución (la golpea el cron lector)
# ─────────────────────────────────────────────────────────────

async def ejecutar_pendientes() -> dict:
    """Envía los reportes cuyo horario (hora Chile) ya venció hoy y no se enviaron aún."""
    ahora = datetime.now(_TZ)
    hoy   = ahora.date()
    iso   = hoy.isoweekday()
    min_actual = ahora.hour * 60 + ahora.minute

    rows = await config.raw_pool.fetch(
        """SELECT * FROM public.report_schedules
            WHERE activo = TRUE AND dia_semana = $1
              AND (hora * 60 + minuto) <= $2
              AND (last_run IS NULL OR last_run < $3)""",
        iso, min_actual, hoy)

    enviados, errores = [], []
    for r in rows:
        try:
            ctx = tenant_registry.get_tenant_by_id(r["tenant_id"])
            if ctx is None:
                raise RuntimeError(f"tenant '{r['tenant_id']}' inactivo o desconocido")
            token = set_tenant(ctx)
            try:
                html, asunto, cfg = await _render(r["reporte"])
                dest = _parse_dest(r["destinatarios"]) or None
                res = enviar_dashboard_email(html, cfg, asunto=asunto, destinatarios=dest)
            finally:
                reset_tenant(token)
            await config.raw_pool.execute(
                "UPDATE public.report_schedules SET last_run = $2 WHERE id = $1", r["id"], hoy)
            enviados.append({"id": r["id"], "tenant": r["tenant_id"],
                             "destinatarios": res.get("destinatarios", [])})
        except Exception as e:                       # noqa: BLE001 — un schedule no debe tumbar el resto
            logger.exception(f"[scheduler] schedule #{r['id']} falló")
            errores.append({"id": r["id"], "tenant": r["tenant_id"], "error": str(e)})

    return {"hora_chile": ahora.strftime("%Y-%m-%d %H:%M"),
            "evaluados": len(rows), "enviados": enviados, "errores": errores}
