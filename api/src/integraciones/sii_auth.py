"""
Autenticación SII con certificado digital (Fase B).

Flujo del SII:
  1. CrSeed.jws         → semilla (GET).
  2. Firmar la semilla con el certificado (XML-DSig enveloped, RSA-SHA1, C14N) →
     documento <getToken> firmado.
  3. GetTokenFromSeed.jws → token (POST con el XML firmado).

El token se usa luego para consultar el RCV / estado de DTE.

La firma se arma a mano (cryptography + lxml) para controlar exactamente el SHA1 y
la canonicalización que espera el SII. La parte de red (SOAP de CrSeed/GetToken)
queda lista para iterar contra maullin con un certificado real — es lo único que no
se puede verificar sin cert.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re

import httpx
from lxml import etree
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

logger = logging.getLogger(__name__)

_DS = "http://www.w3.org/2000/09/xmldsig#"
_C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"

AMBIENTES = {
    "certificacion": "https://maullin.sii.cl/DTEWS",
    "produccion":    "https://palena.sii.cl/DTEWS",
}


class SiiAuthError(Exception):
    """Error de certificado o autenticación con el SII."""


# ─────────────────────────────────────────────────────────────
# Certificado
# ─────────────────────────────────────────────────────────────

def cargar_pfx(pfx_bytes: bytes, password: str):
    """Abre un .pfx/.p12 → (private_key, cert). Lanza SiiAuthError si la clave es
    incorrecta o el archivo no es válido."""
    try:
        key, cert, _ = load_key_and_certificates(
            pfx_bytes, password.encode() if password else None)
    except Exception as e:                       # noqa: BLE001
        raise SiiAuthError(f"No se pudo abrir el certificado (¿clave correcta?): {e}")
    if key is None or cert is None:
        raise SiiAuthError("El archivo no contiene una clave privada + certificado válidos.")
    return key, cert


def info_cert(cert) -> dict:
    """Titular, RUT y vencimiento del certificado (para mostrar en la UI)."""
    def _attr(oid_name):
        for a in cert.subject:
            if a.oid._name == oid_name:
                return a.value
        return ""
    return {
        "titular": _attr("commonName"),
        "rut": _attr("serialNumber"),
        "vence": str(getattr(cert, "not_valid_after_utc", cert.not_valid_after).date()),
    }


# ─────────────────────────────────────────────────────────────
# Firma de la semilla (XML-DSig enveloped, RSA-SHA1)
# ─────────────────────────────────────────────────────────────

def _c14n(el) -> bytes:
    return etree.tostring(el, method="c14n")


def firmar_semilla(seed: str, key, cert) -> bytes:
    """Documento <getToken> con la semilla, firmado (enveloped) — bytes UTF-8."""
    root = etree.Element("getToken")
    item = etree.SubElement(root, "item")
    etree.SubElement(item, "Semilla").text = str(seed)

    # Digest del documento sin la firma (enveloped).
    digest = base64.b64encode(hashlib.sha1(_c14n(root)).digest()).decode()

    sig = etree.SubElement(root, f"{{{_DS}}}Signature")
    si  = etree.SubElement(sig, f"{{{_DS}}}SignedInfo")
    etree.SubElement(si, f"{{{_DS}}}CanonicalizationMethod", Algorithm=_C14N)
    etree.SubElement(si, f"{{{_DS}}}SignatureMethod", Algorithm=f"{_DS}rsa-sha1")
    ref = etree.SubElement(si, f"{{{_DS}}}Reference", URI="")
    trs = etree.SubElement(ref, f"{{{_DS}}}Transforms")
    etree.SubElement(trs, f"{{{_DS}}}Transform", Algorithm=f"{_DS}enveloped-signature")
    etree.SubElement(ref, f"{{{_DS}}}DigestMethod", Algorithm=f"{_DS}sha1")
    etree.SubElement(ref, f"{{{_DS}}}DigestValue").text = digest

    firma = key.sign(_c14n(si), padding.PKCS1v15(), hashes.SHA1())
    etree.SubElement(sig, f"{{{_DS}}}SignatureValue").text = base64.b64encode(firma).decode()

    ki = etree.SubElement(sig, f"{{{_DS}}}KeyInfo")
    x509 = etree.SubElement(ki, f"{{{_DS}}}X509Data")
    etree.SubElement(x509, f"{{{_DS}}}X509Certificate").text = \
        base64.b64encode(cert.public_bytes(Encoding.DER)).decode()

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


# ─────────────────────────────────────────────────────────────
# Llamadas al SII (CrSeed → GetTokenFromSeed)
# ─────────────────────────────────────────────────────────────

def _extraer(tag: str, texto: str) -> str | None:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", texto, re.S)
    return m.group(1).strip() if m else None


async def pedir_semilla(base: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{base}/CrSeed.jws")
        resp.raise_for_status()
        seed = _extraer("SEMILLA", resp.text)
    if not seed:
        raise SiiAuthError(f"El SII no devolvió SEMILLA: {resp.text[:200]}")
    return seed


async def pedir_token(base: str, xml_firmado: bytes) -> str:
    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
        '<SOAP-ENV:Body><getToken xmlns="http://DefaultNamespace">'
        f'<pszXml><![CDATA[{xml_firmado.decode("utf-8")}]]></pszXml>'
        '</getToken></SOAP-ENV:Body></SOAP-ENV:Envelope>'
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{base}/GetTokenFromSeed.jws", content=envelope.encode(),
                                 headers={"Content-Type": "text/xml; charset=utf-8"})
        resp.raise_for_status()
        token = _extraer("TOKEN", resp.text)
    if not token:
        raise SiiAuthError(f"El SII no devolvió TOKEN: {resp.text[:300]}")
    return token


async def obtener_token(pfx_bytes: bytes, password: str, ambiente: str = "certificacion") -> str:
    """Semilla → firma → token. Devuelve el token de sesión del SII."""
    base = AMBIENTES.get(ambiente, AMBIENTES["certificacion"])
    key, cert = cargar_pfx(pfx_bytes, password)
    seed = await pedir_semilla(base)
    xml = firmar_semilla(seed, key, cert)
    token = await pedir_token(base, xml)
    logger.info(f"[sii] token obtenido ({ambiente})")
    return token
