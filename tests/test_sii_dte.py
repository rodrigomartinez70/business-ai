"""Tests del agente de estado DTE en el SII (mock, sin red ni cert)."""
from datetime import date
import pytest
from src.integraciones import sii_dte


def test_estados_incluye_dok_y_glosas():
    assert sii_dte.ESTADO_OK == "DOK"
    assert "DOK" in sii_dte.ESTADOS_DTE and "DNK" in sii_dte.ESTADOS_DTE


@pytest.mark.asyncio
async def test_verificar_estado_dte_mock():
    d = await sii_dte.verificar_estado_dte(None, "restaurante_toteat", date(2026, 6, 15), mock=True)
    assert d["total"] > 0
    assert d["dok"] + d["no_dok"] == d["total"]
    assert sum(d["por_estado"].values()) == d["total"]
    # el listado son SOLO los != DOK
    assert len(d["listado"]) == d["no_dok"]
    assert all(x["estado"] != "DOK" for x in d["listado"])
    assert d["periodo"]["mes"] == "2026-06"


def test_mock_determinista_por_mes():
    a = sii_dte._mock_dtes(date(2026, 6, 1), date(2026, 6, 30))
    b = sii_dte._mock_dtes(date(2026, 6, 1), date(2026, 6, 30))
    assert [x["folio"] for x in a] == [x["folio"] for x in b]
