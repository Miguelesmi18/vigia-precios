"""Conector a SerpApi (resultados de Google Shopping) para productos físicos.

Documentación: https://serpapi.com/google-shopping-api
Plan gratuito: 250 búsquedas al mes. Cada llamada a shopping() gasta UNA.
"""

import re
import time
from dataclasses import dataclass
from statistics import median

import requests
from requests.utils import requote_uri

from vigia import stores
from vigia.itad import to_cents

BASE_URL = "https://serpapi.com/search.json"
TIMEOUT = 60        # Google Shopping a veces tarda (sobre todo en Black Friday)
RETRY_WAIT = 5      # segundos antes del único reintento
# Una oferta por debajo de la mitad del precio mediano es sospechosa
# (precio "demasiado bueno para ser verdad": posible estafa o producto distinto)
SUSPICIOUS_RATIO = 0.5


@dataclass
class Offer:
    title: str
    shop: str
    trust: str                    # official / retailer / marketplace / unknown
    price_cents: int
    shipping_cents: int | None    # None = Google no dice el envío
    link: str | None
    suspicious: bool = False      # precio anormalmente bajo comparado con el resto

    @property
    def total_cents(self) -> int:
        """Precio final: producto + envío (si se conoce)."""
        return self.price_cents + (self.shipping_cents or 0)


SHIPPING_WORDS = ("envío", "envio", "delivery", "shipping", "entrega")


def parse_shipping(delivery: str | None) -> int | None:
    """'Envío gratis' -> 0, 'Envío: 4,99 €' -> 499, texto raro -> None."""
    if not delivery:
        return None
    text = delivery.lower()
    if "gratis" in text or "gratuito" in text or "free" in text:
        return 0
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)", text)
    if not match:
        return None
    return to_cents(match.group(1).replace(",", "."))


def find_shipping(item: dict) -> int | None:
    """Busca el envío en 'delivery' y, si no está, en 'extensions' y 'snippet'."""
    candidates = [item.get("delivery")]
    candidates += [str(e) for e in item.get("extensions", []) or []]
    candidates.append(item.get("snippet"))
    for text in candidates:
        if text and any(w in text.lower() for w in SHIPPING_WORDS):
            value = parse_shipping(text)
            if value is not None:
                return value
    return None


def flag_suspicious(offers: list["Offer"]) -> None:
    """Marca las ofertas con un precio anormalmente bajo respecto al resto."""
    if len(offers) < 3:
        return
    typical = median(o.total_cents for o in offers)
    for o in offers:
        o.suspicious = o.total_cents < typical * SUSPICIOUS_RATIO


def matches_model(title: str, model: str | None) -> bool:
    """Si se da un modelo (ej. 'ECAM22.110'), el título tiene que contenerlo.

    Se ignoran mayúsculas, espacios, puntos y guiones: 'ECAM 22-110' también vale.
    Pero el modelo no puede seguir pegado a otra letra o número:
    'Ultimate 2' NO vale para 'Ultimate 2C', que es otro mando.
    """
    if not model:
        return True
    chars = re.sub(r"[\s.\-_/]", "", model.lower())
    pattern = r"[\s.\-_/]*".join(re.escape(c) for c in chars)
    return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", title.lower()) is not None


# Palabras de accesorios: si salen en el título (y no en lo que buscas), no es el producto
ACCESSORY_WORDS = ("funda", "estuche", "carcasa", "protector", "adaptador", "cable",
                   "soporte", "skin", "pegatina", "repuesto", "recambio", "filtro",
                   "case", "cover", "stand", "almohadilla", "grips")


def looks_like_accessory(title: str, query: str = "") -> bool:
    words = set(re.findall(r"[a-záéíóúñü]+", title.lower()))
    wanted = set(re.findall(r"[a-záéíóúñü]+", query.lower()))
    return any(w in words and w not in wanted for w in ACCESSORY_WORDS)


class SerpApiClient:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        self.api_key = api_key
        self.session = session or requests.Session()
        self._sleep = time.sleep
        self.session.headers["User-Agent"] = "vigia-precios/0.5 (proyecto personal)"

    def _get(self, params):
        """Una petición con UN reintento si SerpApi tarda demasiado o falla (5xx)."""
        for attempt in (1, 2):
            try:
                resp = self.session.get(BASE_URL, params=params, timeout=TIMEOUT)
            except requests.Timeout:
                if attempt == 2:
                    raise
            else:
                if resp.status_code < 500 or attempt == 2:
                    return resp
            self._sleep(RETRY_WAIT)

    def shopping(self, query: str, country: str = "es", language: str = "es",
                 model: str | None = None) -> list[Offer]:
        """Busca en Google Shopping. Devuelve ofertas NUEVAS, de la más barata a la más cara."""
        params = {"engine": "google_shopping", "q": query, "gl": country.lower(),
                  "hl": language, "api_key": self.api_key}
        resp = self._get(params)
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
            if looks_like_accessory(title, query):
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
                shipping_cents=find_shipping(item),
                link=safe_url(item.get("product_link") or item.get("link")),
            ))
        flag_suspicious(offers)
        return sorted(offers, key=lambda o: o.total_cents)


def safe_url(url: str | None) -> str | None:
    """Codifica espacios y símbolos raros: Telegram corta un enlace en el primer espacio."""
    return requote_uri(url) if url else url
