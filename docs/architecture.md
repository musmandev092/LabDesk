# Architecture

LabDesk is a single-process PySide6 (Qt) desktop app over an encrypted SQLCipher
SQLite database. It runs on a lab's own PCs; there is no server tier.

## Layers and the dependency rule

```
            ┌─────────────────────────────────────────┐
            │  presentation  (src/labdesk/ui/, app.py) │  Qt widgets, dialogs
            └───────────────┬─────────────────────────┘
                            │ calls
            ┌───────────────▼─────────────────────────┐
            │  application/services (src/labdesk/      │  authorize + audit + tx
            │  services/: receipts, results, users,    │
            │  money, billing)                         │
            └───────────────┬─────────────────────────┘
                            │ uses
   ┌────────────────────────▼───────────┐   ┌──────────────────────────┐
   │  infrastructure (src/labdesk/db/)  │   │  render / report          │
   │  connection, schema, crypto, audit │   │  (PDF/print generation)   │
   └────────────────────────────────────┘   └──────────────────────────┘

   licensing/  — self-contained (only depends on db.paths today; see DEBT.md)
```

**Dependency rule (enforced in CI by import-linter, see `pyproject.toml`
`[tool.importlinter]`):**

- `db`, `render`, `report`, `services`, `licensing` must **not** import `ui` or `app`.
- `db` is the lowest layer — it imports none of the upper layers.
- `licensing` must not reach up into `services`/`report`/`render`/`ui`/`app`.

A violation fails the build. The full Clean-Architecture layering
(`domain/application/infrastructure/presentation`) is the target; the contracts above
are the subset that already holds and are pinned so they can't regress.

## Report rendering by test category

`catalog_render.classify()` (pure, no Qt/DB) maps each test to a **render
category** — `numeric_tabular`, `qualitative`, `blood_bank`, `descriptive`,
`obstetric`, or `culture` — from its parameters, report head and name. The
classification runs at **render time** (so it applies to existing lab DBs with no
migration); a non-NULL `tests.render_category` overrides it. `render/report_doc.py`
dispatches to a per-category table/narrative drawer + a shared impression block,
and the worklist entry screen picks matching input widgets for the same category.

## The service boundary (the important rule)

**Every privileged write goes through a `services/` function that calls
`require(actor_role, capability)` and `log_audit(...)` inside one transaction.** UI
widgets gather input and render results; they do not run mutation SQL.

This is defence-in-depth: the widget's button state is UX only; `require()` is the
authoritative gate (`src/labdesk/roles.py`). The four privileged paths:

| Action | Service | Capability |
|--------|---------|------------|
| Create a bill | `services.receipts.create_receipt` | `create_receipt` |
| Void / deliver | `services.receipts.void_receipt` / `mark_receipt_delivered` | `void_receipt` / `deliver_report` |
| Release results | `services.results.release_results` | `finalize_results` |
| Save a culture | `services.results.save_culture` | `finalize_results` |
| Create / disable / reset user | `services.users.*` | `manage_users` |

### How a bill-create flows

```
ReceptionPage.save()                      # ui/reception.py
  ├─ validate name/cart/discount/patient-id, normalise phone, compute money
  ├─ build receipts_svc.BillDraft(...)
  └─ receipts_svc.create_receipt(con, draft, actor_username=, actor_role=)
        ├─ require(actor_role, "create_receipt")     # raises PermissionError if denied
        ├─ BEGIN (implicit) … upsert patient, insert receipt, allocate lab_no,
        │                     insert items, insert ledger income … COMMIT
        ├─ log_audit("patient_created"/"patient_updated")
        ├─ log_audit("receipt_created")
        └─ log_audit("discount_approved")  (if any discount)
  ← view then prints / WhatsApps / clears the form
```

## Composition root

`src/labdesk/app.py` (`run` / `run_cli`) wires the app: unlocks the DB, enforces the
license, builds the main window. `python -m labdesk` is the dev entry point.
