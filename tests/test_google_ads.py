"""Tests del parseo de Google Ads (puros, sin red ni DB)."""

from datetime import date

from src.integraciones import google_ads


def test_parse_campana_convierte_micros_y_fechas():
    raw = {
        "id": "gads-1001",
        "name": "Búsqueda — Marca",
        "channel_type": "SEARCH",
        "status": "ENABLED",
        "budget_micros": "12000000000",   # micros → 12000.0
        "start_date": "2026-03-01",
        "end_date": None,
    }
    c = google_ads._parse_campana(raw)
    assert c["id_externo"] == "gads-1001"
    assert c["objetivo"] == "SEARCH"
    assert c["presupuesto_diario"] == 12000.0
    assert c["fecha_inicio"] == date(2026, 3, 1)
    assert c["fecha_fin"] is None


def test_parse_insight_normaliza_costo_micros_y_metricas_meta_en_cero():
    raw = {
        "campaign_id": "gads-1001",
        "date": "2026-04-10",
        "cost_micros": "45000000000",     # micros → 45000.0
        "impressions": "12000",
        "clicks": "320",
        "conversions": "15.0",
        "currency": "CLP",
    }
    ins = google_ads._parse_insight(raw)
    assert ins["campana_externa"] == "gads-1001"
    assert ins["fecha"] == date(2026, 4, 10)
    assert ins["gasto"] == 45000.0
    assert ins["impresiones"] == 12000
    assert ins["clics"] == 320
    assert ins["conversiones"] == 15.0
    # Métricas propias de Meta no aplican a Google → 0.
    assert ins["mensajes"] == 0 and ins["interacciones"] == 0
    assert ins["reproducciones"] == 0 and ins["visitas_perfil"] == 0


def test_mock_insights_determinista_y_solo_enabled():
    camp = google_ads._mock_campanas()
    desde, hasta = date(2026, 4, 1), date(2026, 4, 7)
    filas = google_ads._mock_insights(desde, hasta, camp)
    assert filas, "el mock debe generar filas"
    enabled = {c["id"] for c in camp if c["status"] == "ENABLED"}
    for f in filas:
        assert desde.isoformat() <= f["date"] <= hasta.isoformat()
        assert f["campaign_id"] in enabled          # las pausadas no generan métricas
        assert int(f["impressions"]) > 0
    # determinista: misma semilla → mismo resultado
    assert filas == google_ads._mock_insights(desde, hasta, camp)
