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
