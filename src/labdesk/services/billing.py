"""Pure billing math + promo-discount lookup (no Qt).

Extracted verbatim from the reception/receipts views so the exact arithmetic
(including each call site's rounding policy) can be unit-tested in isolation.
"""

from __future__ import annotations

import datetime
import sqlite3

from .. import db


def compute_bill_totals(
    items: list[dict],
    discount_pct: float,
    paid: float,
    *,
    round_to_paisa: bool,
) -> dict:
    """Compute the money breakdown for a bill.

    ``items`` is a list of dicts each carrying a ``"charge"`` key.

    Behaviour mirrors the two call sites exactly:

      * reception ``recompute()``  → ``round_to_paisa=False`` (net NOT rounded;
        subtotal is the raw sum).
      * receipts ``_EditReceiptDialog._net``/``_recompute`` → ``round_to_paisa=True``
        (subtotal rounded to 2 dp, net = ``round(max(0, sub - sub*pct/100), 2)``,
        due/change rounded to 2 dp).

    Returns ``{"subtotal","discount","net","paid","due","change"}``.
    """
    subtotal = sum(c["charge"] for c in items)
    disc = subtotal * discount_pct / 100.0
    net = max(0.0, subtotal - disc)
    if round_to_paisa:
        subtotal = round(subtotal, 2)
        net = round(max(0.0, subtotal - subtotal * discount_pct / 100.0), 2)
    due = max(0.0, net - paid)
    change = max(0.0, paid - net)
    if round_to_paisa:
        due = round(due, 2)
        change = round(change, 2)
    discount = subtotal - net
    return {
        "subtotal": subtotal,
        "discount": discount,
        "net": net,
        "paid": paid,
        "due": due,
        "change": change,
    }


def get_active_promo_discount(con: sqlite3.Connection) -> float:
    """Active special-day discount %, honouring the optional end date."""
    try:
        pct = float(db.get_setting(con, "promo_discount_pct", "0") or 0)
    except ValueError:
        pct = 0.0
    until = db.get_setting(con, "promo_until", "").strip()
    if until:
        try:
            if datetime.date.today() > datetime.date.fromisoformat(until):
                return 0.0
        except ValueError:
            pass
    return max(0.0, min(100.0, pct))
