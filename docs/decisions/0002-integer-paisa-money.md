# ADR 0002 — Money is integer paisa, not floating-point rupees

- Status: Accepted (paisa twins live alongside REAL; final REAL drop pending)
- Date: 2026-06-16

## Context

Money was stored in SQLite `REAL` (float) and computed with float arithmetic. Floats
can't represent most decimal currency exactly (`0.1 + 0.2 != 0.3`), so totals,
discounts and due/change drift sub-cent and disagree across call sites —
unacceptable for financial records — and the two billing call sites even rounded
differently.

## Decision

Represent and compute money as **integer paisa** (1 rupee = 100 paisa) with a single
**half-up** policy (`Decimal` `ROUND_HALF_UP`, matching cashier expectation, unlike
Python's banker's `round`). Canonical implementation: `src/labdesk/application/money.py`
(`to_paisa` / `to_rupees` / `format_paisa` / `apply_discount` / `compute_bill_totals`).

## Consequences

- `application/money.py` is exact and fully tested (invariants: net/due/change ≥ 0,
  `due*change == 0`, `subtotal == net + discount`).
- DB cutover is staged: `*_paisa` INTEGER columns added additively and **dual-written**
  alongside the `REAL` columns today; the final step (move all reads onto paisa, drop
  the `REAL` columns) is a supervised financial migration, tracked in
  [`../DEBT.md`](../DEBT.md). Old binaries keep reading `REAL` until that drop.
- New money math uses `application/money.py`, not float arithmetic.
