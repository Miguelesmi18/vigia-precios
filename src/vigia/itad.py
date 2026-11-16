"""Conector a la API oficial de IsThereAnyDeal (solo tiendas autorizadas).

Documentación: https://docs.isthereanydeal.com/
Lo usamos para dos cosas:
  1. Buscar juegos y saber su id de Steam.
  2. Consultar el precio en Steam (shops=61), la única tienda oficial que nos interesa.
"""

from dataclasses import dataclass

import requests

BASE_URL = "https://api.isthereanydeal.com"
TIMEOUT = 15        # segundos
STEAM_SHOP_ID = 61  # id de Steam dentro de IsThereAnyDeal


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


def to_cents(amount: float | int | str | None) -> int | None:
    """Convierte 19.99 (o "19.99") en 1999. round() evita errores como 1998.9999."""
    if amount is None:
        return None
    return round(float(amount) * 100)


class ItadClient:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = "vigia-precios/0.2 (proyecto personal)"

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

    def prices(self, game_ids: list[str], country: str = "ES",
               shops: list[int] | None = None) -> dict[str, list[Deal]]:
        """Precios actuales de varios juegos. Devuelve {id_juego: [ofertas]}.

        shops: lista de ids de tienda para filtrar (ej. [61] = solo Steam).
        """
        params = {"country": country}
        if shops:
            params["shops"] = ",".join(str(s) for s in shops)
        data = self._request("POST", "/games/prices/v3",
                             params=params, json_body=game_ids)
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

    def steam_appids(self, game_ids: list[str]) -> dict[str, int]:
        """Busca el id de Steam de cada juego. Devuelve {id_itad: appid}.

        La API responde con listas como ["app/1145360", "sub/12345"];
        nos quedamos con el primer "app/".
        """
        data = self._request("POST", f"/lookup/shop/{STEAM_SHOP_ID}/id/v1",
                             json_body=game_ids)
        result = {}
        for itad_id, shop_ids in (data or {}).items():
            for sid in shop_ids or []:
                if sid.startswith("app/"):
                    result[itad_id] = int(sid.split("/", 1)[1])
                    break
        return result
