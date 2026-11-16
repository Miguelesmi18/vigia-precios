"""Tests del conector de IsThereAnyDeal SIN conexión a internet.

Usamos un objeto falso (FakeSession) que devuelve respuestas preparadas.
Así los tests son rápidos, gratis y no gastan peticiones de la API.
"""

from vigia.itad import ItadClient, to_cents


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, data):
        self.data = data
        self.headers = {}
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse(self.data)


def test_to_cents_rounds_correctly():
    assert to_cents(19.99) == 1999
    assert to_cents(0.1 + 0.2) == 30
    assert to_cents(None) is None


def test_search_parses_games():
    session = FakeSession([{"id": "id-1", "slug": "hades", "title": "Hades", "type": "game"}])
    client = ItadClient("clave-falsa", session=session)
    games = client.search("hades")
    assert games[0].title == "Hades"
    method, url, kwargs = session.calls[0]
    assert method == "GET" and url.endswith("/games/search/v1")
    # la clave va en la cabecera, no en la URL
    assert kwargs["headers"]["ITAD-API-Key"] == "clave-falsa"


def test_prices_parses_deals_in_cents():
    session = FakeSession([{
        "id": "id-1",
        "deals": [{
            "shop": {"id": 61, "name": "Steam"},
            "price": {"amount": 12.49, "currency": "EUR"},
            "regular": {"amount": 24.99, "currency": "EUR"},
            "cut": 50,
            "url": "https://example.com",
        }],
    }])
    client = ItadClient("clave-falsa", session=session)
    deals = client.prices(["id-1"], country="ES")["id-1"]
    assert deals[0].shop == "Steam"
    assert deals[0].price_cents == 1249
    assert deals[0].regular_cents == 2499
    assert session.calls[0][2]["params"] == {"country": "ES"}
