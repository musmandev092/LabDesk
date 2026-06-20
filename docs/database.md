# Database reference

## Engine & encryption

SQLite via **SQLCipher** (`sqlcipher3-binary`). The whole file is encrypted at rest
with a key derived from the lab's passphrase. The connection layer
(`src/labdesk/db/connection.py`) is **fail-closed**: if encryption can't be
established it refuses to open a usable connection rather than silently falling back
to plaintext. `PRAGMA foreign_keys = ON` is set on every connection.

## Schema

The canonical schema is `src/labdesk/schema.sql` (applied idempotently with
`CREATE TABLE IF NOT EXISTS` on connect). Core tables:

| Table | Purpose |
|-------|---------|
| `patients` | patient identity (permanent `mr_no` / Patient ID) |
| `doctors` | referring doctors |
| `tests`, `test_parameters`, `panels`, `panel_items` | the test catalogue (`tests.render_category` optionally overrides the printed-report layout — see `catalog_render.py`) |
| `receipts` | a bill + patient snapshot + money + status (`pending→reported→delivered`) |
| `receipt_items` | line items (test snapshot + charge + per-item `remarks` and `conclusion`/impression) |
| `results` | entered result lines (snapshotted for reproducible reprints) |
| `cultures`, `culture_sensitivity` | microbiology findings |
| `ledger` | income / void / due-recovery money movements |
| `expenses` | outgoings |
| `users` | staff accounts (scrypt password hashes, roles, lockout) |
| `audit_log` | tamper-evident SHA-256 hash chain (see [security-model.md](./security-model.md)) |
| `settings` | key/value app config (incl. the report-verify HMAC key) |

History is **snapshotted onto receipts/results** so editing a patient or test never
rewrites a previously issued report.

## Migrations

There is no heavyweight migration framework; `connection.py` applies, on connect:

1. `schema.sql` (idempotent `IF NOT EXISTS`).
2. **`_EXTRA_COLUMNS`** (`db/_config.py`) — additive `ALTER TABLE ADD COLUMN` for
   columns added after v1, so older DBs gain them without a destructive rebuild.
3. **`_ensure_indexes`** — idempotent `CREATE INDEX IF NOT EXISTS`, so index additions
   reach existing encrypted DBs too.
4. An additive sync of the shipped catalogue into existing installs.

When you add a post-v1 column, add it to `_EXTRA_COLUMNS`; when you add an index, add
it to `_ensure_indexes`.

## Indexes

Hot-path + every foreign-key column is indexed (the FK indexes were added in the A+
uplift to stop full scans and slow `ON DELETE CASCADE`): e.g. `ix_receipts_patient`,
`ix_receipts_doctor`, `ix_cultures_item`, `ix_cultsens_culture`, `ix_panel_items_test`,
plus `ux_receipts_labno` (the unique daily-serial guard). `tests/test_schema_indexes.py`
asserts they exist, that the planner uses one for an equality lookup, and that
`PRAGMA foreign_key_check` is clean.

## Known data-integrity debt

Money is currently stored in `REAL` columns (float), which can drift sub-cent. The
migration to integer **paisa** is underway — `services/money.py` is the exact-math
foundation; the column cutover is tracked in [`../DEBT.md`](../DEBT.md).
