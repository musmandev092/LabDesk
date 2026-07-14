"""Pure billing math + promo-discount lookup (no Qt). Money is computed exactly in
integer paisa (see application.money) — no floating-point drift."""

from __future__ import annotations

import datetime
from typing import cast

from .. import db
from ..db import sqlite3
from . import money


def compute_bill_totals(
    items: list[dict[str, object]], discount_pct: float, paid: float
) -> dict[str, float]:
    """Compute the money breakdown for a bill, exactly, via integer paisa. `items`
    is a list of dicts each carrying a "charge" key."""
    charges_paisa = [money.to_paisa(cast("float", c["charge"])) for c in items]
    totals_paisa = money.compute_bill_totals_paisa(
        charges_paisa, discount_pct, money.to_paisa(paid)
    )
    return {key: money.to_rupees(val) for key, val in totals_paisa.items()}


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
