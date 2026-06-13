"""
Tests del motor de auth SII (Fase B) — carga de certificado + firma de la semilla.
Sin red: se genera un certificado autofirmado para verificar la mecánica de la firma
XML-DSig. La auth en vivo contra maullin necesita un certificado real.
"""

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("cryptography")
pytest.importorskip("lxml")

import base64
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree

from src.integraciones import sii_auth

_NS = {"ds": "http://www.w3.org/2000/09/xmldsig#"}


def _generar_pfx(password="clave123"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Empresa Test SpA"),
        x509.NameAttribute(NameOID.SERIAL_NUMBER, "76.111.222-3"),
    ])
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
            .sign(key, hashes.SHA256()))
    pfx = pkcs12.serialize_key_and_certificates(
        b"test", key, cert, None, serialization.BestAvailableEncryption(password.encode()))
    return pfx


def test_cargar_pfx_y_leer_info():
    key, cert = sii_auth.cargar_pfx(_generar_pfx(), "clave123")
    info = sii_auth.info_cert(cert)
    assert info["titular"] == "Empresa Test SpA"
    assert info["rut"] == "76.111.222-3"
    assert info["vence"]


def test_cargar_pfx_clave_incorrecta():
    with pytest.raises(sii_auth.SiiAuthError):
        sii_auth.cargar_pfx(_generar_pfx(), "clave-mala")


def test_firmar_semilla_estructura_y_firma_verificable():
    key, cert = sii_auth.cargar_pfx(_generar_pfx(), "clave123")
    xml = sii_auth.firmar_semilla("000000012345", key, cert)
    root = etree.fromstring(xml)

    assert root.tag == "getToken"
    assert root.findtext("item/Semilla") == "000000012345"

    si = root.find("ds:Signature/ds:SignedInfo", _NS)
    assert si is not None
    sigval = root.findtext("ds:Signature/ds:SignatureValue", namespaces=_NS)
    assert sigval

    # La firma del SignedInfo debe verificar con la clave pública del certificado.
    si_c14n = etree.tostring(si, method="c14n")
    cert.public_key().verify(
        base64.b64decode(sigval), si_c14n, padding.PKCS1v15(), hashes.SHA1())

    # El X509Certificate embebido corresponde al cert.
    x509_b64 = root.findtext("ds:Signature/ds:KeyInfo/ds:X509Data/ds:X509Certificate", namespaces=_NS)
    assert base64.b64decode(x509_b64) == cert.public_bytes(serialization.Encoding.DER)
