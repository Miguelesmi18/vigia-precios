"""Tests del detector de ofertas falsas con historiales inventados."""

from datetime import datetime, timedelta, timezone

from vigia.analysis import (FAKE, GOOD, NORMAL, UNKNOWN, PricePoint, analyze,
                            compare_to_low)

NOW = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)   # "Black Friday"


def days_ago(n):
    return NOW - timedelta(days=n)


def history(*pairs):
    """history((200, 2499), (5, 1249)) = 24,99 € hace 200 días, 12,49 € hace 5."""
    return [PricePoint(days_ago(d), cents) for d, cents in pairs]


def test_genuine_sale_at_historic_low():
    points = history((300, 2499), (5, 1249))
    v = analyze(points, current_cents=1249, cut=50, now=NOW)
    assert v.level == GOOD
    assert "mínimo histórico" in v.summary()


def test_inflated_price_before_black_friday_is_fake():
    # Siempre 19,99 €; el 10 de noviembre sube a 29,99 €; el 25 "rebaja" a 19,99 €
    points = history((300, 1999), (18, 2999), (3, 1999))
    v = analyze(points, current_cents=1999, cut=33, now=NOW)
    assert v.level == FAKE
    assert "subieron el precio de 19,99 € a 29,99 €" in v.summary()


def test_discount_that_was_cheaper_last_month_is_fake():
    # Hace 20 días ya estuvo a 9,99 €; ahora la "oferta" es 14,99 €
    points = history((300, 2499), (20, 999), (15, 2499), (2, 1499))
    v = analyze(points, current_cents=1499, cut=40, now=NOW)
    assert v.level == FAKE
    assert "ya costaba 9,99 €" in v.summary()


def test_short_history_is_not_judged_as_fake():
    points = history((10, 2499), (2, 1249))
    v = analyze(points, current_cents=1249, cut=50, now=NOW)
    assert v.level != FAKE
    assert "menos de 30 días" in v.summary()


def test_full_price_far_from_low_is_normal():
    points = history((300, 2499), (200, 999), (190, 2499))
    v = analyze(points, current_cents=2499, cut=0, now=NOW)
    assert v.level == NORMAL
    assert "lejos del mínimo histórico (9,99 €)" in v.summary()


def test_no_history():
    assert analyze([], 1000, 0, NOW).level == UNKNOWN


def test_keyshop_compare_to_low():
    assert compare_to_low(500, 490).level == GOOD
    assert compare_to_low(847, 490).level == NORMAL
    assert "lejos" in compare_to_low(847, 490).summary()
    assert compare_to_low(847, None).level == UNKNOWN


def test_one_day_of_history_is_not_a_historic_low():
    """Primera consulta de un producto: no se puede decir que sea mínimo histórico."""
    points = [PricePoint(NOW - timedelta(hours=1), 27990)]
    v = analyze(points, current_cents=27990, cut=1, now=NOW)
    assert v.level == UNKNOWN
    assert "historial" in v.summary()
    assert "mínimo histórico" not in v.summary()


def test_full_price_never_discounted_is_not_a_good_offer():
    """Juego en reserva siempre a 69,99 €: es su precio normal, no una oferta."""
    points = history((60, 6999), (20, 6999))
    v = analyze(points, current_cents=6999, cut=0, now=NOW)
    assert v.level == NORMAL
    assert "nunca ha estado más barato" in v.summary()
