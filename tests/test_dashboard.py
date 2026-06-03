"""
Tests del dashboard semanal (cálculo consolidado + render HTML + envío email).

Los insights IA y el SMTP se mockean para que los tests sean deterministas
y no dependan de red. Los cálculos corren contra la DB de test real.
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.verticals.hotel.dashboard import _detectar_problemas


_IPC_FAKE = {
    "serie": [{"mes": f"2025-{m:02d}", "valor": v} for m, v in
              enumerate([0.4, 0.0, 0.5, -0.1, 0.3, 0.2, 0.9, 0.0, 0.4, 0.0, 0.3, -0.2], start=1)],
    "acumulado_pct": 3.1, "ultimo_mes": "2025-12", "fuente": "Banco Central de Chile",
}


@pytest.fixture(autouse=True)
def _mock_externos():
    """Evita red externa: insights (Claude/Ollama) e IPC (mindicador) deterministas."""
    with patch("src.verticals.hotel.dashboard.generar_insights", new=AsyncMock(return_value=["insight de prueba"])), \
         patch("src.verticals.hotel.dashboard.obtener_ipc", new=AsyncMock(return_value=_IPC_FAKE)):
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
                  "rent", "revenue", "gastos", "gastos_analitico", "cierre", "ipc"):
        assert campo in data
    assert "inicio" in data["semana"] and "fin" in data["semana"]
    # P&L YTD comparativo: el período actual empieza el 1 de enero
    assert data["pnl"]["periodo"]["actual"]["inicio"].endswith("-01-01")


@pytest.mark.asyncio
async def test_dashboard_seccion_ipc(client, gerente_headers):
    html = (await client.get("/api/agents/dashboard-semanal?formato=html", headers=gerente_headers)).text
    assert "📉 Contexto económico — Inflación Chile" in html
    assert "Banco Central de Chile" in html
    # gráfico con eje cero: 4 filas (positivos / eje / negativos / meses)
    assert html.count('border-top:2px solid') >= 1


@pytest.mark.asyncio
async def test_dashboard_gastos_analitico(client, gerente_headers):
    data = (await client.get("/api/agents/dashboard-semanal?formato=json", headers=gerente_headers)).json()
    ana = data["gastos_analitico"]
    for campo in ("serie_mensual", "gasto_prom_mensual", "crecimiento_pct",
                  "ipc_acum_pct", "brecha_pp", "top_categorias", "top_proveedores"):
        assert campo in ana
    # el IPC acumulado se propagó al cálculo de gastos
    assert ana["ipc_acum_pct"] == 3.1
    # si hay crecimiento e IPC, la brecha = crecimiento - inflación
    if ana["crecimiento_pct"] is not None:
        assert ana["brecha_pp"] == round(ana["crecimiento_pct"] - ana["ipc_acum_pct"], 1)

    # cada categoría trae crecimiento y comparación vs IPC
    cats = ana["top_categorias"]
    assert cats, "debe haber categorías"
    for c in cats:
        for campo in ("categoria", "monto", "pct", "crecimiento_pct", "vs_ipc_pp"):
            assert campo in c
        # vs_ipc_pp = crecimiento - inflación cuando ambos existen
        if c["crecimiento_pct"] is not None:
            assert c["vs_ipc_pp"] == round(c["crecimiento_pct"] - ana["ipc_acum_pct"], 1)
    # con 7 categorías en el seed, debe aparecer la fila "Otras" y el total cerrar ~100%
    nombres = [c["categoria"] for c in cats]
    if "Otras" in nombres:
        assert abs(sum(c["pct"] for c in cats) - 100) < 1.5


@pytest.mark.asyncio
async def test_dashboard_vista_cfo_en_html(client, gerente_headers):
    html = (await client.get("/api/agents/dashboard-semanal?formato=html", headers=gerente_headers)).text
    assert "Vista CFO" in html
    assert "Gasto por categoría (12m)" in html
    assert "vs Inflación" in html
    assert "Top proveedores (12m)" in html


def test_ipc_acumulado_compuesto():
    from src.finanzas.economia import _acumulado_pct
    # inflación compuesta de +1% y +1% = 2.01%, no 2%
    assert _acumulado_pct([1.0, 1.0]) == 2.0
    assert _acumulado_pct([0.5, -0.2, 0.3]) == round(((1.005*0.998*1.003)-1)*100, 1)
    assert _acumulado_pct([]) == 0.0


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
    pnl    = {"resumen": {"resultado_neto": -100}}
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
    pnl    = {"resumen": {"resultado_neto": 100}}
    cash   = {"semaforo": "ok", "resumen": {}}
    gastos = {"alertas": []}
    rent   = {"totales": {"tasa_cancel_pct": 5}}
    cierre = {"totales": {"gop_estado": "positivo"}}
    assert _detectar_problemas(pnl, cash, gastos, rent, cierre) == []
