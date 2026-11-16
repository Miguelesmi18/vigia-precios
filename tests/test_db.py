from vigia import db


def test_add_and_list_products():
    conn = db.connect(":memory:")       # base de datos temporal, en memoria
    pid = db.add_product(conn, "Hades", 1500, itad_id="abc")
    products = db.list_products(conn)
    assert len(products) == 1
    assert products[0]["id"] == pid
    assert products[0]["target_cents"] == 1500


def test_save_price_and_history():
    conn = db.connect(":memory:")
    pid = db.add_product(conn, "Hades", 1500, itad_id="abc")
    db.save_price(conn, pid, "Steam", 2499, 2499, "EUR", None,
                  checked_at="2026-11-01T10:00:00+00:00")
    db.save_price(conn, pid, "Steam", 1249, 2499, "EUR", None,
                  checked_at="2026-11-10T10:00:00+00:00")
    history = db.price_history(conn, pid)
    assert [h["price_cents"] for h in history] == [2499, 1249]


def test_remove_product_also_removes_prices():
    conn = db.connect(":memory:")
    pid = db.add_product(conn, "Hades", 1500, itad_id="abc")
    db.save_price(conn, pid, "Steam", 2499, 2499, "EUR", None)
    assert db.remove_product(conn, pid) is True
    assert db.price_history(conn, pid) == []
