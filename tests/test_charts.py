"""Test de la gráfica semanal (se salta si matplotlib no está instalado)."""

import pytest

from vigia import charts, db

pytest.importorskip("matplotlib")


def test_make_chart_creates_png(tmp_path):
    conn = db.connect(":memory:")
    pid = db.add_physical(conn, "Cafetera", 28000, query="cafetera")
    db.add_product(conn, "Juego sin datos", 4000, itad_id="x")
    for day, price in [(16, 27990), (18, 149900), (19, 29990)]:      # 1.499 € se descarta
        db.save_price(conn, pid, "delonghi.es", price, None, "EUR", None,
                      checked_at=f"2026-11-{day}T09:00:00+00:00", trust="official")
    from datetime import datetime, timezone
    path = charts.make_chart(conn, tmp_path / "resumen.png",
                             now=datetime(2026, 11, 20, 9, tzinfo=timezone.utc))
    assert path.exists()
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"    # es un PNG de verdad


def test_no_products_no_chart(tmp_path):
    assert charts.make_chart(db.connect(":memory:"), tmp_path / "x.png") is None
