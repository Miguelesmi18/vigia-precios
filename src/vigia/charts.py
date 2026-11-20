"""Gráfica semanal de precios (imagen PNG) para enviar con el resumen por Telegram.

Necesita matplotlib (pip install -e ".[charts]"). Si no está instalado, no se
genera gráfica y el resumen se envía solo con texto.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from vigia import db, stores

OUTLIER_RATIO = 1.6   # mismo criterio que el resumen: fuera packs y precios absurdos


def _points(conn, product_id: int, trusts: tuple[str, ...], since: str):
    rows = [r for r in db.best_price_per_check(conn, product_id, trusts)
            if r["checked_at"] >= since]
    if not rows:
        return [], []
    typical = median(r["price_cents"] for r in rows)
    rows = [r for r in rows if r["price_cents"] <= typical * OUTLIER_RATIO]
    dates = [datetime.fromisoformat(r["checked_at"]).astimezone() for r in rows]
    prices = [r["price_cents"] / 100 for r in rows]
    return dates, prices


def make_chart(conn, path: Path, days: int = 7, now: datetime | None = None) -> Path | None:
    """Dibuja una gráfica por producto. Devuelve la ruta del PNG, o None si no se pudo."""
    try:
        import matplotlib
        matplotlib.use("Agg")                    # sin pantalla: dibuja directo a archivo
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat(timespec="seconds")
    products = db.list_products(conn)
    if not products:
        return None

    start_local = (now - timedelta(days=days)).astimezone()
    end_local = now.astimezone()
    fig, axes = plt.subplots(len(products), 1, figsize=(8, 2.4 * len(products)),
                             squeeze=False, sharex=True)
    for ax, p in zip(axes[:, 0], products):
        if p["kind"] == "game":
            groups = [("Steam", ("official",), "-"), ("Claves", ("keyshop",), "--")]
        else:
            groups = [("Tiendas de confianza", (stores.OFFICIAL, stores.RETAILER), "-"),
                      ("Otras tiendas", (stores.MARKETPLACE, stores.UNKNOWN), "--")]
        plotted = False
        for label, trusts, style in groups:
            dates, prices = _points(conn, p["id"], trusts, since)
            if dates:
                # Escalones: cada precio dura hasta el siguiente cambio (o hasta hoy)
                ax.step(dates + [end_local], prices + [prices[-1]], style, where="post",
                        label=label)
                ax.plot(dates, prices, "o", markersize=4,
                        color=ax.lines[-1].get_color())
                plotted = True
        ax.axhline(p["target_cents"] / 100, color="tab:red", linewidth=1,
                   linestyle=":", label="Tu objetivo")
        ax.set_title(p["name"], fontsize=11, loc="left")
        ax.set_ylabel("€")
        ax.grid(alpha=0.3)
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
        if not plotted:
            ax.text(0.5, 0.5, "Sin datos esta semana", transform=ax.transAxes,
                    ha="center", va="center", color="gray")
        ax.set_xlim(start_local, end_local)
        ax.margins(y=0.25)
        ax.legend(fontsize=8, loc="best", framealpha=0.85)

    fig.suptitle("Precios de la semana", fontsize=13, fontweight="bold")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path
