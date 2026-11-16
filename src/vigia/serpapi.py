"""Conector a SerpApi (resultados de Google Shopping) para productos físicos.

Documentación: https://serpapi.com/google-shopping-api
Plan gratuito: 250 búsquedas al mes. Cada llamada a shopping() gasta UNA.
"""

import re
from dataclasses import dataclass

import requests

from vigia import stores
from vigia.itad import to_cents

BASE_URL = "https://serpapi.com/search.json"
TIMEOUT = 30


@dataclass
class Offer:
    title: str
    shop: str
    trust: str                    # official / retailer / marketplace / unknown
    price_cents: int
    shipping_cents: int | None    # None = Google no dice el envío
    link: str | None

    @property
    def total_cents(self) -> int:
        """Precio final: producto + envío (si se conoce)."""
        return self.price_cents + (self.shipping_cents or 0)


def parse_shipping(delivery: str | None) -> int | None:
    """'Envío gratis' -> 0, 'Envío: 4,99 €' -> 499, texto raro -> None."""
    if not delivery:
        return None
    text = delivery.lower()
    if "gratis" in text or "free" in text:
        return 0
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)", text)
    if not match:
        return None
    return to_cents(match.group(1).replace(",", "."))


def matches_model(title: str, model: str | None) -> bool:
    """Si se da un modelo (ej. 'ECAM22.110'), el título tiene que contenerlo.

    Se ignoran mayúsculas, espacios, puntos y guiones: 'ECAM 22-110' también vale.
    """
    if not model:
        return True
    clean = lambda s: re.sub(r"[\s.\-_/]", "", s.lower())
    return clean(model) in clean(title)


class SerpApiClient:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = "vigia-precios/0.3 (proyecto personal)"

    def shopping(self, query: str, country: str = "es", language: str = "es",
                 model: str | None = None) -> list[Offer]:
        """Busca en Google Shopping. Devuelve ofertas NUEVAS, de la más barata a la más cara."""
        params = {"engine": "google_shopping", "q": query, "gl": country.lower(),
                  "hl": language, "api_key": self.api_key}
        resp = self.session.get(BASE_URL, params=params, timeout=TIMEOUT)
        if resp.status_code == 429:
            raise RuntimeError("SerpApi: límite de búsquedas alcanzado.")
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(f"SerpApi: {data['error']}")

        offers = []
        for item in data.get("shopping_results", []):
            title = item.get("title", "")
            price = item.get("extracted_price")
            if price is None or not matches_model(title, model):
                continue
            extras = " ".join(str(e) for e in item.get("extensions", []) or [])
            if stores.looks_second_hand(title, item.get("snippet"), extras,
                                        item.get("second_hand_condition")):
                continue
            shop = item.get("source", "?")
            offers.append(Offer(
                title=title,
                shop=shop,
                trust=stores.classify(shop),
                price_cents=to_cents(price),
                shipping_cents=parse_shipping(item.get("delivery")),
                link=item.get("product_link") or item.get("link"),
            ))
        return sorted(offers, key=lambda o: o.total_cents)
