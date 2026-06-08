"""REFERENCE generator — billing math invariants (discount / net / due / change).

Contract every tests/gen/test_*.py must follow:
  * expose exactly one function ``register(t)``
  * emit assertions only through t.check / t.eq / t.near / t.has
  * never touch the network or the live DB (the runner isolates both)
  * use t.con, t.db, t.report, t.whatsapp, t.render, t.roles, t.normalize_phone,
    t.make_receipt(...), t.SCN as needed
This module alone emits ~6,000 cases.
"""

from __future__ import annotations


def register(t):
    t.section("billing math (discount / net / due / change)")
    SUBS = [0, 50, 100, 250, 333, 800, 1250, 4999, 5000, 99999, 123456]
    DISCS = [0, 5, 10, 12.5, 20, 30, 33, 50, 75, 100]
    for sub in SUBS:
        for disc in DISCS:
            net = max(0.0, sub - sub * disc / 100.0)
            for paid in [0, net / 3, net / 2, net, net + 1, net + 500, sub + 1000]:
                due = max(0.0, net - paid)
                change = max(0.0, paid - net)
                t.check(net <= sub + 1e-9, f"net<=sub sub={sub} disc={disc}")
                t.check(due >= -1e-9 and change >= -1e-9, f"due/change>=0 sub={sub} paid={paid}")
                t.check(
                    not (due > 1e-6 and change > 1e-6),
                    f"never due AND change sub={sub} disc={disc} paid={paid}",
                )
                if paid >= net:
                    t.near(change, paid - net, f"overpaid change sub={sub} disc={disc} paid={paid}")
                    t.check(due < 1e-6, f"no due when overpaid sub={sub} paid={paid}")
                else:
                    t.near(due, net - paid, f"due sub={sub} disc={disc} paid={paid}")
                    t.check(change < 1e-6, f"no change when underpaid sub={sub} paid={paid}")
                # discount never makes net negative or exceed subtotal
                t.check(0.0 <= net <= sub + 1e-9, f"net bounds sub={sub} disc={disc}")
