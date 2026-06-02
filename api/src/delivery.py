"""
Envío de reportes por correo.

El dashboard HTML se manda como cuerpo del email (para verlo al abrir el
correo) y además adjunto como archivo .html (para guardarlo). Usa smtplib
de la stdlib — sin dependencias nuevas.
"""

import logging
import smtplib
import ssl
from datetime import date
from email.message import EmailMessage

from . import config

logger = logging.getLogger(__name__)


def _destinatarios() -> list[str]:
    return [d.strip() for d in config.REPORT_EMAIL_TO.split(",") if d.strip()]


def enviar_dashboard_email(html: str, cfg: dict, asunto: str | None = None) -> dict:
    """
    Envía el dashboard HTML por correo. Devuelve un dict con el resultado.
    Lanza RuntimeError si la configuración SMTP es insuficiente.
    """
    if not config.email_disponible():
        raise RuntimeError(
            "Configuración SMTP incompleta. Definí SMTP_HOST, SMTP_FROM y "
            "REPORT_EMAIL_TO en el entorno."
        )

    biz   = cfg.get("business", {}).get("name", "Negocio")
    to    = _destinatarios()
    asunto = asunto or f"📈 Dashboard Semanal — {biz} — {date.today():%d/%m/%Y}"

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"]    = config.SMTP_FROM
    msg["To"]      = ", ".join(to)

    # Plain text fallback (sin HTML adjunto que puede ser bloqueado)
    msg.set_content(
        "Dashboard generado. Accede a: http://178.104.160.82:8000/api/agents/dashboard-semanal?formato=html"
    )

    # Agregar HTML como alternativa
    msg.add_alternative(html, subtype="html")

    # NO adjuntar el archivo HTML - algunos servidores lo bloquean
    # nombre = f"dashboard_{date.today():%Y%m%d}.html"
    # msg.add_attachment(
    #     html.encode("utf-8"), maintype="text", subtype="html", filename=nombre
    # )

    _entregar(msg, to)
    logger.info(f"Dashboard enviado a {len(to)} destinatario(s).")
    return {"enviado": True, "destinatarios": to, "asunto": asunto}


def _entregar(msg: EmailMessage, to: list[str]) -> None:
    """Abre la conexión SMTP y entrega el mensaje.

    Puerto 465 → SSL directo (SMTPS).
    Puerto 587 / resto → STARTTLS si SMTP_USE_TLS=true.
    """
    ctx = ssl.create_default_context()
    try:
        if config.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=ctx, timeout=30) as srv:
                if config.SMTP_USER:
                    srv.login(config.SMTP_USER, config.SMTP_PASSWORD)
                result = srv.send_message(msg, from_addr=config.SMTP_FROM, to_addrs=to)
                if result:
                    logger.warning(f"SMTP respuesta parcial: {result}")
        elif config.SMTP_USE_TLS:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as srv:
                srv.starttls(context=ctx)
                if config.SMTP_USER:
                    srv.login(config.SMTP_USER, config.SMTP_PASSWORD)
                result = srv.send_message(msg, from_addr=config.SMTP_FROM, to_addrs=to)
                if result:
                    logger.warning(f"SMTP respuesta parcial: {result}")
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as srv:
                if config.SMTP_USER:
                    srv.login(config.SMTP_USER, config.SMTP_PASSWORD)
                result = srv.send_message(msg, from_addr=config.SMTP_FROM, to_addrs=to)
                if result:
                    logger.warning(f"SMTP respuesta parcial: {result}")
    except smtplib.SMTPRecipientsRefused as e:
        logger.error(f"SMTP rechazó destinatarios: {e}")
        raise
    except smtplib.SMTPSenderRefused as e:
        logger.error(f"SMTP rechazó remitente: {e}")
        raise
    except Exception as e:
        logger.error(f"Error SMTP desconocido: {e}")
        raise
