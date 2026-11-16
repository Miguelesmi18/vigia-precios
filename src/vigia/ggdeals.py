"""Conector a la API de GG.deals: precios en tiendas de claves (keyshops).

Documentación: https://gg.deals/api/prices/
Las tiendas de claves (Eneba, Instant Gaming, G2A, Kinguin...) son revendedores
o marketplaces de terceros: más baratos, pero con más riesgo (claves de otra
región, vendedores desconocidos). Por eso se marcan como 'keyshop'.

Límite de la API: 100 juegos por minuto y 1.000 por hora.
Limitación: la API da el precio más bajo entre todas las tiendas de claves,
pero NO dice en cuál. La tienda concreta se ve en el enlace de GG.deals.
"""

from dataclasses import dataclass

import requests

from vigia.itad import to_cents

BASE_URL = "https://api.gg.deals/v1/prices/by-steam-app-id/"
TIMEOUT = 15
MAX_IDS = 100   # máximo de ids por petición


@dataclass
class KeyshopPrice:
    title: str
    url: str | None
    keyshop_cents: int | None             # precio actual más bajo en tiendas de claves
    keyshop_low_cents: int | None         # mínimo histórico en tiendas de claves
    retail_cents: int | None              # precio actual más bajo en tiendas oficiales
    currency: str


class GgDealsClient:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = "vigia-precios/0.2 (proyecto personal)"

    def prices(self, appids: list[int], region: str = "es") -> dict[int, KeyshopPrice]:
        """Precios por id de Steam. Devuelve {appid: KeyshopPrice}."""
        result: dict[int, KeyshopPrice] = {}
        for start in range(0, len(appids), MAX_IDS):
            chunk = appids[start:start + MAX_IDS]
            # Esta API exige la clave en la URL (no admite cabecera)
            params = {"ids": ",".join(str(a) for a in chunk),
                      "key": self.api_key, "region": region.lower()}
            resp = self.session.get(BASE_URL, params=params, timeout=TIMEOUT)
            if resp.status_code == 429:
                raise RuntimeError("GG.deals: límite de peticiones alcanzado, espera un poco.")
            resp.raise_for_status()
            body = resp.json()
            if not body.get("success", False):
                raise RuntimeError("GG.deals respondió con un error.")
            for appid_text, item in (body.get("data") or {}).items():
                if not item:          # null = juego no encontrado en GG.deals
                    continue
                p = item.get("prices") or {}
                result[int(appid_text)] = KeyshopPrice(
                    title=item.get("title", ""),
                    url=item.get("url"),
                    keyshop_cents=to_cents(p.get("currentKeyshops")),
                    keyshop_low_cents=to_cents(p.get("historicalKeyshops")),
                    retail_cents=to_cents(p.get("currentRetail")),
                    currency=p.get("currency", "EUR"),
                )
        return result
