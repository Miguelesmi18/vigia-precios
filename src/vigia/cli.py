"""Programa de comandos: vigia search | add | list | remove | check."""

import argparse
import sqlite3
import sys

import requests

from vigia import config, db
from vigia.itad import ItadClient


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


def cmd_search(args, conn, client):
    games = client.search(args.title)
    if not games:
        print("No he encontrado ningún juego con ese título.")
        return 1
    for i, g in enumerate(games, start=1):
        print(f"{i}. {g.title}  [{g.type or '?'}]")
    return 0


def cmd_add(args, conn, client):
    games = client.search(args.title, results=1)
    if not games:
        print("No he encontrado ese juego. Prueba con 'vigia search'.")
        return 1
    game = games[0]
    try:
        pid = db.add_product(conn, game.title, args.target, itad_id=game.id)
    except sqlite3.IntegrityError:  # ya estaba en la lista
        print(f"'{game.title}' ya estaba en la lista.")
        return 1
    print(f"Añadido #{pid}: {game.title} (aviso por debajo de {euros(args.target)})")
    return 0


def cmd_list(args, conn, client):
    products = db.list_products(conn)
    if not products:
        print("No vigilas nada todavía. Usa: vigia add \"titulo\" 15")
        return 0
    for p in products:
        print(f"#{p['id']}  {p['name']}  -> objetivo {euros(p['target_cents'])}")
    return 0


def cmd_remove(args, conn, client):
    if db.remove_product(conn, args.id):
        print(f"Eliminado #{args.id}.")
        return 0
    print(f"No existe el #{args.id}.")
    return 1


def cmd_check(args, conn, client):
    """Consulta precios, los guarda en el historial y avisa si bajan del objetivo."""
    products = [p for p in db.list_products(conn) if p["itad_id"]]
    if not products:
        if not args.quiet:
            print("No hay juegos que comprobar.")
        return 0

    all_deals = client.prices([p["itad_id"] for p in products], country=config.COUNTRY)
    checked_at = db.now_iso()

    for p in products:
        deals = all_deals.get(p["itad_id"], [])
        for d in deals:
            db.save_price(conn, p["id"], d.shop, d.price_cents, d.regular_cents,
                          d.currency, d.url, checked_at=checked_at)
        if not deals:
            if not args.quiet:
                print(f"{p['name']}: sin precios ahora mismo.")
            continue

        best = min(deals, key=lambda d: d.price_cents)
        below = best.price_cents <= p["target_cents"]
        if below:
            print(f"🔔 {p['name']}: {euros(best.price_cents)} en {best.shop} "
                  f"(-{best.cut}%, objetivo {euros(p['target_cents'])})")
            if best.url:
                print(f"   {best.url}")
        elif not args.quiet:
            print(f"{p['name']}: mejor precio {euros(best.price_cents)} en "
                  f"{best.shop} (objetivo {euros(p['target_cents'])})")
    return 0


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
        client = ItadClient(config.get_itad_key()) if args.needs_api else None
        return args.func(args, conn, client)
    except RuntimeError as e:
        print(f"Error: {e}")
        return 2
    except requests.RequestException as e:
        print(f"Error de conexión con la API: {e}")
        return 3
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
