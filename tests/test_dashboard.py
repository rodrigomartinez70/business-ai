"""
Tests del dashboard semanal (cálculo consolidado + render HTML + envío email).

Los insights IA y el SMTP se mockean para que los tests sean deterministas
y no dependan de red. Los cálculos corren contra la DB de test real.
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.dashboard import _detectar_problemas


@pytest.fixture(autouse=True)
def _mock_insights():
    """Evita llamadas a Claude/Ollama: insights deterministas y rápidos."""
    with patch("src.dashboard.generar_insights", new=AsyncMock(return_value=["insight de prueba"])):
        yield


@pytest.mark.asyncio
async def test_dashboard_html(client, gerente_headers):
    resp = await client.get("/api/agents/dashboard-semanal?formato=html", headers=gerente_headers)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    html = resp.text
    # Las 7 secciones presentes
    for marca in ["Puntos de atención", "📑 P&L", "💵 Cash Flow", "🏪 Rentabilidad",
                  "📊 Revenue", "📋 Control de Gastos", "🧾 Cierre de la semana"]:
        assert marca in html, f"falta sección: {marca}"


@pytest.mark.asyncio
async def test_dashboard_orden_secciones(client, gerente_headers):
    html = (await client.get("/api/agents/dashboard-semanal?formato=html", headers=gerente_headers)).text
    # Orden por importancia: cada título de tarjeta aparece después del anterior
    titulos = ["<h2>📑 P&L", "<h2>💵 Cash Flow", "<h2>🏪 Rentabilidad",
               "<h2>📊 Revenue", "<h2>📋 Control de Gastos", "<h2>🧾 Cierre de la semana"]
    pos = [html.index(t) for t in titulos]
    assert pos == sorted(pos), f"secciones fuera de orden: {pos}"


@pytest.mark.asyncio
async def test_dashboard_insights_solo_pnl_y_rent(client, gerente_headers):
    html = (await client.get("/api/agents/dashboard-semanal?formato=html", headers=gerente_headers)).text
    # Insights IA aparece exactamente 2 veces (P&L + Rentabilidad)
    assert html.count("💡 Insights IA") == 2


@pytest.mark.asyncio
async def test_dashboard_json(client, gerente_headers):
    data = (await client.get("/api/agents/dashboard-semanal?formato=json", headers=gerente_headers)).json()
    for campo in ("fecha_envio", "semana", "problemas", "pnl", "cash",
                  "rent", "revenue", "gastos", "cierre"):
        assert campo in data
    assert "inicio" in data["semana"] and "fin" in data["semana"]
    # P&L YTD: el período empieza el 1 de enero
    assert data["pnl"]["periodo"]["inicio"].endswith("-01-01")


@pytest.mark.asyncio
async def test_dashboard_email_mock(client, gerente_headers):
    from src import config

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self, **k): pass
        def login(self, *a): pass
        def send_message(self, *a, **k): pass

    with patch.multiple(config, SMTP_HOST="smtp.test", SMTP_FROM="from@test.com",
                        REPORT_EMAIL_TO="dueno@test.com", SMTP_USE_TLS=True,
                        SMTP_USER="", SMTP_PASSWORD=""), \
         patch("smtplib.SMTP", FakeSMTP):
        resp = await client.get("/api/agents/dashboard-semanal?formato=email", headers=gerente_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["enviado"] is True
    assert body["destinatarios"] == ["dueno@test.com"]


@pytest.mark.asyncio
async def test_dashboard_requiere_auth(client):
    resp = await client.get("/api/agents/dashboard-semanal")
    assert resp.status_code == 403


# ── unitario: detección de problemas ──────────────────────────────────────────

def test_detectar_problemas_ordena_criticos_primero():
    pnl    = {"actual": {"resultado": {"estado": "negativo"}}}
    cash   = {"semaforo": "alerta", "resumen": {}}
    gastos = {"alertas": []}
    rent   = {"totales": {"tasa_cancel_pct": 5}}
    cierre = {"totales": {"gop_estado": "positivo"}}
    probs = _detectar_problemas(pnl, cash, gastos, rent, cierre)
    # GOP YTD negativo (crítico) + cash flow alerta
    niveles = [p["nivel"] for p in probs]
    assert "critico" in niveles
    # los críticos van primero
    assert niveles == sorted(niveles, key=lambda n: 0 if n == "critico" else 1)


def test_detectar_problemas_sin_problemas():
    pnl    = {"actual": {"resultado": {"estado": "positivo"}}}
    cash   = {"semaforo": "ok", "resumen": {}}
    gastos = {"alertas": []}
    rent   = {"totales": {"tasa_cancel_pct": 5}}
    cierre = {"totales": {"gop_estado": "positivo"}}
    assert _detectar_problemas(pnl, cash, gastos, rent, cierre) == []
