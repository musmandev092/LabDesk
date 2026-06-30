# Architecture

A single-process PySide6 (Qt) desktop app over an encrypted SQLCipher database. It
runs on a lab's own PCs — there is no server tier.

## Layers & the dependency rule

```
presentation/  + app.py     Qt widgets, dialogs, composition root
      │ calls
application/                 authorize + audit + transaction (write services + money)
      │ uses
db/   ── render/ report/     encrypted SQLite          PDF / print generation
licensing/                  self-contained (depends only on db.paths today)
```

**Enforced in CI by import-linter** (`pyproject.toml` `[tool.importlinter]`):
`db`, `render`, `report`, `application`, `licensing` must **not** import
`presentation` or `app`; `db` is the lowest layer; `licensing` must not reach up.
A violation fails the build.

## The service boundary (the key rule)

**Every privileged write goes through an `application/` function that calls
`require(actor_role, capability)` and `log_audit(...)` in one transaction.** Qt
widgets gather/validate input and render output; they never run mutation SQL. The
button's enabled state is UX only — `require()` (in `roles.py`) is the authoritative
gate, enforced regardless of the calling path. See [ADR 0001](./decisions/0001-authorized-service-boundary.md).

| Action | Service | Capability |
|--------|---------|------------|
| Create a bill | `application.receipts.create_receipt` | `create_receipt` |
| Void / deliver | `application.receipts.void_receipt` / `mark_receipt_delivered` | `void_receipt` / `deliver_report` |
| Receive a due | `db.receive_due` | `receive_payment` |
| Release results / save culture | `application.results.*` | `finalize_results` |
| Create / disable / reset user | `application.users.*` | `manage_users` |

Example — `ReceptionPage.save()` builds a `BillDraft` and calls
`create_receipt(con, draft, actor_username=, actor_role=)`, which checks `require`,
then (in one transaction) upserts the patient, inserts the receipt + items + ledger
income, and writes the audit rows; the view then prints / WhatsApps / clears.

## Report rendering by category

`catalog_render.classify()` (pure, no Qt/DB) maps each test to a render category —
`numeric_tabular`, `qualitative`, `blood_bank`, `descriptive`, `obstetric`, `culture`
— from its parameters/head/name, at **render time** (no migration needed); a non-NULL
`tests.render_category` overrides it. `render/report_doc.py` dispatches to a
per-category drawer + shared impression block, and the worklist entry screen picks
matching input widgets for the same category.

## Composition root

`app.py` (`run` / `run_cli`): auto-scales the UI to the screen, enforces the license,
unlocks the DB, runs first-run/restore, then builds the main window. `python -m
labdesk` is the dev entry point.
