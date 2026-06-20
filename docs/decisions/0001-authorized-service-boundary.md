# ADR 0001 — Privileged writes go through an authorized, audited service boundary

- Status: Accepted
- Date: 2026-06-16

## Context

The highest-stakes writes — bill creation, clinical result/culture release, and user
management — ran as inline multi-table SQL **inside Qt widgets**, with authorization
expressed only as the widget's button/visibility state. A service layer with
`require()` + audit existed, but only for the cheaper mutations (void/deliver/due).
So the invariant "all mutations are authorized at an audited boundary" was false for
the most important writes (a CWE-862/863 missing/incorrect-authorization defect, the
top finding of the audit).

## Decision

Every privileged write goes through a function in `src/labdesk/services/` that, in one
transaction:

1. calls `roles.require(actor_role, capability)` (raises `PermissionError` if denied),
2. performs the multi-table write,
3. calls `db.log_audit(...)`.

Qt widgets gather input, compute/validate, and render results; they pass plain data
(e.g. `BillDraft`) to the service and never run mutation SQL. `require()` is
authoritative; `can()`/`can_view_page()` remain UX-only.

## Consequences

- Authorization and audit are enforced regardless of the calling code path
  (defence-in-depth) and are unit-testable without Qt — each path has tests asserting
  *authz-deny writes nothing* and *committed multi-table state*.
- New capabilities added: `create_receipt`(2), `enter_results`(3), `finalize_results`(3),
  `edit_finalized_results`(5).
- A future CI guard (semgrep) should ban write-SQL in `ui/**` once all paths migrate;
  until then the rule is enforced by review + this ADR.
- Not a defence against a holder of the shared SQLCipher key editing the DB directly
  (see [ADR-adjacent] security-model.md and the Wave 5 hardening).
