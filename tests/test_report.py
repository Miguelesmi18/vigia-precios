"""Tests del resumen semanal con un historial inventado."""

from datetime import date, datetime, timezone

from vigia import db
from vigia.report import black_friday, build_report, countdown, sparkline, trend_text

NOW = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)


def test_small_pieces():
    assert trend_text(2450, 2450) == "sin cambios"
    assert trend_text(2450, 1999) == "↓ 4,51 €"
    assert sparkline([100, 100, 100]) == "▄▄▄"
    assert sparkline([100, 200]) == "▁█"
    assert len(sparkline(list(range(30)))) == 8          # como mucho 8 puntos
    assert black_friday(2026) == date(2026, 11, 27)
    assert countdown(date(2026, 11, 20)) == "🖤 Black Friday en 7 días"
    assert countdown(date(2026, 12, 1)) == "🎄 Navidad en 24 días"


def make_db():
    conn = db.connect(":memory:")
    p4 = db.add_product(conn, "Persona 4 Revival", 4000, itad_id="id-1", steam_appid=1)
    caf = db.add_physical(conn, "Cafetera", 28000, query="cafetera")
    razer = db.add_physical(conn, "Razer", 8500, query="razer")
    for day, steam, keys in [(14, 6999, 4064), (19, 6999, 4064)]:
        ts = f"2026-11-{day}T09:00:00+00:00"
        db.save_price(conn, p4, "Steam", steam, steam, "EUR", None, checked_at=ts)
        db.save_price(conn, p4, "Claves", keys, None, "EUR", "https://gg.deals/game/persona-4-revival/",
                      checked_at=ts, trust="keyshop")
    for day, price in [(14, 27990), (19, 29990)]:
        db.save_price(conn, caf, "delonghi.es", price, None, "EUR", None,
                      checked_at=f"2026-11-{day}T09:00:00+00:00", trust="official")
    ts = "2026-11-19T09:00:00+00:00"
    db.save_price(conn, razer, "Razer.com", 8999, None, "EUR", None, checked_at=ts,
                  trust="official")
    db.save_price(conn, razer, "Play-Asia.com", 7735, None, "EUR", None, checked_at=ts,
                  trust="unknown")
    return conn


def test_report_layout_and_order():
    text = build_report(make_db(), now=NOW, include_server=False)
    assert "🖤 Black Friday en 7 días" in text
    # Orden por cercanía al objetivo: Persona (40,64/40) antes que Razer y Cafetera
    assert text.index("Persona 4 Revival") < text.index("Razer") < text.index("Cafetera")
    assert "🟡 Persona 4 Revival — objetivo 40,00 €" in text
    assert "🔑 Claves: 40,64 € · faltan 0,64 €" in text
    assert "🔗 Ver en qué tienda está: https://gg.deals/game/persona-4-revival/" in text
    assert "🟡 Razer" in text                     # 89,99 sobre 85: menos del 10 %
    assert "🟡 Cafetera" in text                  # 299,90 sobre 280: un 7 % por encima
    assert "🏬 delonghi.es: 299,90 € · faltan 19,90 €" in text
    assert "(mínimo de la semana: 279,90 €)" in text
    assert "⏳ Mejor esperar: ha subido esta semana" in text
    assert "🔎 Play-Asia.com: 77,35 €" in text and "extranjera" in text
    assert "⏳ Espera al Black Friday" in text


def test_report_budget_and_serpapi(monkeypatch):
    monkeypatch.setenv("CHRISTMAS_BUDGET", "400")
    conn = make_db()
    db.log_api_call(conn, "serpapi")
    text = build_report(conn, now=datetime.now(timezone.utc), include_server=False)
    # Todo hoy: 40,64 (claves) + 299,90 + 89,99 = 430,53
    assert "🎁 Comprarlo todo hoy: 430,53 € · a tus precios: 405,00 €" in text
    assert "Presupuesto 400,00 €: te pasas 30,53 €" in text
    assert "🔍 SerpApi: 1/250 búsquedas este mes" in text


def test_product_at_target_says_buy():
    conn = db.connect(":memory:")
    pid = db.add_physical(conn, "Mando", 6000, query="mando")
    db.save_price(conn, pid, "PcComponentes", 5499, None, "EUR", None,
                  checked_at="2026-11-19T09:00:00+00:00", trust="retailer")
    text = build_report(conn, now=NOW, include_server=False)
    assert "✅ Mando" in text
    assert "✔ a tu precio" in text
    assert "👉 Buen momento: está a tu precio" in text


def test_report_without_data():
    conn = db.connect(":memory:")
    db.add_physical(conn, "Auriculares", 8500, query="auriculares")
    assert "Sin datos esta semana" in build_report(conn, now=NOW, include_server=False)


def test_report_nothing_watched():
    assert "no vigilas nada" in build_report(db.connect(":memory:"), now=NOW)


def test_outlier_and_old_other_shop():
    conn = db.connect(":memory:")
    pid = db.add_physical(conn, "Cafetera", 28000, query="cafetera")
    # Un día solo aparece un Fnac absurdo a 1.499 €: debe ignorarse
    for day, shop, price in [(14, "delonghi.es", 27990), (16, "Fnac", 149900),
                             (19, "delonghi.es", 29990)]:
        db.save_price(conn, pid, shop, price, None, "EUR", None,
                      checked_at=f"2026-11-{day}T09:00:00+00:00", trust="official")
    # Una tienda desconocida más barata, pero vista el día 16 (no en la última comprobación)
    db.save_price(conn, pid, "makro-falso.es", 25000, None, "EUR", None,
                  checked_at="2026-11-16T09:00:00+00:00", trust="unknown")
    text = build_report(conn, now=NOW, include_server=False)
    assert "1499" not in text and "1.499" not in text
    assert "▁█" in text                       # gráfica sin el pico absurdo
    assert "🔎 makro-falso.es: 250,00 € (fuera de tu lista de confianza, visto el 16/11)" in text


def test_physical_products_include_offer_link():
    conn = db.connect(":memory:")
    pid = db.add_physical(conn, "Mando", 4500, query="mando")
    db.save_price(conn, pid, "PcComponentes", 5499, None, "EUR",
                  "https://www.google.com/shopping/product/123",
                  checked_at="2026-11-19T09:00:00+00:00", trust="retailer")
    text = build_report(conn, now=NOW, include_server=False)
    assert "🏬 PcComponentes: 54,99 €" in text
    assert "🔗 Ver la oferta: https://www.google.com/shopping/product/123" in text


def test_battery_status(tmp_path):
    from vigia.report import battery_status
    bat = tmp_path / "BAT0"
    bat.mkdir()
    (bat / "capacity").write_text("100\n")
    (bat / "status").write_text("Full\n")
    assert battery_status(tmp_path) == "🔌 100 % enchufado"
    (bat / "capacity").write_text("25\n")
    (bat / "status").write_text("Discharging\n")
    assert battery_status(tmp_path) == "🪫 25 % sin cargador"
    assert battery_status(tmp_path / "nada") is None
