"""Tests del resumen semanal con un historial inventado."""

from datetime import datetime, timezone

from vigia import db
from vigia.report import build_report, trend

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)


def test_trend_text():
    assert trend(2450, 2450) == "sin cambios"
    assert trend(2450, 1999) == "↓ 4,51 € en la semana"
    assert trend(1999, 2450) == "↑ 4,51 € en la semana"


def test_report_games_and_physical():
    conn = db.connect(":memory:")
    hades = db.add_product(conn, "Hades", 1500, itad_id="id-1", steam_appid=1145360)
    caf = db.add_physical(conn, "Cafetera", 28000, query="cafetera")

    # Hades: Steam fijo; claves bajan de 15,80 a 10,08
    db.save_price(conn, hades, "Steam", 2450, 2450, "EUR", None,
                  checked_at="2026-11-17T09:00:00+00:00")
    db.save_price(conn, hades, "Steam", 2450, 2450, "EUR", None,
                  checked_at="2026-11-22T09:00:00+00:00")
    db.save_price(conn, hades, "Claves", 1580, None, "EUR", None,
                  checked_at="2026-11-17T09:00:00+00:00", trust="keyshop")
    db.save_price(conn, hades, "Claves", 1008, None, "EUR", None,
                  checked_at="2026-11-22T09:00:00+00:00", trust="keyshop")
    # Cafetera: MediaMarkt baja de 299,90 a 279,90 (por debajo del objetivo)
    db.save_price(conn, caf, "MediaMarkt", 29990, None, "EUR", None,
                  checked_at="2026-11-18T09:00:00+00:00", trust="retailer")
    db.save_price(conn, caf, "MediaMarkt", 27990, None, "EUR", None,
                  checked_at="2026-11-22T09:00:00+00:00", trust="retailer")
    # Un precio de hace un mes no debe contar
    db.save_price(conn, caf, "MediaMarkt", 19990, None, "EUR", None,
                  checked_at="2026-10-20T09:00:00+00:00", trust="retailer")

    text = build_report(conn, days=7, now=NOW)
    assert "🎮 Hades — objetivo 15,00 €" in text
    assert "Steam: 24,50 € (sin cambios)" in text
    assert "Claves: 10,08 € (↓ 5,72 € en la semana) · mínimo de la semana 10,08 €" in text
    assert "Tiendas de confianza: 279,90 € (↓ 20,00 € en la semana)" in text
    assert "199,90" not in text                       # fuera de la semana
    assert "✅ Ahora mismo está por debajo de tu objetivo" in text


def test_report_without_data():
    conn = db.connect(":memory:")
    db.add_physical(conn, "Auriculares", 8500, query="auriculares")
    assert "Sin datos esta semana" in build_report(conn, now=NOW)


def test_report_nothing_watched():
    assert "no vigilas nada" in build_report(db.connect(":memory:"), now=NOW)
