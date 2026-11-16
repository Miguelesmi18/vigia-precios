"""Programa de comandos: vigia search | add | list | remove | check."""

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

from vigia import analysis, config, db
from vigia.ggdeals import GgDealsClient
from vigia.itad import STEAM_SHOP_ID, ItadClient

KEYSHOP_LABEL = "Tiendas de claves (GG.deals)"
HISTORY_DAYS = 400   # días de historial de Steam que se piden para el análisis
KEYSHOP_WARNING = "⚠ tienda de claves: revisa región, plataforma y vendedor antes de comprar"


@dataclass
class Clients:
    itad: ItadClient | None = None
    gg: GgDealsClient | None = None    # None si no hay clave de GG.deals


def euros(cents: int | None) -> str:
    """1999 -> '19,99 €' (formato español)."""
    if cents is None:
        return "-"
    return f"{cents / 100:.2f} €".replace(".", ",")


def parse_euros(text: str) -> int:
    """'19,99' o '19.99' -> 1999 céntimos."""
    value = float(text.replace(",", "."))
    if value <= 0:
        raise argparse.ArgumentTypeError("El precio tiene que ser mayor que 0.")
    return round(value * 100)


def cmd_search(args, conn, clients):
    games = clients.itad.search(args.title)
    if not games:
        print("No he encontrado ningún juego con ese título.")
        return 1
    for i, g in enumerate(games, start=1):
        print(f"{i}. {g.title}  [{g.type or '?'}]")
    return 0


def cmd_add(args, conn, clients):
    games = clients.itad.search(args.title, results=1)
    if not games:
        print("No he encontrado ese juego. Prueba con 'vigia search'.")
        return 1
    game = games[0]
    appid = clients.itad.steam_appids([game.id]).get(game.id)
    try:
        pid = db.add_product(conn, game.title, args.target, itad_id=game.id,
                             steam_appid=appid)
    except sqlite3.IntegrityError:  # ya estaba en la lista
        print(f"'{game.title}' ya estaba en la lista.")
        return 1
    print(f"Añadido #{pid}: {game.title} (aviso por debajo de {euros(args.target)})")
    if appid is None:
        print("   Ojo: no está en Steam, así que no se podrán comparar precios.")
    return 0


def cmd_list(args, conn, clients):
    products = db.list_products(conn)
    if not products:
        print("No vigilas nada todavía. Usa: vigia add \"titulo\" 15")
        return 0
    for p in products:
        print(f"#{p['id']}  {p['name']}  -> objetivo {euros(p['target_cents'])}")
    return 0


def cmd_remove(args, conn, clients):
    if db.remove_product(conn, args.id):
        print(f"Eliminado #{args.id}.")
        return 0
    print(f"No existe el #{args.id}.")
    return 1


def _fill_missing_appids(conn, clients, products):
    """Juegos añadidos con la versión 0.1 no tienen id de Steam: se busca ahora."""
    missing = [p for p in products if p["steam_appid"] is None]
    if not missing:
        return products
    found = clients.itad.steam_appids([p["itad_id"] for p in missing])
    for p in missing:
        if p["itad_id"] in found:
            db.set_steam_appid(conn, p["id"], found[p["itad_id"]])
    return [p for p in db.list_products(conn) if p["itad_id"]]


def cmd_check(args, conn, clients):
    """Consulta Steam y tiendas de claves, guarda el historial y avisa."""
    products = [p for p in db.list_products(conn) if p["itad_id"]]
    if not products:
        if not args.quiet:
            print("No hay juegos que comprobar.")
        return 0

    products = _fill_missing_appids(conn, clients, products)
    checked_at = db.now_iso()

    # 1) Steam, a través de IsThereAnyDeal (solo la tienda 61)
    steam = clients.itad.prices([p["itad_id"] for p in products],
                                country=config.COUNTRY, shops=[STEAM_SHOP_ID])

    # 2) Tiendas de claves, a través de GG.deals (si hay clave)
    keyshops = {}
    if clients.gg:
        appids = [p["steam_appid"] for p in products if p["steam_appid"]]
        if appids:
            keyshops = clients.gg.prices(appids, region=config.COUNTRY)
    elif not args.quiet:
        print("(Sin GGDEALS_API_KEY en .env: solo se consulta Steam)\n")

    for p in products:
        target = p["target_cents"]
        steam_deals = steam.get(p["itad_id"], [])
        steam_best = min(steam_deals, key=lambda d: d.price_cents) if steam_deals else None
        ks = keyshops.get(p["steam_appid"]) if p["steam_appid"] else None

        # Guardar en el historial
        if steam_best:
            db.save_price(conn, p["id"], steam_best.shop, steam_best.price_cents,
                          steam_best.regular_cents, steam_best.currency,
                          steam_best.url, checked_at=checked_at, trust="official")
        if ks and ks.keyshop_cents is not None:
            db.save_price(conn, p["id"], KEYSHOP_LABEL, ks.keyshop_cents, None,
                          ks.currency, ks.url, checked_at=checked_at, trust="keyshop")

        # Análisis de la oferta (detector de ofertas falsas)
        steam_verdict = None
        if steam_best:
            now = datetime.now(timezone.utc)
            points = clients.itad.history(p["itad_id"], country=config.COUNTRY,
                                          shops=[STEAM_SHOP_ID],
                                          since=now - timedelta(days=HISTORY_DAYS))
            steam_verdict = analysis.analyze(points, steam_best.price_cents,
                                             steam_best.cut, now)
        ks_verdict = None
        if ks and ks.keyshop_cents is not None:
            ks_verdict = analysis.compare_to_low(ks.keyshop_cents, ks.keyshop_low_cents)

        # Avisos (los que van a Telegram)
        if steam_best and steam_best.price_cents <= target:
            print(f"🔔 {p['name']}: {euros(steam_best.price_cents)} en Steam "
                  f"(-{steam_best.cut}%, objetivo {euros(target)})")
            print(f"   {steam_verdict.summary()}")
            if steam_best.url:
                print(f"   {steam_best.url}")
        if ks and ks.keyshop_cents is not None and ks.keyshop_cents <= target:
            print(f"🔔 {p['name']}: {euros(ks.keyshop_cents)} en tiendas de claves "
                  f"(objetivo {euros(target)})")
            print(f"   {ks_verdict.summary()}")
            print(f"   {KEYSHOP_WARNING}")
            if ks.url:
                print(f"   {ks.url}")

        # Resumen completo (solo sin --quiet)
        if not args.quiet:
            print(f"{p['name']}  (objetivo {euros(target)})")
            if steam_best:
                cut = f" (-{steam_best.cut}%)" if steam_best.cut else ""
                print(f"   Steam (oficial):    {euros(steam_best.price_cents)}{cut}")
                print(f"      {steam_verdict.summary()}")
            else:
                print("   Steam (oficial):    sin precio")
            if clients.gg:
                if ks_verdict:
                    print(f"   Tiendas de claves:  {euros(ks.keyshop_cents)}")
                    print(f"      {ks_verdict.summary()}")
                else:
                    print("   Tiendas de claves:  sin precio")
            print()
    return 0


def describe_http_error(error: requests.RequestException, secrets: list[str]) -> str:
    """Mensaje de error claro: qué API falló, el código y su explicación.

    Nunca muestra la URL completa ni las claves (la de GG.deals va en la URL).
    """
    resp = getattr(error, "response", None)
    if resp is None:
        return f"Error de conexión: {type(error).__name__} (¿hay internet?)"
    url = str(getattr(resp, "url", "") or "")
    service = "GG.deals" if "gg.deals" in url else "IsThereAnyDeal"
    try:
        detail = resp.text or ""
    except Exception:
        detail = ""
    for secret in secrets:
        detail = detail.replace(secret, "***")
    detail = " ".join(detail.split())[:300]
    return f"Error de {service} ({resp.status_code}): {detail or 'sin detalles'}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vigia", description="Vigía de precios")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search", help="Buscar un juego por título")
    p.add_argument("title")
    p.set_defaults(func=cmd_search, needs_api=True)

    p = sub.add_parser("add", help="Vigilar un juego")
    p.add_argument("title")
    p.add_argument("target", type=parse_euros, help="Precio objetivo en euros, ej. 15 o 14,99")
    p.set_defaults(func=cmd_add, needs_api=True)

    p = sub.add_parser("list", help="Ver lo que vigilas")
    p.set_defaults(func=cmd_list, needs_api=False)

    p = sub.add_parser("remove", help="Dejar de vigilar")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_remove, needs_api=False)

    p = sub.add_parser("check", help="Comprobar precios ahora")
    p.add_argument("--quiet", action="store_true",
                   help="Solo imprime los avisos (para tareas automáticas)")
    p.set_defaults(func=cmd_check, needs_api=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows: que la consola acepte tildes y emojis
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    conn = db.connect(config.DB_PATH)
    try:
        clients = Clients()
        if args.needs_api:
            clients.itad = ItadClient(config.get_itad_key())
            gg_key = config.get_ggdeals_key()
            clients.gg = GgDealsClient(gg_key) if gg_key else None
        return args.func(args, conn, clients)
    except RuntimeError as e:
        print(f"Error: {e}")
        return 2
    except requests.RequestException as e:
        secrets = [k for k in (config.get_ggdeals_key(),) if k]
        print(describe_http_error(e, secrets))
        return 3
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
