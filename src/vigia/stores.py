"""Clasificación de tiendas por nivel de confianza.

  retailer    -> TUS tiendas de confianza (TRUSTED_SHOPS en el .env)
  official    -> tienda oficial de la marca (De'Longhi, Razer...): también de confianza
  marketplace -> vendedores de terceros (eBay, AliExpress, "Amazon.es - Seller"...)
  unknown     -> cualquier otra tienda, aunque sea grande: no está en tu lista

Solo 'retailer' y 'official' generan avisos de compra 🔔; el resto, pistas 🔎.
"""

import os
import re

OFFICIAL, RETAILER, MARKETPLACE, UNKNOWN = "official", "retailer", "marketplace", "unknown"

LABELS = {
    OFFICIAL: "oficial de la marca",
    RETAILER: "tienda de tu confianza",
    MARKETPLACE: "marketplace (vendedores de terceros)",
    UNKNOWN: "fuera de tu lista de confianza",
}

# Tus tiendas de confianza. Se cambian en el .env con TRUSTED_SHOPS
# (separadas por comas), sin tocar el código.
DEFAULT_TRUSTED = ["amazon", "mediamarkt", "media markt", "el corte inglés",
                   "el corte ingles", "carrefour", "fnac", "pccomponentes"]


def trusted_shops() -> list[str]:
    value = os.getenv("TRUSTED_SHOPS", "").strip()
    if not value:
        return DEFAULT_TRUSTED
    return [t.strip().lower() for t in value.split(",") if t.strip()]


MARKETPLACES = [
    "ebay", "aliexpress", "alibaba", "temu", "miravia", "wallapop", "shein", "wish",
    "fruugo", "manomano", "rakuten", "cdiscount", "back market", "backmarket",
]
BRANDS = [
    "de'longhi", "delonghi", "philips", "krups", "nespresso", "cecotec", "melitta",
    "siemens", "bosch", "saeco", "sage", "breville", "dolce gusto", "jura",
    "samsung", "xiaomi", "lg", "sony", "nintendo", "playstation", "lenovo", "hp",
    "asus", "logitech", "razer", "8bitdo", "steelseries", "corsair", "hyperx", "dyson", "rowenta", "moulinex", "tefal", "taurus", "smeg",
]

# "Amazon.es - Seller", "vendedor externo"...: vende un tercero, no la tienda
THIRD_PARTY_WORDS = ["seller", "vendedor", "marketplace"]

# Tiendas fuera de España: envío más caro, posibles aduanas y garantía distinta
FOREIGN_TLDS = ["de", "fr", "it", "uk", "ua", "pl", "nl", "be", "at", "ch", "cz", "ro",
                "hu", "se", "dk", "no", "fi", "cn", "hk", "jp", "us", "ru", "tr", "lt", "lv"]
FOREIGN_SHOPS = ["play-asia", "ldlc"]

# Palabras que indican producto usado o reacondicionado (se descartan)
SECOND_HAND_WORDS = ["reacondicionado", "reacondicionada", "segunda mano", "usado",
                     "usada", "refurbished", "renewed", "como nuevo", "outlet"]


def _contains(name: str, terms: list[str]) -> bool:
    """Busca palabras completas: 'game' no coincide con 'gameseal'."""
    return any(re.search(rf"(?<!\w){re.escape(t)}(?!\w)", name) for t in terms)


def classify(shop: str) -> str:
    name = (shop or "").lower()
    # Primero marketplaces: "eBay - tienda X" o "Amazon.es - Seller" no cuentan
    # como tienda grande
    if _contains(name, MARKETPLACES) or _contains(name, THIRD_PARTY_WORDS):
        return MARKETPLACE
    if _contains(name, trusted_shops()):
        return RETAILER
    if _contains(name, BRANDS):
        return OFFICIAL
    return UNKNOWN


def is_foreign(shop: str) -> bool:
    """¿Tienda de fuera de España? Por el dominio (.de, .ua...) o por nombre conocido."""
    name = (shop or "").lower()
    if _contains(name, FOREIGN_SHOPS):
        return True
    return any(re.search(rf"\.{tld}(?!\w)", name) for tld in FOREIGN_TLDS)


def describe(shop: str, level: str) -> str:
    """Texto de confianza para mostrar: 'gran tienda', 'tienda desconocida · extranjera'..."""
    label = LABELS[level]
    if is_foreign(shop):
        label += " · extranjera: revisa envío, aduanas y garantía"
    return label


def is_trusted(level: str) -> bool:
    return level in (OFFICIAL, RETAILER)


def looks_second_hand(*texts: str | None) -> bool:
    blob = " ".join(t for t in texts if t).lower()
    return any(w in blob for w in SECOND_HAND_WORDS)
