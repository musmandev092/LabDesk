# ADR 0001 — Privileged writes go through an authorized, audited service boundary

- Status: Accepted
- Date: 2026-06-16

## Context

The highest-stakes writes — bill creation, result/culture release, user management —
ran as inline multi-table SQL **inside Qt widgets**, with authorization expressed only
as widget button/visibility state. So the invariant "all mutations are authorized at
an audited boundary" was false for the most important writes (a CWE-862/863
missing/incorrect-authorization defect — the top audit finding).

## Decision

Every privileged write goes through a function in `src/labdesk/application/` that, in
one transaction: (1) calls `roles.require(actor_role, capability)` (raises
`PermissionError` if denied); (2) performs the multi-table write; (3) calls
`db.log_audit(...)`. Qt widgets gather/validate input and render results, pass plain
data (e.g. `BillDraft`) to the service, and never run mutation SQL. `require()` is
authoritative; `can()` / `can_view_page()` stay UX-only.

## Consequences

- Authorization + audit hold regardless of the calling path, and are unit-testable
  without Qt (each path asserts *deny writes nothing* and *committed multi-table state*).
- Capabilities: `create_receipt`(2), `receive_payment`(2), `enter_results`(3),
  `finalize_results`(3), `void_receipt`(4), `record_expense`(4),
  `edit_finalized_results`(5), `manage_users`(5).
- A future CI guard should ban write-SQL in `presentation/**`; until then it's enforced
  by review + this ADR.
- Not a defence against a holder of the shared SQLCipher key editing the DB directly
  (see [security-model.md](../security-model.md), Wave 5 hardening).
