"""Detector de ofertas falsas.

Reglas (inspiradas en la directiva europea Omnibus, que obliga a las tiendas a
indicar el precio más bajo de los 30 días anteriores a una rebaja):

1. REBAJA FALSA: si en los 30 días antes de empezar la oferta el juego ya
   costaba lo mismo o menos, no es una rebaja de verdad.
2. PRECIO INFLADO: si en esos 30 días el precio se subió más de un 10 % por
   encima de lo habitual (los 90 días anteriores) y luego se "rebajó".
3. MÍNIMO HISTÓRICO: compara el precio con el más bajo de todo el historial.

El historial es un REGISTRO DE CAMBIOS: cada punto indica el precio desde esa
fecha hasta el siguiente cambio.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median

WINDOW = timedelta(days=30)        # ventana de la regla Omnibus
MIN_HISTORY = timedelta(days=7)    # con menos historial no se puede juzgar nada
BASELINE = timedelta(days=90)      # periodo para calcular el precio "habitual"
INFLATION_MARGIN = 1.10            # +10 % = subida sospechosa
NEAR_LOW_MARGIN = 1.10             # hasta +10 % del mínimo = "cerca del mínimo"
FAR_FROM_LOW_MARGIN = 1.30         # más de +30 % del mínimo = "lejos del mínimo"

FAKE, GOOD, NORMAL, UNKNOWN = "fake", "good", "normal", "unknown"
LABELS = {
    FAKE: "❌ Oferta sospechosa",
    GOOD: "✅ Buena oferta",
    NORMAL: "➖ Precio normal",
    UNKNOWN: "❔ Sin historial suficiente",
}


@dataclass
class PricePoint:
    timestamp: datetime
    price_cents: int


@dataclass
class Verdict:
    level: str
    reasons: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return LABELS[self.level]

    def summary(self) -> str:
        return f"{self.label}: " + "; ".join(self.reasons) if self.reasons else self.label


def euros(cents: int) -> str:
    return f"{cents / 100:.2f} €".replace(".", ",")


def price_at(points: list[PricePoint], moment: datetime) -> int | None:
    """Precio vigente en un momento dado (el último cambio anterior a él)."""
    current = None
    for p in points:
        if p.timestamp <= moment:
            current = p.price_cents
        else:
            break
    return current


def prices_in_window(points: list[PricePoint], start: datetime, end: datetime) -> list[int]:
    """Todos los precios que estuvieron vigentes entre start y end."""
    prices = []
    first = price_at(points, start)
    if first is not None:
        prices.append(first)
    prices += [p.price_cents for p in points if start < p.timestamp < end]
    return prices


def offer_start(points: list[PricePoint], current_cents: int, now: datetime) -> datetime:
    """Fecha en la que empezó el precio actual."""
    if not points or points[-1].price_cents != current_cents:
        return now    # el registro aún no recoge el precio actual
    start = points[-1].timestamp
    for p in reversed(points):
        if p.price_cents != current_cents:
            break
        start = p.timestamp
    return start


def analyze(points: list[PricePoint], current_cents: int, cut: int,
            now: datetime) -> Verdict:
    """Analiza si el precio actual es una buena oferta, normal o sospechosa."""
    points = sorted(points, key=lambda p: p.timestamp)
    if not points:
        return Verdict(UNKNOWN, ["no hay historial de precios"])

    # Con muy poco historial, "mínimo histórico" no significa nada
    span = now - points[0].timestamp
    if span < MIN_HISTORY:
        days = max(span.days, 0)
        return Verdict(UNKNOWN, [f"solo {days} día(s) de historial; "
                                 f"hacen falta {MIN_HISTORY.days} para valorar la oferta"])

    reasons: list[str] = []
    level = NORMAL
    start = offer_start(points, current_cents, now)
    enough_history = points[0].timestamp <= start - WINDOW

    # Reglas 1 y 2: solo si se anuncia como rebaja y hay historial suficiente
    if cut > 0 and enough_history:
        last_30 = prices_in_window(points, start - WINDOW, start)
        if last_30 and min(last_30) <= current_cents:
            level = FAKE
            reasons.append(f"no es una rebaja real: en los 30 días anteriores "
                           f"ya costaba {euros(min(last_30))}")
        baseline = prices_in_window(points, start - WINDOW - BASELINE, start - WINDOW)
        if last_30 and baseline:
            usual, peak = round(median(baseline)), max(last_30)
            if peak > usual * INFLATION_MARGIN and peak > current_cents:
                level = FAKE
                reasons.append(f"subieron el precio de {euros(usual)} a {euros(peak)} "
                               f"antes de rebajarlo")
    elif cut > 0:
        reasons.append("historial de menos de 30 días antes de la oferta")

    # Regla 3: comparación con el mínimo histórico
    lowest = min([p.price_cents for p in points] + [current_cents])
    # Sin descuento, estar en el "mínimo" solo significa que nunca ha bajado:
    # es el precio normal, no una oferta (ej. un juego en reserva a 69,99 €)
    if current_cents <= lowest and cut == 0:
        reasons.append("precio de siempre: nunca ha estado más barato")
    elif current_cents <= lowest:
        reasons.append("🎯 mínimo histórico")
        if level != FAKE:
            level = GOOD
    elif current_cents <= lowest * NEAR_LOW_MARGIN:
        reasons.append(f"cerca del mínimo histórico ({euros(lowest)})")
        if level != FAKE and cut > 0:
            level = GOOD
    elif current_cents > lowest * FAR_FROM_LOW_MARGIN:
        reasons.append(f"lejos del mínimo histórico ({euros(lowest)})")
    else:
        reasons.append(f"mínimo histórico: {euros(lowest)}")

    return Verdict(level, reasons)


def compare_to_low(current_cents: int, low_cents: int | None) -> Verdict:
    """Versión simple para tiendas de claves: solo hay precio actual y mínimo histórico."""
    if low_cents is None:
        return Verdict(UNKNOWN, ["sin mínimo histórico"])
    if current_cents <= low_cents * NEAR_LOW_MARGIN:
        return Verdict(GOOD, [f"cerca del mínimo histórico ({euros(low_cents)})"])
    if current_cents > low_cents * FAR_FROM_LOW_MARGIN:
        return Verdict(NORMAL, [f"lejos del mínimo histórico ({euros(low_cents)})"])
    return Verdict(NORMAL, [f"mínimo histórico: {euros(low_cents)}"])
