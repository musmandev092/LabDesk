# ADR 0002 — Money is integer paisa, not floating-point rupees

- Status: Accepted (foundation landed; column cutover pending)
- Date: 2026-06-16

## Context

Money is stored in SQLite `REAL` (float) columns and computed with float arithmetic.
Floating-point cannot represent most decimal currency values exactly
(`0.1 + 0.2 == 0.30000000000000004`), so totals, discounts, and due/change can drift
by sub-cent amounts and disagree across call sites — unacceptable for financial
records. The codebase also had two different rounding policies at the two billing call
sites.

## Decision

Represent and compute money as **integer minor units (paisa)**, 1 rupee = 100 paisa,
with a single **half-up** rounding policy (`Decimal` `ROUND_HALF_UP`, matching cashier
expectation, unlike Python's banker's `round`). The canonical implementation is
`src/labdesk/services/money.py` (`to_paisa` / `to_rupees` / `format_paisa` /
`apply_discount` / `compute_bill_totals_paisa`).

## Consequences

- `services/money.py` is exact and fully tested (incl. property-style invariants:
  net/due/change ≥ 0, `due*change == 0`, `subtotal == net + discount`).
- The DB cutover (add `*_paisa` INTEGER columns additively → backfill with
  `ROUND(real*100)` → move reads/writes onto paisa behind the Wave-1 billing
  characterization tests → finally drop the `REAL` columns) is a **financial data
  migration** and is performed as a separate, supervised step. Old binaries keep
  reading the `REAL` columns until the final drop, preserving DB compatibility.
- New money math should use `services/money.py` rather than float arithmetic.
