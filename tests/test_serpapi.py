"""Tests del conector de SerpApi (Google Shopping) SIN conexión a internet."""

from fakes import FakeSession

from vigia.serpapi import (Offer, SerpApiClient, find_shipping, flag_suspicious,
                           matches_model, parse_shipping)


def test_parse_shipping():
    assert parse_shipping("Envío gratis") == 0
    assert parse_shipping("Free delivery") == 0
    assert parse_shipping("Envío: 4,99 €") == 499
    assert parse_shipping("+5,95 € de envío") == 595
    assert parse_shipping(None) is None
    assert parse_shipping("Llega mañana") is None


def test_matches_model_ignores_spaces_and_dots():
    assert matches_model("De'Longhi Magnifica S ECAM 22.110.B", "ECAM22.110")
    assert matches_model("cafetera ecam22-110-b", "ECAM22.110")
    assert not matches_model("Filtro de agua para ECAM", "ECAM22.110")
    assert matches_model("lo que sea", None)


def test_shopping_parses_filters_and_sorts():
    session = FakeSession({"shopping_results": [
        {"title": "De'Longhi Magnifica S ECAM22.110.B", "source": "MediaMarkt",
         "extracted_price": 259.0, "delivery": "Envío gratis", "product_link": "https://a"},
        {"title": "De'Longhi Magnifica S ECAM22.110.B", "source": "eBay - vendedor",
         "extracted_price": 239.0, "delivery": "Envío: 9,99 €"},
        {"title": "De'Longhi ECAM22.110.B Reacondicionado", "source": "Amazon.es",
         "extracted_price": 180.0},
        {"title": "Filtro de agua De'Longhi", "source": "Amazon.es", "extracted_price": 12.0},
        {"title": "De'Longhi Magnifica ECAM22.110.B", "source": "Amazon.es",
         "extracted_price": 249.99, "delivery": "Envío: 3,50 €"},
    ]})
    client = SerpApiClient("clave-falsa", session=session)
    offers = client.shopping("delonghi magnifica s", model="ECAM22.110")

    # Sin reacondicionado ni filtro; ordenado por precio FINAL (con envío)
    assert [(o.shop, o.total_cents) for o in offers] == [
        ("eBay - vendedor", 24899), ("Amazon.es", 25349), ("MediaMarkt", 25900)]
    assert offers[0].trust == "marketplace"
    params = session.calls[0][2]["params"]
    assert params["engine"] == "google_shopping" and params["gl"] == "es"


def test_find_shipping_in_extensions():
    assert find_shipping({"extensions": ["4,5 estrellas", "Envío gratuito"]}) == 0
    assert find_shipping({"delivery": "Envío: 3,99 €"}) == 399
    assert find_shipping({"extensions": ["Oferta"]}) is None


def test_flag_suspicious_too_cheap():
    offers = [Offer("x", "Bilma Boutique", "unknown", 6930, None, None),
              Offer("x", "Amazon.es", "retailer", 27999, None, None),
              Offer("x", "Leroy Merlin", "retailer", 28390, None, None),
              Offer("x", "Suditel", "unknown", 35900, None, None)]
    flag_suspicious(offers)
    assert [o.suspicious for o in offers] == [True, False, False, False]


def test_safe_url_encodes_spaces():
    from vigia.serpapi import safe_url
    url = "https://www.google.com/search?q=Razer Hammerhead V3&udm=28"
    assert safe_url(url) == "https://www.google.com/search?q=Razer%20Hammerhead%20V3&udm=28"
    assert safe_url(safe_url(url)) == safe_url(url)      # no codifica dos veces
    assert safe_url(None) is None


def test_model_must_not_continue_with_letter():
    assert matches_model("8BitDo Ultimate 2 Wireless Controller", "Ultimate 2")
    assert not matches_model("Mando 8BitDo Ultimate 2C Switch", "Ultimate 2")
    assert not matches_model("8BitDo Ultimate 2C", "Ultimate 2")


def test_accessories_are_detected():
    from vigia.serpapi import looks_like_accessory
    assert looks_like_accessory("Funda de silicona para 8Bitdo Ultimate 2")
    assert looks_like_accessory("Aenllosi Estuche Rígido para 8Bitdo Ultimate 2")
    assert looks_like_accessory("Adaptador 8BitDo USB Wireless Adapter 2")
    assert not looks_like_accessory("Mando 8BitDo Ultimate 2 Wireless")
    # si lo que buscas ES el accesorio, no se descarta
    assert not looks_like_accessory("Adaptador 8BitDo USB", query="adaptador 8bitdo")


class FlakySession:
    """Primero falla con 503 y después responde bien."""

    def __init__(self, data):
        from fakes import FakeResponse
        self.responses = [FakeResponse({}, status_code=503), FakeResponse(data)]
        self.headers = {}
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


def test_shopping_retries_once_after_server_error():
    session = FlakySession({"shopping_results": [
        {"title": "Mando 8BitDo Ultimate 2", "source": "PcComponentes", "extracted_price": 54.99},
        {"title": "Funda para 8BitDo Ultimate 2", "source": "PcComponentes", "extracted_price": 9.99},
    ]})
    client = SerpApiClient("clave-falsa", session=session)
    client._sleep = lambda s: None
    offers = client.shopping("8BitDo Ultimate 2", model="Ultimate 2")
    assert session.calls == 2
    assert [o.title for o in offers] == ["Mando 8BitDo Ultimate 2"]   # la funda, fuera
