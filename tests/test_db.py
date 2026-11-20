import sqlite3

from vigia import db


def test_add_and_list_products():
    conn = db.connect(":memory:")       # base de datos temporal, en memoria
    pid = db.add_product(conn, "Hades", 1500, itad_id="abc", steam_appid=1145360)
    products = db.list_products(conn)
    assert len(products) == 1
    assert products[0]["id"] == pid
    assert products[0]["target_cents"] == 1500
    assert products[0]["steam_appid"] == 1145360


def test_save_price_and_history_with_trust():
    conn = db.connect(":memory:")
    pid = db.add_product(conn, "Hades", 1500, itad_id="abc")
    db.save_price(conn, pid, "Steam", 2499, 2499, "EUR", None,
                  checked_at="2026-11-01T10:00:00+00:00")
    db.save_price(conn, pid, "Tiendas de claves", 1199, None, "EUR", None,
                  checked_at="2026-11-10T10:00:00+00:00", trust="keyshop")
    history = db.price_history(conn, pid)
    assert [h["price_cents"] for h in history] == [2499, 1199]
    assert [h["trust"] for h in history] == ["official", "keyshop"]


def test_remove_product_also_removes_prices():
    conn = db.connect(":memory:")
    pid = db.add_product(conn, "Hades", 1500, itad_id="abc")
    db.save_price(conn, pid, "Steam", 2499, 2499, "EUR", None)
    assert db.remove_product(conn, pid) is True
    assert db.price_history(conn, pid) == []


def test_old_database_is_migrated(tmp_path):
    """Una base de datos de la versión 0.1 (sin steam_appid ni trust) se actualiza sola."""
    path = tmp_path / "vieja.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'game', itad_id TEXT, target_cents INTEGER NOT NULL,
            created_at TEXT NOT NULL, UNIQUE (kind, itad_id));
        CREATE TABLE prices (id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
            shop TEXT NOT NULL, price_cents INTEGER NOT NULL, regular_cents INTEGER,
            currency TEXT NOT NULL, url TEXT, checked_at TEXT NOT NULL);
        INSERT INTO products (name, itad_id, target_cents, created_at)
            VALUES ('Hades', 'abc', 1500, '2026-11-15');
        INSERT INTO prices (product_id, shop, price_cents, currency, checked_at)
            VALUES (1, 'Epic Game Store', 2450, 'EUR', '2026-11-16');
    """)
    old.commit()
    old.close()

    conn = db.connect(path)
    product = db.list_products(conn)[0]
    assert product["name"] == "Hades"            # no se ha perdido nada
    assert product["steam_appid"] is None        # columna nueva, vacía
    assert db.price_history(conn, 1)[0]["trust"] == "official"


def test_alerts_save_update_clear():
    conn = db.connect(":memory:")
    pid = db.add_product(conn, "Hades", 1500, itad_id="abc")
    assert db.last_alert_price(conn, pid, "steam") is None
    db.save_alert(conn, pid, "steam", 1249)
    db.save_alert(conn, pid, "steam", 999)              # se actualiza, no se duplica
    assert db.last_alert_price(conn, pid, "steam") == 999
    db.clear_alert(conn, pid, "steam")
    assert db.last_alert_price(conn, pid, "steam") is None
