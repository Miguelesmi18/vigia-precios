"""Programa de comandos de Vigía de precios.

Juegos:            vigia search | add
Productos físicos: vigia shop | add-product
Comunes:           vigia list | remove | check | report
"""

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

from vigia import analysis, config, db, report, stores
from vigia.ggdeals import GgDealsClient
from vigia.itad import STEAM_SHOP_ID, ItadClient
from vigia.serpapi import SerpApiClient

KEYSHOP_LABEL = "Tiendas de claves (GG.deals)"
HISTORY_DAYS = 400   # días de historial de Steam que se piden para el análisis
KEYSHOP_CHECKLIST = ("Comprueba en el enlace: que sea Steam KEY (no Account ni Gift), "
                     "región EUROPE o GLOBAL, y tienda de confianza (Instant Gaming, Eneba...)")
SUSPICIOUS_TEXT = "⚠ PRECIO SOSPECHOSO: muy por debajo del resto, posible estafa o producto distinto"
MARKETPLACE_CHECKLIST = ("Comprueba el vendedor, la garantía en España y que el producto "
                         "sea nuevo antes de comprar")


@dataclass
class Clients:
    itad: ItadClient | None = None
    gg: GgDealsClient | None = None        # None si no hay clave de GG.deals
    serp: SerpApiClient | None = None      # None si no hay clave de SerpApi


def euros(cents: int | None) -> str:
    """1999 -> '19,99 €' (formato español)."""
    if cents is None:
        return "-"
    return f"{cents / 100:.2f} €".replace(".", ",")


def shipping_text(cents: int | None) -> str:
    if cents is None:
        return "envío no indicado"
    return "envío gratis" if cents == 0 else f"envío {euros(cents)}"


def parse_euros(text: str) -> int:
    """'19,99' o '19.99' -> 1999 céntimos."""
    value = float(text.replace(",", "."))
    if value <= 0:
        raise argparse.ArgumentTypeError("El precio tiene que ser mayor que 0.")
    return round(value * 100)


def should_alert(args, conn, product_id: int, kind: str, price_cents: int) -> bool:
    """Con --only-new solo se avisa si es la primera vez o si el precio ha bajado más.

    Así un producto que sigue barato no te escribe dos veces al día.
    """
    if not getattr(args, "only_new", False):
        return True
    last = db.last_alert_price(conn, product_id, kind)
    if last is not None and price_cents >= last:
        return False
    db.save_alert(conn, product_id, kind, price_cents)
    return True


def reset_alert(args, conn, product_id: int, kind: str) -> None:
    """El precio ya no está por debajo del objetivo: se olvida el aviso anterior."""
    if getattr(args, "only_new", False):
        db.clear_alert(conn, product_id, kind)


def require_serp(clients):
    if not clients.serp:
        raise RuntimeError("Falta SERPAPI_KEY en el .env (necesaria para productos físicos).")
    return clients.serp


# ---------------------------------------------------------------- juegos

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


# ---------------------------------------------------------------- productos físicos

def cmd_shop(args, conn, clients):
    """Explorar: busca en Google Shopping y muestra precio final y confianza. Gasta 1 búsqueda."""
    offers = require_serp(clients).shopping(args.query, country=config.COUNTRY,
                                            model=args.model)
    if not offers:
        print("Sin resultados nuevos (se descartan usados y reacondicionados).")
        return 1
    for o in offers[:args.limit]:
        print(f"{euros(o.total_cents):>10}  {o.shop}  [{stores.describe(o.shop, o.trust)}]")
        print(f"            {o.title[:70]}")
        print(f"            {euros(o.price_cents)} + {shipping_text(o.shipping_cents)}")
        if o.suspicious:
            print(f"            {SUSPICIOUS_TEXT}")
    print(f"\n(1 búsqueda de SerpApi usada; el plan gratuito da 250 al mes)")
    return 0


def cmd_add_product(args, conn, clients):
    query = args.query or args.name
    pid = db.add_physical(conn, args.name, args.target, query=query, model=args.model)
    model = f", modelo {args.model}" if args.model else ""
    print(f"Añadido #{pid}: {args.name} (aviso por debajo de {euros(args.target)}{model})")
    print(f"   Búsqueda: \"{query}\". Se consultará como máximo cada "
          f"{config.PHYSICAL_INTERVAL_HOURS:g} horas.")
    return 0


# ---------------------------------------------------------------- comunes

def cmd_list(args, conn, clients):
    products = db.list_products(conn)
    if not products:
        print("No vigilas nada todavía. Usa: vigia add \"juego\" 15  o  "
              "vigia add-product \"cafetera X\" 250")
        return 0
    for p in products:
        kind = "juego" if p["kind"] == "game" else "producto"
        extra = f"  [modelo {p['model']}]" if p["model"] else ""
        print(f"#{p['id']}  ({kind})  {p['name']}  -> objetivo "
              f"{euros(p['target_cents'])}{extra}")
    return 0


def cmd_report(args, conn, clients):
    """Resumen de los últimos días (lo usa la tarea semanal de Hermes)."""
    print(report.build_report(conn, days=args.days))
    return 0


def cmd_remove(args, conn, clients):
    if db.remove_product(conn, args.id):
        print(f"Eliminado #{args.id}.")
        return 0
    print(f"No existe el #{args.id}.")
    return 1


def cmd_check(args, conn, clients):
    """Comprueba juegos y productos físicos, guarda el historial y avisa."""
    products = db.list_products(conn)
    if not products:
        if not args.quiet:
            print("No vigilas nada todavía.")
        return 0
    games = [p for p in products if p["kind"] == "game" and p["itad_id"]]
    physical = [p for p in products if p["kind"] == "physical"]
    if games:
        check_games(args, conn, clients, games)
    if physical:
        check_physical(args, conn, clients, physical)
    return 0


def _fill_missing_appids(conn, clients, games):
    """Juegos añadidos con la versión 0.1 no tienen id de Steam: se busca ahora."""
    missing = [p for p in games if p["steam_appid"] is None]
    if not missing:
        return games
    found = clients.itad.steam_appids([p["itad_id"] for p in missing])
    for p in missing:
        if p["itad_id"] in found:
            db.set_steam_appid(conn, p["id"], found[p["itad_id"]])
    return [p for p in db.list_products(conn) if p["kind"] == "game" and p["itad_id"]]


def check_games(args, conn, clients, games):
    """Steam (vía IsThereAnyDeal) y tiendas de claves (vía GG.deals)."""
    games = _fill_missing_appids(conn, clients, games)
    checked_at = db.now_iso()

    # 1) Steam, a través de IsThereAnyDeal (solo la tienda 61)
    steam = clients.itad.prices([p["itad_id"] for p in games],
                                country=config.COUNTRY, shops=[STEAM_SHOP_ID])

    # 2) Tiendas de claves, a través de GG.deals (si hay clave)
    keyshops = {}
    if clients.gg:
        appids = [p["steam_appid"] for p in games if p["steam_appid"]]
        if appids:
            keyshops = clients.gg.prices(appids, region=config.COUNTRY)
    elif not args.quiet:
        print("(Sin GGDEALS_API_KEY en .env: solo se consulta Steam)\n")

    for p in games:
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
            if should_alert(args, conn, p["id"], "steam", steam_best.price_cents):
                print(f"🔔 {p['name']}: {euros(steam_best.price_cents)} en Steam "
                      f"(-{steam_best.cut}%, objetivo {euros(target)})")
                print(f"   {steam_verdict.summary()}")
                if steam_best.url:
                    print(f"   {steam_best.url}")
        else:
            reset_alert(args, conn, p["id"], "steam")
        if (ks and ks.keyshop_cents is not None and ks.keyshop_cents <= target
                and config.keyshop_alerts_enabled()):
            # Es una PISTA, no una compra segura: GG.deals no dice qué tienda es
            # ni si es clave, regalo o cuenta.
            if should_alert(args, conn, p["id"], "keyshop", ks.keyshop_cents):
                print(f"🔎 {p['name']}: posible chollo en tiendas de claves, "
                      f"{euros(ks.keyshop_cents)} (objetivo {euros(target)})")
                print(f"   {ks_verdict.summary()}")
                print(f"   {KEYSHOP_CHECKLIST}")
                if ks.url:
                    print(f"   {ks.url}")
        else:
            reset_alert(args, conn, p["id"], "keyshop")

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


def _due(conn, product, force: bool) -> bool:
    """¿Toca consultar este producto? (ahorra búsquedas de SerpApi)."""
    if force:
        return True
    last = db.last_checked(conn, product["id"])
    if not last:
        return True
    elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(last)
    return elapsed >= timedelta(hours=config.PHYSICAL_INTERVAL_HOURS)


def check_physical(args, conn, clients, products):
    """Productos físicos vía Google Shopping (SerpApi)."""
    if not clients.serp:
        if not args.quiet:
            print("(Sin SERPAPI_KEY en .env: no se comprueban productos físicos)\n")
        return
    trusted = (stores.OFFICIAL, stores.RETAILER)

    for p in products:
        if not _due(conn, p, getattr(args, "force", False)):
            if not args.quiet:
                print(f"{p['name']}: comprobado hace menos de "
                      f"{config.PHYSICAL_INTERVAL_HOURS:g} h (usa --force para forzar)\n")
            continue

        target = p["target_cents"]
        offers = clients.serp.shopping(p["query"], country=config.COUNTRY, model=p["model"])
        checked_at = db.now_iso()

        # Guardar la oferta más barata de cada tienda
        best_per_shop = {}
        for o in offers:                   # vienen ordenadas de más barata a más cara
            best_per_shop.setdefault(o.shop, o)
        for o in best_per_shop.values():
            db.save_price(conn, p["id"], o.shop, o.total_cents, None, "EUR", o.link,
                          checked_at=checked_at, trust=o.trust,
                          shipping_cents=o.shipping_cents)

        # Las ofertas sospechosamente baratas se guardan, pero nunca generan aviso
        best_trusted = next((o for o in offers
                             if stores.is_trusted(o.trust) and not o.suspicious), None)
        best_other = next((o for o in offers
                           if not stores.is_trusted(o.trust) and not o.suspicious), None)

        # Detector de ofertas falsas con TU historial (tiendas de confianza)
        verdict = None
        if best_trusted:
            rows = db.best_price_per_check(conn, p["id"], trusted)
            points = [analysis.PricePoint(datetime.fromisoformat(r["checked_at"]),
                                          r["price_cents"]) for r in rows]
            # cut=1: se analiza como posible rebaja (Google no siempre da el descuento)
            verdict = analysis.analyze(points, best_trusted.total_cents, 1,
                                       datetime.now(timezone.utc))

        # Avisos
        if best_trusted and best_trusted.total_cents <= target:
            if should_alert(args, conn, p["id"], "trusted", best_trusted.total_cents):
                print(f"🔔 {p['name']}: {euros(best_trusted.total_cents)} en {best_trusted.shop} "
                      f"({shipping_text(best_trusted.shipping_cents)}, objetivo {euros(target)})")
                print(f"   {verdict.summary()}")
                if best_trusted.link:
                    print(f"   {best_trusted.link}")
        else:
            reset_alert(args, conn, p["id"], "trusted")
        if (best_other and best_other.total_cents <= target
                and (not best_trusted or best_other.total_cents < best_trusted.total_cents)):
            if should_alert(args, conn, p["id"], "other", best_other.total_cents):
                print(f"🔎 {p['name']}: {euros(best_other.total_cents)} en {best_other.shop} "
                      f"[{stores.describe(best_other.shop, best_other.trust)}] "
                      f"(objetivo {euros(target)})")
                print(f"   {MARKETPLACE_CHECKLIST}")
                if best_other.link:
                    print(f"   {best_other.link}")
        else:
            reset_alert(args, conn, p["id"], "other")

        # Resumen
        if not args.quiet:
            print(f"{p['name']}  (objetivo {euros(target)})")
            if not offers:
                print("   Sin resultados (revisa la búsqueda o el --model)")
            for o in list(best_per_shop.values())[:5]:
                warn = "  ⚠ sospechoso" if o.suspicious else ""
                print(f"   {euros(o.total_cents):>10}  {o.shop}  [{stores.describe(o.shop, o.trust)}]  "
                      f"({shipping_text(o.shipping_cents)}){warn}")
            if verdict:
                print(f"      {verdict.summary()}")
            print()


def describe_http_error(error: requests.RequestException, secrets: list[str]) -> str:
    """Mensaje de error claro: qué API falló, el código y su explicación.

    Nunca muestra la URL completa ni las claves (GG.deals y SerpApi la llevan en la URL).
    """
    resp = getattr(error, "response", None)
    if resp is None:
        return f"Error de conexión: {type(error).__name__} (¿hay internet?)"
    url = str(getattr(resp, "url", "") or "")
    if "gg.deals" in url:
        service = "GG.deals"
    elif "serpapi" in url:
        service = "SerpApi"
    else:
        service = "IsThereAnyDeal"
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

    p = sub.add_parser("shop", help="Explorar productos en Google Shopping (gasta 1 búsqueda)")
    p.add_argument("query", help="Qué buscar, ej. \"cafetera superautomatica\"")
    p.add_argument("--model", help="Código de modelo que debe aparecer en el título")
    p.add_argument("--limit", type=int, default=10, help="Resultados a mostrar")
    p.set_defaults(func=cmd_shop, needs_api=True)

    p = sub.add_parser("add-product", help="Vigilar un producto físico")
    p.add_argument("name", help="Nombre para reconocerlo, ej. \"Cafetera De'Longhi\"")
    p.add_argument("target", type=parse_euros, help="Precio objetivo en euros")
    p.add_argument("--query", help="Texto de búsqueda (por defecto, el nombre)")
    p.add_argument("--model", help="Código de modelo obligatorio, ej. ECAM22.110")
    p.set_defaults(func=cmd_add_product, needs_api=False)

    p = sub.add_parser("list", help="Ver lo que vigilas")
    p.set_defaults(func=cmd_list, needs_api=False)

    p = sub.add_parser("report", help="Resumen de precios de los últimos días")
    p.add_argument("--days", type=int, default=7, help="Días a resumir (por defecto 7)")
    p.set_defaults(func=cmd_report, needs_api=False)

    p = sub.add_parser("remove", help="Dejar de vigilar")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_remove, needs_api=False)

    p = sub.add_parser("check", help="Comprobar precios ahora")
    p.add_argument("--quiet", action="store_true",
                   help="Solo imprime los avisos (para tareas automáticas)")
    p.add_argument("--force", action="store_true",
                   help="Consultar productos físicos aunque se hayan mirado hace poco")
    p.add_argument("--only-new", action="store_true",
                   help="Avisar solo de ofertas nuevas o más baratas que el último aviso")
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
            serp_key = config.get_serpapi_key()
            clients.serp = SerpApiClient(serp_key) if serp_key else None
        return args.func(args, conn, clients)
    except RuntimeError as e:
        print(f"Error: {e}")
        return 2
    except requests.RequestException as e:
        secrets = [k for k in (config.get_ggdeals_key(), config.get_serpapi_key()) if k]
        print(describe_http_error(e, secrets))
        return 3
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
