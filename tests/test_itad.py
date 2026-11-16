"""Tests del conector de IsThereAnyDeal SIN conexión a internet."""

from fakes import FakeSession

from vigia.itad import ItadClient, to_cents


def test_to_cents_rounds_correctly():
    assert to_cents(19.99) == 1999
    assert to_cents("24.30") == 2430
    assert to_cents(0.1 + 0.2) == 30
    assert to_cents(None) is None


def test_search_parses_games_and_hides_key_from_url():
    session = FakeSession([{"id": "id-1", "slug": "hades", "title": "Hades", "type": "game"}])
    client = ItadClient("clave-falsa", session=session)
    games = client.search("hades")
    assert games[0].title == "Hades"
    method, url, kwargs = session.calls[0]
    assert method == "GET" and url.endswith("/games/search/v1")
    assert kwargs["headers"]["ITAD-API-Key"] == "clave-falsa"
    assert "clave-falsa" not in url


def test_prices_filters_by_steam():
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
    deals = client.prices(["id-1"], country="ES", shops=[61])["id-1"]
    assert deals[0].shop == "Steam"
    assert deals[0].price_cents == 1249
    assert session.calls[0][2]["params"] == {"country": "ES", "shops": "61"}


def test_steam_appids_takes_first_app():
    session = FakeSession({
        "id-1": ["sub/999", "app/1145360"],
        "id-2": ["sub/5"],          # sin "app/": no tiene página de juego en Steam
    })
    client = ItadClient("clave-falsa", session=session)
    result = client.steam_appids(["id-1", "id-2"])
    assert result == {"id-1": 1145360}
    method, url, _ = session.calls[0]
    assert method == "POST" and url.endswith("/lookup/shop/61/id/v1")


def test_history_parses_price_log_in_cents():
    session = FakeSession([
        {"timestamp": "2026-11-20T10:00:00+01:00", "shop": {"id": 61, "name": "Steam"},
         "deal": {"price": {"amount": 12.49, "amountInt": 1249, "currency": "EUR"},
                  "regular": {"amount": 24.99, "amountInt": 2499, "currency": "EUR"},
                  "cut": 50}},
        {"timestamp": "2025-01-01T10:00:00+01:00", "shop": {"id": 61, "name": "Steam"},
         "deal": {"price": {"amount": 24.99, "amountInt": 2499, "currency": "EUR"},
                  "regular": {"amount": 24.99, "amountInt": 2499, "currency": "EUR"},
                  "cut": 0}},
    ])
    client = ItadClient("clave-falsa", session=session)
    points = client.history("id-1", shops=[61])
    assert [p.price_cents for p in points] == [2499, 1249]     # ordenado por fecha
    method, url, kwargs = session.calls[0]
    assert method == "GET" and url.endswith("/games/history/v2")
    assert kwargs["params"]["shops"] == "61"
