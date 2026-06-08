"""
Envío de reportes por correo.

El dashboard HTML se manda como cuerpo del email (para verlo al abrir el
correo) y además adjunto como archivo .html (para guardarlo). Usa smtplib
de la stdlib — sin dependencias nuevas.
"""

import logging
import re
import smtplib
import ssl
from datetime import date
from email.message import EmailMessage

from . import config

logger = logging.getLogger(__name__)

# El filtro de salida de mail.majorbi.com (v2nets) descarta silenciosamente
# los correos HTML que contienen emojis tras aceptarlos en SMTP (250 OK +
# queue id, pero nunca se entregan). Se eliminan del cuerpo del email para
# garantizar la entrega. La vista web (/dashboard-semanal?formato=html) los
# mantiene.
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF"   # pictogramas y símbolos
    "\U00002600-\U000027BF"    # misc símbolos / dingbats
    "\U0001F1E6-\U0001F1FF"    # indicadores regionales (banderas)
    "\U0000FE0F"               # variation selector-16
    "\U000020E3]+\\s?",        # combining enclosing keycap (+ espacio sobrante)
    flags=re.UNICODE,
)


def _strip_emojis(html: str) -> str:
    """Quita emojis del HTML para que el filtro de salida no descarte el correo."""
    return _EMOJI_RE.sub("", html)


def _destinatarios() -> list[str]:
    # Por-tenant: si el config del tenant define report.email_to, se usa eso;
    # si no, se cae al global REPORT_EMAIL_TO (env). Acepta lista o string coma-separado.
    lista = (config.get_config().get("report") or {}).get("email_to")
    if not lista:
        lista = config.REPORT_EMAIL_TO
    if isinstance(lista, str):
        lista = lista.split(",")
    return [d.strip() for d in lista if d and str(d).strip()]


def enviar_dashboard_email(html: str, cfg: dict, asunto: str | None = None,
                           destinatarios: list[str] | None = None) -> dict:
    """
    Envía el dashboard HTML por correo. Devuelve un dict con el resultado.
    Lanza RuntimeError si la configuración SMTP es insuficiente.

    `destinatarios` permite forzar los receptores (p. ej. para una previsualización
    dirigida); si no se pasa, se usan los del tenant / REPORT_EMAIL_TO.
    """
    if not config.email_disponible():
        raise RuntimeError(
            "Configuración SMTP incompleta. Definí SMTP_HOST, SMTP_FROM y "
            "REPORT_EMAIL_TO en el entorno."
        )

    biz   = cfg.get("business", {}).get("name", "Negocio")
    to    = destinatarios or _destinatarios()
    asunto = asunto or f"Dashboard Semanal — {biz} — {date.today():%d/%m/%Y}"

    # El filtro de salida descarta correos con emojis: limpiarlos del cuerpo.
    html = _strip_emojis(html)

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"]    = config.SMTP_FROM
    msg["To"]      = ", ".join(to)

    # Plain text fallback — sin URLs con IP cruda (disparador de spam).
    msg.set_content(
        "Tu cliente de correo no muestra HTML. El dashboard va en el cuerpo del mensaje."
    )

    # Agregar HTML como alternativa
    msg.add_alternative(html, subtype="html")

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
