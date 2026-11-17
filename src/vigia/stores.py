"""Clasificación de tiendas por nivel de confianza.

  official    -> tienda oficial de la marca (De'Longhi, Philips...)
  retailer    -> gran tienda conocida en España (Amazon, MediaMarkt...)
  marketplace -> plataforma de vendedores de terceros (eBay, AliExpress...)
  unknown     -> cualquier otra: puede ser legal, pero no la conocemos

Puedes ampliar estas listas cuando quieras: es solo texto.
"""

import re

OFFICIAL, RETAILER, MARKETPLACE, UNKNOWN = "official", "retailer", "marketplace", "unknown"

LABELS = {
    OFFICIAL: "oficial de la marca",
    RETAILER: "gran tienda",
    MARKETPLACE: "marketplace (vendedores de terceros)",
    UNKNOWN: "tienda desconocida",
}

# Se compara en minúsculas con el nombre de la tienda que da Google Shopping
RETAILERS = [
    "amazon", "mediamarkt", "media markt", "el corte inglés", "el corte ingles",
    "pccomponentes", "fnac", "carrefour", "worten", "alcampo", "eroski", "hipercor",
    "leroy merlin", "lidl", "decathlon", "conforama", "ikea", "coolmod", "electrocosto",
    "tien21", "milar", "euronics", "apple", "game", "xtralife",
]
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
    if _contains(name, RETAILERS):
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
