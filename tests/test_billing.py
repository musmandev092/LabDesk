"""Characterization tests for services/billing.py — money math + promo lookup.

These PIN the current behaviour (including the float arithmetic and the two distinct
rounding policies of the two call sites) so the Wave-4 money→integer-paisa cutover is
provably behaviour-preserving. They assert what the code does TODAY, warts included.
"""

from __future__ import annotations

import datetime

from labdesk import db as dbpkg
from labdesk.application.billing import compute_bill_totals, get_active_promo_discount


def _items(*charges):
    return [{"charge": c} for c in charges]


# --------------------------------------------------------------------------
# compute_bill_totals — pure, no DB
# --------------------------------------------------------------------------


def test_no_discount_exact_payment():
    r = compute_bill_totals(_items(1000.0), 0.0, 1000.0)
    assert r == {
        "subtotal": 1000.0,
        "discount": 0.0,
        "net": 1000.0,
        "paid": 1000.0,
        "due": 0.0,
        "change": 0.0,
    }


def test_percentage_discount_unpaid():
    r = compute_bill_totals(_items(1000.0), 10.0, 0.0)
    assert r["net"] == 900.0
    assert r["discount"] == 100.0
    assert r["due"] == 900.0
    assert r["change"] == 0.0


def test_overpayment_yields_change_no_due():
    r = compute_bill_totals(_items(900.0), 0.0, 1000.0)
    assert r["due"] == 0.0
    assert r["change"] == 100.0


def test_no_float_drift_subtotal_is_exact():
    # Wave 4b: the old float path returned 0.1 + 0.2 == 0.30000000000000004 here; the
    # integer-paisa computation is exact.
    r = compute_bill_totals(_items(0.1, 0.2), 0.0, 0.0)
    assert r["subtotal"] == 0.3
    assert r["net"] == 0.3


def test_full_discount_zeroes_net():
    r = compute_bill_totals(_items(1000.0), 100.0, 0.0)
    assert r["net"] == 0.0
    assert r["discount"] == 1000.0
    assert r["due"] == 0.0


def test_over_100_percent_discount_clamps_net_to_zero_not_negative():
    # compute_bill_totals itself does NOT clamp the pct; net is floored at 0.
    r = compute_bill_totals(_items(1000.0), 150.0, 0.0)
    assert r["net"] == 0.0
    assert r["discount"] == 1000.0  # subtotal - net


def test_rounded_due_and_change_are_two_dp():
    r = compute_bill_totals(_items(999.999), 0.0, 100.0)
    assert r["subtotal"] == 1000.0
    assert r["due"] == 900.0
    assert r["change"] == 0.0


def test_empty_items_is_all_zero():
    r = compute_bill_totals([], 25.0, 0.0)
    assert r["subtotal"] == 0.0 and r["net"] == 0.0 and r["due"] == 0.0


# --------------------------------------------------------------------------
# get_active_promo_discount — reads settings off a live con
# --------------------------------------------------------------------------


def test_promo_default_is_zero(con):
    assert get_active_promo_discount(con) == 0.0


def test_promo_simple_pct(con):
    dbpkg.set_setting(con, "promo_discount_pct", "15")
    assert get_active_promo_discount(con) == 15.0


def test_promo_pct_is_clamped_high_and_low(con):
    dbpkg.set_setting(con, "promo_discount_pct", "150")
    assert get_active_promo_discount(con) == 100.0
    dbpkg.set_setting(con, "promo_discount_pct", "-5")
    assert get_active_promo_discount(con) == 0.0


def test_promo_invalid_pct_string_is_zero(con):
    dbpkg.set_setting(con, "promo_discount_pct", "abc")
    assert get_active_promo_discount(con) == 0.0


def test_promo_expired_until_returns_zero(con):
    dbpkg.set_setting(con, "promo_discount_pct", "20")
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    dbpkg.set_setting(con, "promo_until", yesterday)
    assert get_active_promo_discount(con) == 0.0


def test_promo_future_until_keeps_pct(con):
    dbpkg.set_setting(con, "promo_discount_pct", "20")
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    dbpkg.set_setting(con, "promo_until", tomorrow)
    assert get_active_promo_discount(con) == 20.0


def test_promo_malformed_until_is_ignored(con):
    dbpkg.set_setting(con, "promo_discount_pct", "20")
    dbpkg.set_setting(con, "promo_until", "not-a-date")
    assert get_active_promo_discount(con) == 20.0
