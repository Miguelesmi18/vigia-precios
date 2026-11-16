"""Conector a la API oficial de IsThereAnyDeal (solo tiendas autorizadas).

Documentación: https://docs.isthereanydeal.com/
"""

from dataclasses import dataclass

import requests

BASE_URL = "https://api.isthereanydeal.com"
TIMEOUT = 15  # segundos


@dataclass
class Game:
    id: str
    title: str
    type: str | None = None


@dataclass
class Deal:
    shop: str
    price_cents: int
    regular_cents: int | None
    currency: str
    cut: int            # % de descuento
    url: str | None


def to_cents(amount: float | int | None) -> int | None:
    """Convierte 19.99 en 1999. round() evita errores como 19.99*100 = 1998.9999."""
    if amount is None:
        return None
    return round(float(amount) * 100)


class ItadClient:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = "vigia-precios/0.1 (proyecto personal)"

    def _request(self, method: str, path: str, params: dict | None = None,
                 json_body=None):
        # La clave va en la cabecera, así no aparece en las URLs de los logs
        headers = {"ITAD-API-Key": self.api_key}
        resp = self.session.request(method, BASE_URL + path, params=params,
                                    json=json_body, headers=headers,
                                    timeout=TIMEOUT)
        if resp.status_code == 429:
            raise RuntimeError("IsThereAnyDeal: demasiadas peticiones, espera un poco.")
        resp.raise_for_status()
        return resp.json()

    def search(self, title: str, results: int = 5) -> list[Game]:
        """Busca juegos por título."""
        data = self._request("GET", "/games/search/v1",
                             params={"title": title, "results": results})
        return [Game(id=g["id"], title=g["title"], type=g.get("type"))
                for g in data]

    def prices(self, game_ids: list[str], country: str = "ES") -> dict[str, list[Deal]]:
        """Precios actuales de varios juegos. Devuelve {id_juego: [ofertas]}."""
        data = self._request("POST", "/games/prices/v3",
                             params={"country": country}, json_body=game_ids)
        result: dict[str, list[Deal]] = {}
        for item in data:
            deals = []
            for d in item.get("deals", []):
                price = d.get("price") or {}
                regular = d.get("regular") or {}
                deals.append(Deal(
                    shop=d["shop"]["name"],
                    price_cents=to_cents(price.get("amount")),
                    regular_cents=to_cents(regular.get("amount")),
                    currency=price.get("currency", "EUR"),
                    cut=d.get("cut", 0),
                    url=d.get("url"),
                ))
            result[item["id"]] = deals
        return result
