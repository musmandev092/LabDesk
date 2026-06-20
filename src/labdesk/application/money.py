"""Money as integer minor units (paisa). 1 rupee = 100 paisa.

Floating-point currency drifts (``0.1 + 0.2 != 0.3``); storing and operating on
integer paisa is exact. This is the canonical conversion + rounding the codebase
migrates billing onto, off the REAL columns (DB-review / data-integrity finding).

One rounding policy everywhere: **half-up** (``Decimal`` ROUND_HALF_UP), which is
what a human cashier expects (2.5 → 3), unlike Python's banker's ``round``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def to_paisa(rupees: float | str | Decimal) -> int:
    """Convert a rupee amount to integer paisa, rounded half-up.

    Accepts float/str/Decimal. ``str(rupees)`` is used so a float like ``0.1`` is
    taken at its decimal face value rather than its binary expansion."""
    cents = (Decimal(str(rupees)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def to_rupees(paisa: int) -> float:
    """Convert integer paisa back to a rupee float (for display/legacy REAL writes)."""
    return int(paisa) / 100.0


def format_paisa(paisa: int) -> str:
    """Render paisa as a fixed 2-dp rupee string, e.g. ``123456`` → ``'1234.56'``."""
    sign = "-" if paisa < 0 else ""
    p = abs(int(paisa))
    return f"{sign}{p // 100}.{p % 100:02d}"


def apply_discount(subtotal_paisa: int, discount_pct: float | str | Decimal) -> int:
    """Net after a percentage discount, in paisa, floored at zero.

    ``net = subtotal - round_half_up(subtotal * pct / 100)``. The percentage is NOT
    clamped here (callers clamp the promo separately); a pct ≥ 100 floors net at 0."""
    disc = (
        Decimal(int(subtotal_paisa)) * Decimal(str(discount_pct)) / Decimal(100)
    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return max(0, int(subtotal_paisa) - int(disc))


def compute_bill_totals_paisa(
    item_charges_paisa: list[int], discount_pct: float | str | Decimal, paid_paisa: int
) -> dict[str, int]:
    """Exact integer-paisa equivalent of application.billing.compute_bill_totals.

    Returns ``{"subtotal","discount","net","paid","due","change"}`` all in paisa. No
    floating drift: the subtotal is an exact sum and the discount is the only rounded
    quantity (half-up)."""
    subtotal = sum(int(c) for c in item_charges_paisa)
    net = apply_discount(subtotal, discount_pct)
    discount = subtotal - net
    due = max(0, net - int(paid_paisa))
    change = max(0, int(paid_paisa) - net)
    return {
        "subtotal": subtotal,
        "discount": discount,
        "net": net,
        "paid": int(paid_paisa),
        "due": due,
        "change": change,
    }
