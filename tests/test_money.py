"""Wave 4b — exact integer-paisa money module.

Pins the conversion + half-up policy and the invariants the float code can't
guarantee (no 0.1+0.2 drift; net/due/change never negative; due*change == 0). Uses
deterministic loops as stdlib property tests (Hypothesis is not a project dep).
"""

from __future__ import annotations

import pytest

from labdesk.application.money import (
    apply_discount,
    compute_bill_totals_paisa,
    format_paisa,
    to_paisa,
    to_rupees,
)


@pytest.mark.parametrize(
    "rupees,paisa",
    [
        (0, 0),
        (1, 100),
        (0.1, 10),
        (0.2, 20),
        (0.01, 1),
        (12.34, 1234),
        (999.99, 99999),
        ("500", 50000),
        ("0.005", 1),
        (2.675, 268),  # half-up, not 267
    ],
)
def test_to_paisa_half_up(rupees, paisa):
    assert to_paisa(rupees) == paisa


def test_no_float_drift_on_sum():
    # The canonical float-drift case: 0.1 + 0.2 == 0.30000000000000004 in float.
    assert to_paisa(0.1) + to_paisa(0.2) == to_paisa(0.3) == 30


def test_round_trip_paisa_rupees():
    for p in range(0, 200000, 7):
        assert to_paisa(to_rupees(p)) == p


def test_format_paisa():
    assert format_paisa(0) == "0.00"
    assert format_paisa(5) == "0.05"
    assert format_paisa(1234) == "12.34"
    assert format_paisa(100000) == "1000.00"
    assert format_paisa(-250) == "-2.50"


def test_apply_discount_half_up_and_floored():
    assert apply_discount(50000, 10) == 45000  # 10% of 500.00
    assert apply_discount(50000, 0) == 50000
    assert apply_discount(50000, 100) == 0
    assert apply_discount(50000, 150) == 0  # floored, never negative
    # 33% of 100.01 = 33.0033 -> 3300 paisa (half-up), net = 6701
    assert apply_discount(10001, 33) == 10001 - 3300


def test_compute_bill_totals_paisa_matches_breakdown():
    r = compute_bill_totals_paisa([10000, 25000], 10, 30000)
    assert r["subtotal"] == 35000
    assert r["net"] == 31500
    assert r["discount"] == 3500
    assert r["due"] == 1500
    assert r["change"] == 0


def test_compute_bill_totals_paisa_overpay():
    r = compute_bill_totals_paisa([50000], 0, 60000)
    assert r["due"] == 0
    assert r["change"] == 10000


def test_invariants_hold_across_many_inputs():
    # Property-style: over a grid of inputs, the money invariants always hold.
    for sub in range(0, 200000, 5000):
        for pct in (0, 5, 10, 17, 50, 100):
            for paid in (0, sub // 2, sub, sub + 10000):
                r = compute_bill_totals_paisa([sub], pct, paid)
                assert r["net"] >= 0
                assert r["due"] >= 0 and r["change"] >= 0
                assert r["due"] == 0 or r["change"] == 0  # never owe AND get change
                assert r["subtotal"] == r["net"] + r["discount"]
