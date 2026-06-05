"""Tests del parseo de Meta Ads (puros, sin red ni DB)."""

from datetime import date

from src.integraciones import meta_ads


def test_parse_campana_convierte_presupuesto_y_fechas():
    raw = {
        "id": "23851000000000001",
        "name": "Proyecto Mirador — Leads",
        "objective": "OUTCOME_LEADS",
        "status": "ACTIVE",
        "daily_budget": "5000000",  # unidad menor (centavos) → 50000.0
        "start_time": "2026-03-01T00:00:00-0300",
        "stop_time": None,
    }
    c = meta_ads._parse_campana(raw)
    assert c["id_externo"] == "23851000000000001"
    assert c["objetivo"] == "OUTCOME_LEADS"
    assert c["presupuesto_diario"] == 50000.0
    assert c["fecha_inicio"] == date(2026, 3, 1)
    assert c["fecha_fin"] is None


def test_parse_insight_extrae_metricas_y_conversiones():
    raw = {
        "campaign_id": "23851000000000001",
        "date_start": "2026-04-10",
        "spend": "45000.5",
        "impressions": "12000",
        "clicks": "320",
        "reach": "9000",
        "actions": [
            {"action_type": "link_click", "value": "300"},
            {"action_type": "lead", "value": "12"},
        ],
        "account_currency": "CLP",
    }
    ins = meta_ads._parse_insight(raw)
    assert ins["campana_externa"] == "23851000000000001"
    assert ins["fecha"] == date(2026, 4, 10)
    assert ins["gasto"] == 45000.5
    assert ins["impresiones"] == 12000
    assert ins["clics"] == 320
    assert ins["conversiones"] == 12.0  # solo cuenta el action_type 'lead'


def test_conversiones_suma_solo_tipos_de_lead():
    actions = [
        {"action_type": "lead", "value": "3"},
        {"action_type": "offsite_conversion.fb_pixel_lead", "value": "2"},
        {"action_type": "post_engagement", "value": "999"},
    ]
    assert meta_ads._conversiones_de_actions(actions) == 5.0
    assert meta_ads._conversiones_de_actions(None) == 0.0


def test_mock_insights_respeta_rango_y_valores_validos():
    camp = meta_ads._mock_campanas()
    desde, hasta = date(2026, 4, 1), date(2026, 4, 7)
    filas = meta_ads._mock_insights(desde, hasta, camp)
    assert filas, "el mock debe generar filas"
    for f in filas:
        assert desde.isoformat() <= f["date_start"] <= hasta.isoformat()
        assert int(f["impressions"]) > 0
        assert int(f["clicks"]) >= 0
    # determinista: misma semilla → mismo resultado
    assert filas == meta_ads._mock_insights(desde, hasta, camp)
