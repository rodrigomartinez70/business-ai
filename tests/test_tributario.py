"""
Tests del Copiloto Tributario (agentes IVA, Cumplimiento y Riesgo).
"""

import pytest
from datetime import date


FECHA = date(2026, 3, 31)


@pytest.mark.asyncio
async def test_tributario_estructura_json(client, gerente_headers):
    resp = await client.get(f"/api/agents/tributario?fecha={FECHA}", headers=gerente_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "periodo" in data
    assert "agente_iva" in data
    assert "agente_cumplimiento" in data
    assert "agente_riesgo" in data


@pytest.mark.asyncio
async def test_tributario_agente_iva(client, gerente_headers):
    iva = (await client.get(
        f"/api/agents/tributario?fecha={FECHA}", headers=gerente_headers
    )).json()["agente_iva"]
    assert "acumulado_mes" in iva
    assert "f29" in iva
    acum = iva["acumulado_mes"]
    # saldo = débito - crédito
    assert acum["saldo_iva"] == pytest.approx(
        acum["iva_debito_acum"] - acum["iva_credito_acum"], abs=1.0
    )
    assert iva["acumulado_mes"]["estado"] in ("deuda", "saldo_a_favor")
    # F29 monto a pagar nunca negativo
    assert iva["f29"]["monto_estimado"] >= 0


@pytest.mark.asyncio
async def test_tributario_f29_vence_dia_20_mes_siguiente(client, gerente_headers):
    f29 = (await client.get(
        f"/api/agents/tributario?fecha={FECHA}", headers=gerente_headers
    )).json()["agente_iva"]["f29"]
    # corte 2026-03-31 -> vence 2026-04-20
    assert f29["vencimiento"] == "2026-04-20"
    assert f29["dias_para_vencimiento"] == 20


@pytest.mark.asyncio
async def test_tributario_cumplimiento_vencimientos(client, gerente_headers):
    cum = (await client.get(
        f"/api/agents/tributario?fecha={FECHA}", headers=gerente_headers
    )).json()["agente_cumplimiento"]
    assert "proximos_vencimientos" in cum
    assert "calendario_anual" in cum
    for v in cum["proximos_vencimientos"]:
        assert "codigo" in v and "fecha" in v and "dias_restantes" in v
        assert v["dias_restantes"] >= 0
    # corte 31-mar con horizonte 60d incluye el F29 de abril (día 20)
    assert any(v["codigo"] == "F29" for v in cum["proximos_vencimientos"])


@pytest.mark.asyncio
async def test_tributario_agente_riesgo(client, gerente_headers):
    rie = (await client.get(
        f"/api/agents/tributario?fecha={FECHA}", headers=gerente_headers
    )).json()["agente_riesgo"]
    assert rie["score_riesgo"] in ("bajo", "medio", "alto")
    assert isinstance(rie["inconsistencias"], list)
    assert isinstance(rie["alertas"], list)
    assert "documentos_pendientes" in rie
    for a in rie["alertas"]:
        assert a["nivel"] in ("critico", "alerta", "info")


@pytest.mark.asyncio
async def test_tributario_formato_markdown(client, gerente_headers):
    resp = await client.get(
        f"/api/agents/tributario?fecha={FECHA}&formato=markdown", headers=gerente_headers
    )
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert "Copiloto Tributario" in resp.text
    assert "Agente IVA" in resp.text


@pytest.mark.asyncio
async def test_tributario_defaults_a_hoy(client, gerente_headers):
    resp = await client.get("/api/agents/tributario", headers=gerente_headers)
    assert resp.status_code == 200
    assert "agente_iva" in resp.json()


@pytest.mark.asyncio
async def test_tributario_uf_referencia(client, gerente_headers):
    """Sin credenciales del Banco Central (CI), usa la UF de respaldo."""
    iva = (await client.get(
        f"/api/agents/tributario?fecha={FECHA}", headers=gerente_headers
    )).json()["agente_iva"]
    assert iva["uf_referencia"] > 0
    # saldo_iva_uf coherente con el saldo y la UF de referencia
    saldo = iva["acumulado_mes"]["saldo_iva"]
    esperado = round(saldo / iva["uf_referencia"], 2)
    assert iva["acumulado_mes"]["saldo_iva_uf"] == pytest.approx(esperado, abs=0.1)


@pytest.mark.asyncio
async def test_tributario_requiere_auth(client):
    resp = await client.get("/api/agents/tributario")
    assert resp.status_code == 403


# ── Agente Conversacional (Open WebUI) ──────────────────────────────────

@pytest.mark.asyncio
async def test_conversacional_modelo_listado(client, gerente_headers):
    data = (await client.get("/api/v1/models", headers=gerente_headers)).json()
    assert "copiloto-tributario" in [m["id"] for m in data["data"]]


@pytest.mark.asyncio
async def test_conversacional_responde(client, gerente_headers):
    """Sin LLM en CI, responde con el contexto tributario como fallback."""
    resp = await client.post(
        "/api/v1/chat/completions",
        headers=gerente_headers,
        json={
            "model": "copiloto-tributario",
            "messages": [{"role": "user", "content": "¿Cuánto debo pagar de IVA este mes?"}],
            "stream": False,
        },
    )
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    assert isinstance(content, str) and len(content) > 0
