from vigia import cli, db
from vigia.ggdeals import KeyshopPrice
from vigia.itad import Deal, Game


class FakeItad:
    """Cliente falso de IsThereAnyDeal: no se conecta a internet."""

    def __init__(self, steam_cents=2450):
        self.steam_cents = steam_cents
        self.last_shops = None

    def search(self, title, results=5):
        return [Game(id="id-1", title="Hades", type="game")]

    def steam_appids(self, ids):
        return {"id-1": 1145360}

    def history(self, game_id, country="ES", shops=None, since=None):
        from datetime import datetime, timedelta, timezone
        from vigia.analysis import PricePoint
        return [PricePoint(datetime.now(timezone.utc) - timedelta(days=300), 2450)]

    def prices(self, ids, country="ES", shops=None):
        self.last_shops = shops
        return {"id-1": [Deal("Steam", self.steam_cents, 2450, "EUR", 0,
                              "https://store.steampowered.com/app/1145360")]}


class FakeGg:
    def __init__(self, keyshop_cents=1199):
        self.keyshop_cents = keyshop_cents

    def prices(self, appids, region="es"):
        return {1145360: KeyshopPrice("Hades", "https://gg.deals/game/hades/",
                                      self.keyshop_cents, 750, 2450, "EUR")}


class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_parse_euros_accepts_comma():
    assert cli.parse_euros("14,99") == 1499
    assert cli.parse_euros("15") == 1500


def test_add_saves_steam_appid():
    conn = db.connect(":memory:")
    clients = cli.Clients(itad=FakeItad())
    cli.cmd_add(Args(title="hades", target=1500), conn, clients)
    assert db.list_products(conn)[0]["steam_appid"] == 1145360


def test_check_only_asks_steam_and_alerts_keyshop(capsys):
    conn = db.connect(":memory:")
    pid = db.add_product(conn, "Hades", 1500, itad_id="id-1", steam_appid=1145360)
    itad = FakeItad(steam_cents=2450)            # Steam por encima del objetivo
    clients = cli.Clients(itad=itad, gg=FakeGg(keyshop_cents=1199))

    cli.cmd_check(Args(quiet=True), conn, clients)

    out = capsys.readouterr().out
    assert itad.last_shops == [61]                       # solo Steam
    assert "posible chollo en tiendas de claves, 11,99 €" in out   # pista de keyshop
    assert "Steam KEY (no Account ni Gift)" in out       # lista de comprobación
    assert "lejos del mínimo histórico (7,50 €)" in out  # análisis de la oferta
    assert "en Steam" not in out                         # Steam no baja del objetivo
    trusts = [h["trust"] for h in db.price_history(conn, pid)]
    assert sorted(trusts) == ["keyshop", "official"]


def test_check_quiet_prints_nothing_when_no_alert(capsys):
    conn = db.connect(":memory:")
    db.add_product(conn, "Hades", 1000, itad_id="id-1", steam_appid=1145360)
    clients = cli.Clients(itad=FakeItad(2450), gg=FakeGg(1199))
    cli.cmd_check(Args(quiet=True), conn, clients)
    assert capsys.readouterr().out == ""                 # silencio = sin aviso


def test_check_fills_missing_appid_from_old_version():
    conn = db.connect(":memory:")
    pid = db.add_product(conn, "Hades", 1500, itad_id="id-1")   # sin appid (v0.1)
    cli.cmd_check(Args(quiet=True), conn, cli.Clients(itad=FakeItad(), gg=FakeGg()))
    assert db.list_products(conn)[0]["steam_appid"] == 1145360


def test_check_works_without_ggdeals_key(capsys):
    conn = db.connect(":memory:")
    db.add_product(conn, "Hades", 3000, itad_id="id-1", steam_appid=1145360)
    cli.cmd_check(Args(quiet=False), conn, cli.Clients(itad=FakeItad(2450), gg=None))
    out = capsys.readouterr().out
    assert "Sin GGDEALS_API_KEY" in out
    assert "24,50 € en Steam" in out


class FakeHttpResponse:
    def __init__(self, url, status_code, text):
        self.url, self.status_code, self.text = url, status_code, text


def test_describe_http_error_names_service_and_hides_key():
    import requests
    resp = FakeHttpResponse("https://api.gg.deals/v1/prices/by-steam-app-id/?key=SECRETO",
                            400, '{"success":false,"data":{"message":"Invalid key SECRETO"}}')
    err = requests.HTTPError(response=resp)
    msg = cli.describe_http_error(err, ["SECRETO"])
    assert msg.startswith("Error de GG.deals (400)")
    assert "Invalid key" in msg
    assert "SECRETO" not in msg


def test_describe_http_error_itad():
    import requests
    resp = FakeHttpResponse("https://api.isthereanydeal.com/games/prices/v3", 400, "bad shops")
    msg = cli.describe_http_error(requests.HTTPError(response=resp), [])
    assert msg == "Error de IsThereAnyDeal (400): bad shops"


def test_check_summary_shows_steam_analysis(capsys):
    conn = db.connect(":memory:")
    db.add_product(conn, "Hades", 1500, itad_id="id-1", steam_appid=1145360)
    cli.cmd_check(Args(quiet=False), conn, cli.Clients(itad=FakeItad(2450), gg=FakeGg(1199)))
    out = capsys.readouterr().out
    assert "Steam (oficial):    24,50 €" in out
    assert "mínimo histórico" in out


def test_keyshop_alerts_can_be_disabled(capsys, monkeypatch):
    monkeypatch.setenv("KEYSHOP_ALERTS", "off")
    conn = db.connect(":memory:")
    db.add_product(conn, "Hades", 1500, itad_id="id-1", steam_appid=1145360)
    cli.cmd_check(Args(quiet=True), conn, cli.Clients(itad=FakeItad(2450), gg=FakeGg(1199)))
    assert capsys.readouterr().out == ""      # Steam no baja y los keyshops están apagados
