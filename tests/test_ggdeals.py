"""Tests del conector de GG.deals SIN conexión a internet."""

from fakes import FakeSession

from vigia.ggdeals import GgDealsClient


def test_prices_parses_keyshops_and_skips_unknown():
    session = FakeSession({
        "success": True,
        "data": {
            "1145360": {
                "title": "Hades",
                "url": "https://gg.deals/game/hades/",
                "prices": {
                    "currentRetail": "24.50",
                    "currentKeyshops": "11.99",
                    "historicalRetail": "9.99",
                    "historicalKeyshops": "7.50",
                    "currency": "EUR",
                },
            },
            "999": None,     # juego que GG.deals no conoce
        },
    })
    client = GgDealsClient("clave-falsa", session=session)
    result = client.prices([1145360, 999], region="ES")

    assert set(result) == {1145360}
    hades = result[1145360]
    assert hades.keyshop_cents == 1199
    assert hades.keyshop_low_cents == 750
    assert hades.retail_cents == 2450
    params = session.calls[0][2]["params"]
    assert params["ids"] == "1145360,999"
    assert params["region"] == "es"


def test_prices_handles_null_price_fields():
    session = FakeSession({"success": True, "data": {"1": {
        "title": "X", "url": None,
        "prices": {"currentRetail": None, "currentKeyshops": None,
                   "historicalRetail": None, "historicalKeyshops": None,
                   "currency": "EUR"}}}})
    result = GgDealsClient("k", session=session).prices([1])
    assert result[1].keyshop_cents is None
