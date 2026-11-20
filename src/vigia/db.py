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
    query         TEXT,                              -- texto de búsqueda (productos físicos)
    model         TEXT,                              -- código de modelo obligatorio en el título
    target_cents  INTEGER NOT NULL,                  -- precio objetivo en céntimos
    created_at    TEXT    NOT NULL,
    UNIQUE (kind, itad_id)
);

CREATE TABLE IF NOT EXISTS prices (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id     INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    shop           TEXT    NOT NULL,
    trust          TEXT    NOT NULL DEFAULT 'official', -- 'official' o 'keyshop'
    price_cents    INTEGER NOT NULL,                  -- precio FINAL (con envío si se conoce)
    shipping_cents INTEGER,
    regular_cents  INTEGER,
    currency       TEXT    NOT NULL,
    url            TEXT,
    checked_at     TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prices_product_date
    ON prices (product_id, checked_at);

-- Llamadas a APIs con límite (para contar las búsquedas de SerpApi del mes)
CREATE TABLE IF NOT EXISTS api_calls (
    service    TEXT NOT NULL,
    called_at  TEXT NOT NULL
);

-- Avisos ya enviados, para no repetirlos (uno por producto y tipo de aviso)
CREATE TABLE IF NOT EXISTS alerts (
    product_id   INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    kind         TEXT    NOT NULL,     -- 'steam', 'keyshop', 'trusted', 'other'
    price_cents  INTEGER NOT NULL,     -- precio del último aviso enviado
    sent_at      TEXT    NOT NULL,
    PRIMARY KEY (product_id, kind)
);
"""

# Columnas añadidas después de la versión 0.1.0. Si tu base de datos es
# antigua, connect() las añade sin borrar nada (esto es una "migración").
MIGRATIONS = [
    ("products", "steam_appid", "INTEGER"),
    ("prices", "trust", "TEXT NOT NULL DEFAULT 'official'"),
    ("products", "query", "TEXT"),
    ("products", "model", "TEXT"),
    ("prices", "shipping_cents", "INTEGER"),
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
               checked_at: str | None = None, trust: str = "official",
               shipping_cents: int | None = None) -> None:
    """Guarda un precio en el historial."""
    conn.execute(
        "INSERT INTO prices (product_id, shop, trust, price_cents, regular_cents, "
        "currency, url, checked_at, shipping_cents) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (product_id, shop, trust, price_cents, regular_cents, currency, url,
         checked_at or now_iso(), shipping_cents),
    )
    conn.commit()


def price_history(conn, product_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM prices WHERE product_id = ? ORDER BY checked_at",
        (product_id,),
    ).fetchall()


def add_physical(conn, name: str, target_cents: int, query: str,
                 model: str | None = None) -> int:
    """Añade un producto físico (cafetera, auriculares...) a vigilar."""
    cur = conn.execute(
        "INSERT INTO products (name, kind, query, model, target_cents, created_at) "
        "VALUES (?, 'physical', ?, ?, ?, ?)",
        (name, query, model, target_cents, now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def last_checked(conn, product_id: int) -> str | None:
    row = conn.execute("SELECT MAX(checked_at) AS last FROM prices WHERE product_id = ?",
                       (product_id,)).fetchone()
    return row["last"]


def best_price_per_check(conn, product_id: int, trusts: tuple[str, ...]) -> list[sqlite3.Row]:
    """El precio más bajo de cada comprobación, solo de las tiendas indicadas."""
    marks = ",".join("?" for _ in trusts)
    return conn.execute(
        f"SELECT checked_at, MIN(price_cents) AS price_cents FROM prices "
        f"WHERE product_id = ? AND trust IN ({marks}) "
        f"GROUP BY checked_at ORDER BY checked_at",
        (product_id, *trusts),
    ).fetchall()


# ---------------------------------------------------------------- avisos enviados

def last_alert_price(conn, product_id: int, kind: str) -> int | None:
    row = conn.execute("SELECT price_cents FROM alerts WHERE product_id = ? AND kind = ?",
                       (product_id, kind)).fetchone()
    return row["price_cents"] if row else None


def save_alert(conn, product_id: int, kind: str, price_cents: int) -> None:
    conn.execute(
        "INSERT INTO alerts (product_id, kind, price_cents, sent_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (product_id, kind) DO UPDATE SET price_cents = excluded.price_cents, "
        "sent_at = excluded.sent_at",
        (product_id, kind, price_cents, now_iso()),
    )
    conn.commit()


def clear_alert(conn, product_id: int, kind: str) -> None:
    """El precio volvió a subir del objetivo: la próxima bajada será un aviso nuevo."""
    conn.execute("DELETE FROM alerts WHERE product_id = ? AND kind = ?", (product_id, kind))
    conn.commit()


# ---------------------------------------------------------------- uso de APIs

def log_api_call(conn, service: str) -> None:
    conn.execute("INSERT INTO api_calls (service, called_at) VALUES (?, ?)",
                 (service, now_iso()))
    conn.commit()


def count_api_calls(conn, service: str, since_iso: str) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM api_calls WHERE service = ? AND called_at >= ?",
                       (service, since_iso)).fetchone()
    return row["n"]


def latest_prices(conn, product_id: int) -> list[sqlite3.Row]:
    """Los precios de la última comprobación de un producto (uno por tienda)."""
    return conn.execute(
        "SELECT * FROM prices WHERE product_id = ? AND checked_at = "
        "(SELECT MAX(checked_at) FROM prices WHERE product_id = ?) ORDER BY price_cents",
        (product_id, product_id),
    ).fetchall()
