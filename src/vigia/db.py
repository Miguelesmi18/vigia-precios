"""Base de datos SQLite: productos vigilados e historial de precios.

Los precios se guardan en CÉNTIMOS (enteros) para evitar errores de redondeo
de los decimales: 19.99 € se guarda como 1999.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    kind          TEXT    NOT NULL DEFAULT 'game',   -- 'game' o 'physical'
    itad_id       TEXT,                              -- id del juego en IsThereAnyDeal
    steam_appid   INTEGER,                           -- id del juego en Steam
    target_cents  INTEGER NOT NULL,                  -- precio objetivo en céntimos
    created_at    TEXT    NOT NULL,
    UNIQUE (kind, itad_id)
);

CREATE TABLE IF NOT EXISTS prices (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id     INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    shop           TEXT    NOT NULL,
    trust          TEXT    NOT NULL DEFAULT 'official', -- 'official' o 'keyshop'
    price_cents    INTEGER NOT NULL,
    regular_cents  INTEGER,
    currency       TEXT    NOT NULL,
    url            TEXT,
    checked_at     TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prices_product_date
    ON prices (product_id, checked_at);
"""

# Columnas añadidas después de la versión 0.1.0. Si tu base de datos es
# antigua, connect() las añade sin borrar nada (esto es una "migración").
MIGRATIONS = [
    ("products", "steam_appid", "INTEGER"),
    ("prices", "trust", "TEXT NOT NULL DEFAULT 'official'"),
]


def now_iso() -> str:
    """Fecha y hora actual en UTC, en formato ISO (ej. 2026-11-15T11:00:00+00:00)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, definition in MIGRATIONS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.commit()


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Abre la base de datos (la crea si no existe) y prepara las tablas."""
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row          # permite leer columnas por nombre
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def add_product(conn, name: str, target_cents: int, itad_id: str | None = None,
                steam_appid: int | None = None, kind: str = "game") -> int:
    """Añade un producto a vigilar. Devuelve su id."""
    cur = conn.execute(
        "INSERT INTO products (name, kind, itad_id, steam_appid, target_cents, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, kind, itad_id, steam_appid, target_cents, now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def set_steam_appid(conn, product_id: int, appid: int) -> None:
    conn.execute("UPDATE products SET steam_appid = ? WHERE id = ?", (appid, product_id))
    conn.commit()


def list_products(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM products ORDER BY id").fetchall()


def remove_product(conn, product_id: int) -> bool:
    cur = conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    return cur.rowcount > 0


def save_price(conn, product_id: int, shop: str, price_cents: int,
               regular_cents: int | None, currency: str, url: str | None,
               checked_at: str | None = None, trust: str = "official") -> None:
    """Guarda un precio en el historial."""
    conn.execute(
        "INSERT INTO prices (product_id, shop, trust, price_cents, regular_cents, "
        "currency, url, checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (product_id, shop, trust, price_cents, regular_cents, currency, url,
         checked_at or now_iso()),
    )
    conn.commit()


def price_history(conn, product_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM prices WHERE product_id = ? ORDER BY checked_at",
        (product_id,),
    ).fetchall()
