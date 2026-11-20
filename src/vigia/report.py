"""Resumen semanal: cómo ha ido cada producto, lo cerca que está de tu precio
y un consejo orientativo de compra.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from vigia import config, db, stores

SPARK_CHARS = "▁▂▃▄▅▆▇█"
NEAR_TARGET = 0.10           # a menos de un 10 % del objetivo = 🟡
MAX_SPARK_POINTS = 8         # puntos de la minigráfica
OUTLIER_RATIO = 1.6          # precios > 1,6 x la mediana se descartan (otro producto, packs...)


def euros(cents: int) -> str:
    return f"{cents / 100:.2f} €".replace(".", ",")


# ---------------------------------------------------------------- piezas sueltas

def sparkline(values: list[int]) -> str:
    """[300, 280, 299] -> '█▁▇'. Si no hay variación, una línea plana."""
    if len(values) < 2:
        return ""
    if len(values) > MAX_SPARK_POINTS:            # nos quedamos con puntos repartidos
        step = (len(values) - 1) / (MAX_SPARK_POINTS - 1)
        values = [values[round(i * step)] for i in range(MAX_SPARK_POINTS)]
    low, high = min(values), max(values)
    if low == high:
        return SPARK_CHARS[3] * len(values)
    scale = len(SPARK_CHARS) - 1
    return "".join(SPARK_CHARS[round((v - low) / (high - low) * scale)] for v in values)


def trend_text(first: int, last: int) -> str:
    diff = last - first
    if diff == 0:
        return "sin cambios"
    return f"{'↓' if diff < 0 else '↑'} {euros(abs(diff))}"


def black_friday(year: int) -> date:
    """Último viernes de noviembre."""
    d = date(year, 11, 30)
    while d.weekday() != 4:          # 4 = viernes
        d -= timedelta(days=1)
    return d


def countdown(today: date) -> str | None:
    bf = black_friday(today.year)
    if today <= bf:
        days = (bf - today).days
        return "🖤 ¡Hoy es Black Friday!" if days == 0 else f"🖤 Black Friday en {days} días"
    xmas = date(today.year, 12, 25)
    if today <= xmas:
        days = (xmas - today).days
        return "🎄 ¡Feliz Navidad!" if days == 0 else f"🎄 Navidad en {days} días"
    return None


def server_status() -> str | None:
    """Temperatura y tiempo encendido (solo en Linux; en Windows no se muestra)."""
    parts = []
    temps = []
    for zone in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            temps.append(int(zone.read_text().strip()) // 1000)
        except (OSError, ValueError):
            pass
    if temps:
        parts.append(f"{max(temps)} °C")
    try:
        seconds = float(Path("/proc/uptime").read_text().split()[0])
        days = int(seconds // 86400)
        parts.append("encendido hoy" if days == 0 else
                     f"encendido {days} día{'s' if days != 1 else ''}")
    except (OSError, ValueError, IndexError):
        pass
    return "🖥️ Servidor: " + " · ".join(parts) if parts else None


# ---------------------------------------------------------------- un producto

@dataclass
class Series:
    """Precios de un grupo (Steam, claves, tiendas de confianza...) en la semana."""
    label: str
    icon: str
    shop: str
    prices: list[int]
    seen_on: str | None = None    # fecha del último precio si NO es de la última comprobación
    trust: str = ""               # confianza de la tienda del último precio

    @property
    def last(self) -> int:
        return self.prices[-1]

    @property
    def lowest(self) -> int:
        return min(self.prices)


@dataclass
class ProductSummary:
    name: str
    kind: str
    target: int
    main: list[Series] = field(default_factory=list)     # cuentan para el objetivo
    extra: Series | None = None                          # otras tiendas, solo si más baratas
    extra_trust: str = ""

    @property
    def best(self) -> Series | None:
        return min(self.main, key=lambda s: s.last) if self.main else None

    @property
    def ratio(self) -> float:
        """Precio actual / objetivo: 0,98 = un 2 % por debajo. Sin datos = infinito."""
        return self.best.last / self.target if self.best else float("inf")

    @property
    def light(self) -> str:
        if not self.best:
            return "⚪"
        if self.best.last <= self.target:
            return "✅"
        return "🟡" if self.ratio <= 1 + NEAR_TARGET else "🔴"


def _series(conn, product_id: int, trusts: tuple[str, ...], since: str,
            label: str, icon: str) -> Series | None:
    rows = [r for r in db.best_price_per_check(conn, product_id, trusts)
            if r["checked_at"] >= since]
    if not rows:
        return None
    # Fuera precios absurdos (un pack, otro modelo...) que deformarían la gráfica
    typical = median(r["price_cents"] for r in rows)
    rows = [r for r in rows if r["price_cents"] <= typical * OUTLIER_RATIO]
    last = rows[-1]
    # La tienda del último precio de ESTE grupo (puede no ser la última comprobación)
    shop_row = db.conn_price_at(conn, product_id, trusts, last["checked_at"],
                                last["price_cents"])
    shop = shop_row["shop"] if shop_row else label
    seen_on = None
    if last["checked_at"] != db.last_checked(conn, product_id):
        seen_on = datetime.fromisoformat(last["checked_at"]).astimezone().strftime("%d/%m")
    return Series(label, icon, shop, [r["price_cents"] for r in rows], seen_on,
                  shop_row["trust"] if shop_row else "")


def summarize_product(conn, p, since: str) -> ProductSummary:
    s = ProductSummary(p["name"], p["kind"], p["target_cents"])
    if p["kind"] == "game":
        for trusts, label, icon in [(("official",), "Steam", "🎮"),
                                    (("keyshop",), "Claves", "🔑")]:
            series = _series(conn, p["id"], trusts, since, label, icon)
            if series:
                s.main.append(series)
    else:
        trusted = _series(conn, p["id"], (stores.OFFICIAL, stores.RETAILER), since,
                          "Tiendas de confianza", "🏬")
        if trusted:
            s.main.append(trusted)
        other = _series(conn, p["id"], (stores.MARKETPLACE, stores.UNKNOWN), since,
                        "Otras tiendas", "🔎")
        if other and (not trusted or other.last < trusted.last):
            s.extra = other
            if other.trust:
                s.extra_trust = stores.describe(other.shop, other.trust)
    return s


def advice(s: ProductSummary, days_to_bf: int | None) -> str:
    """Consejo ORIENTATIVO basado en reglas sencillas (no es una predicción)."""
    best = s.best
    if not best:
        return "⏳ Sin datos suficientes todavía"
    if best.last <= s.target:
        return "👉 Buen momento: está a tu precio"
    rising = best.last > best.prices[0]
    if rising:
        return "⏳ Mejor esperar: ha subido esta semana"
    if days_to_bf is not None and 0 < days_to_bf <= 10:
        return "⏳ Espera al Black Friday, falta poco"
    if s.light == "🟡" and best.last <= best.lowest:
        return "🤔 Casi: está en su mínimo de la semana y cerca de tu precio"
    return "⏳ Espera: aún lejos de tu precio"


def render_product(s: ProductSummary, days_to_bf: int | None) -> list[str]:
    lines = [f"{s.light} {s.name} — objetivo {euros(s.target)}"]
    if not s.main and not s.extra:
        return lines + ["   Sin datos esta semana"]
    for series in sorted(s.main, key=lambda x: x.last):
        gap = series.last - s.target
        gap_text = "✔ a tu precio" if gap <= 0 else f"faltan {euros(gap)}"
        where = series.label if s.kind == "game" else series.shop
        spark = sparkline(series.prices)
        seen = f" (visto el {series.seen_on})" if series.seen_on else ""
        lines.append(f"   {series.icon} {where}: {euros(series.last)}{seen} · {gap_text}"
                     f"{'  ' + spark if spark else ''} · {trend_text(series.prices[0], series.last)}")
        if series.lowest < series.last:
            lines.append(f"      (mínimo de la semana: {euros(series.lowest)})")
    if s.extra:
        seen = f", visto el {s.extra.seen_on}" if s.extra.seen_on else ""
        trust = f" ({s.extra_trust}{seen})" if s.extra_trust or seen else ""
        lines.append(f"   🔎 {s.extra.shop}: {euros(s.extra.last)}{trust} · solo como pista")
    lines.append(f"   {advice(s, days_to_bf)}")
    return lines


# ---------------------------------------------------------------- el resumen

def build_report(conn, days: int = 7, now: datetime | None = None,
                 include_server: bool = True) -> str:
    now = now or datetime.now(timezone.utc)
    since_dt = now - timedelta(days=days)
    since = since_dt.isoformat(timespec="seconds")
    products = db.list_products(conn)
    if not products:
        return "📊 Resumen semanal: no vigilas nada todavía."

    today = now.astimezone().date()
    bf = black_friday(today.year)
    days_to_bf = (bf - today).days if today <= bf else None

    summaries = sorted((summarize_product(conn, p, since) for p in products),
                       key=lambda s: s.ratio)
    counts = {light: sum(1 for s in summaries if s.light == light)
              for light in ("✅", "🟡", "🔴")}

    lines = [f"📊 Resumen semanal · {since_dt:%d/%m} – {now:%d/%m}"]
    header = []
    if cd := countdown(today):
        header.append(cd)
    header.append(f"✅ {counts['✅']} · 🟡 {counts['🟡']} · 🔴 {counts['🔴']}")
    lines += [" · ".join(header), ""]

    for s in summaries:
        lines += render_product(s, days_to_bf) + [""]

    # Presupuesto de Navidad
    with_price = [s for s in summaries if s.best]
    if with_price:
        today_total = sum(s.best.last for s in with_price)
        target_total = sum(s.target for s in with_price)
        lines.append(f"🎁 Comprarlo todo hoy: {euros(today_total)} · "
                     f"a tus precios: {euros(target_total)}")
        budget = config.christmas_budget_cents()
        if budget is not None:
            diff = budget - today_total
            lines.append(f"   Presupuesto {euros(budget)}: "
                         + (f"te sobran {euros(diff)}" if diff >= 0
                            else f"te pasas {euros(-diff)}"))

    # Búsquedas de SerpApi del mes
    month_start = now.astimezone().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = db.count_api_calls(conn, "serpapi",
                              month_start.astimezone(timezone.utc).isoformat(timespec="seconds"))
    limit = config.SERPAPI_MONTHLY_LIMIT
    warn = "  ⚠ quedan pocas" if used >= limit * 0.8 else ""
    lines.append(f"🔍 SerpApi: {used}/{limit} búsquedas este mes{warn}")

    if include_server and (status := server_status()):
        lines.append(status)
    return "\n".join(lines).rstrip()
