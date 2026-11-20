"""Resumen semanal: cómo ha ido el precio de cada producto en los últimos días."""

from datetime import datetime, timedelta, timezone

from vigia import db

# Grupos de precios que se resumen por separado
GAME_GROUPS = [("Steam", ("official",)), ("Claves", ("keyshop",))]
PHYSICAL_GROUPS = [("Tiendas de confianza", ("official", "retailer")),
                   ("Otras tiendas", ("marketplace", "unknown"))]


def euros(cents: int) -> str:
    return f"{cents / 100:.2f} €".replace(".", ",")


def trend(first: int, last: int) -> str:
    """Texto de la variación entre el primer y el último precio del periodo."""
    diff = last - first
    if diff == 0:
        return "sin cambios"
    arrow = "↓" if diff < 0 else "↑"
    return f"{arrow} {euros(abs(diff))} en la semana"


def group_summary(conn, product_id: int, trusts: tuple[str, ...], since: str):
    """(último, mínimo, primero) del mejor precio de cada comprobación, o None."""
    rows = [r for r in db.best_price_per_check(conn, product_id, trusts)
            if r["checked_at"] >= since]
    if not rows:
        return None
    prices = [r["price_cents"] for r in rows]
    return prices[-1], min(prices), prices[0]


def build_report(conn, days: int = 7, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    since_dt = now - timedelta(days=days)
    since = since_dt.isoformat(timespec="seconds")
    products = db.list_products(conn)
    if not products:
        return "📊 Resumen semanal: no vigilas nada todavía."

    lines = [f"📊 Resumen de los últimos {days} días "
             f"({since_dt:%d/%m} – {now:%d/%m})", ""]
    for p in products:
        icon = "🎮" if p["kind"] == "game" else "📦"
        lines.append(f"{icon} {p['name']} — objetivo {euros(p['target_cents'])}")
        groups = GAME_GROUPS if p["kind"] == "game" else PHYSICAL_GROUPS
        any_data = False
        below = False
        for label, trusts in groups:
            summary = group_summary(conn, p["id"], trusts, since)
            if not summary:
                continue
            any_data = True
            last, lowest, first = summary
            lines.append(f"   {label}: {euros(last)} ({trend(first, last)}) · "
                         f"mínimo de la semana {euros(lowest)}")
            # Solo cuenta como "por debajo" un precio oficial o de tienda de confianza
            if label in ("Steam", "Tiendas de confianza") and last <= p["target_cents"]:
                below = True
        if not any_data:
            lines.append("   Sin datos esta semana")
        elif below:
            lines.append("   ✅ Ahora mismo está por debajo de tu objetivo")
        lines.append("")
    return "\n".join(lines).rstrip()
