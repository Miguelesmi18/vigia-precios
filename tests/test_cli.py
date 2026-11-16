from vigia import cli, db
from vigia.itad import Deal, Game


class FakeClient:
    """Cliente falso: no se conecta a internet."""

    def search(self, title, results=5):
        return [Game(id="id-1", title="Hades", type="game")]

    def prices(self, ids, country="ES"):
        return {"id-1": [
            Deal("Steam", 1249, 2499, "EUR", 50, "https://example.com"),
            Deal("GOG", 1499, 2499, "EUR", 40, None),
        ]}


class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_parse_euros_accepts_comma():
    assert cli.parse_euros("14,99") == 1499
    assert cli.parse_euros("15") == 1500


def test_check_alerts_and_saves_history(capsys):
    conn = db.connect(":memory:")
    pid = db.add_product(conn, "Hades", 1500, itad_id="id-1")

    cli.cmd_check(Args(quiet=True), conn, FakeClient())

    out = capsys.readouterr().out
    assert "Hades: 12,49 € en Steam" in out          # el aviso sale
    assert len(db.price_history(conn, pid)) == 2      # se guardaron 2 precios


def test_check_quiet_prints_nothing_when_no_alert(capsys):
    conn = db.connect(":memory:")
    db.add_product(conn, "Hades", 1000, itad_id="id-1")   # objetivo 10 €
    cli.cmd_check(Args(quiet=True), conn, FakeClient())
    assert capsys.readouterr().out == ""                  # silencio = sin aviso
