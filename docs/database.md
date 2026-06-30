# Database reference

## Engine & encryption

SQLite via **SQLCipher** (`sqlcipher3-binary`): the whole file is encrypted at rest
with a key derived from the lab's passphrase. `db/connection.py` is **fail-closed** —
if encryption can't be established it refuses to open rather than fall back to
plaintext. `PRAGMA foreign_keys = ON` on every connection.

## Schema

Canonical schema: `src/labdesk/schema.sql` (applied idempotently with `IF NOT EXISTS`).

| Table | Purpose |
|-------|---------|
| `patients` | patient identity (permanent `mr_no` / Patient ID) |
| `doctors` | referring doctors |
| `tests`, `test_parameters`, `panels`, `panel_items` | catalogue (`tests.render_category` can override the printed layout — see `catalog_render.py`) |
| `receipts` | bill + patient snapshot + money + status (`pending→reported→delivered`) |
| `receipt_items` | line items (test snapshot, charge, per-item `remarks`, `conclusion`/impression) |
| `results` | entered result lines (snapshotted for reproducible reprints) |
| `cultures`, `culture_sensitivity` | microbiology |
| `ledger` | money movements (income / due-recovery / adjustment / void / expense) — the source of truth for period income, dated by event |
| `expenses` | outgoings |
| `users` | staff accounts (scrypt hashes, roles, lockout) |
| `audit_log` | tamper-evident SHA-256 hash chain (see [security-model.md](./security-model.md)) |
| `settings` | key/value config (incl. the report-verify HMAC key) |

History is **snapshotted onto receipts/results**, so editing a patient or test never
rewrites an already-issued report.

## Migrations

No framework; `connection.py` applies on connect: (1) `schema.sql`; (2)
**`_EXTRA_COLUMNS`** (`db/_config.py`) — additive `ALTER TABLE ADD COLUMN` for
post-v1 columns; (3) **`_ensure_indexes`** — idempotent `CREATE INDEX IF NOT EXISTS`;
(4) an additive catalogue sync (matched by stable legacy keys, not row ids). Adding a
post-v1 column → add it to `_EXTRA_COLUMNS`; adding an index → `_ensure_indexes`.

## Indexes

Hot-path and every FK column is indexed (e.g. `ix_receipts_patient`,
`ix_cultures_item`, `ix_panel_items_test`, `ix_ledger_date`) plus `ux_receipts_labno`
(unique daily serial). `tests/test_schema_indexes.py` asserts they exist and are used.

## Money columns

Money is stored in `REAL` columns with integer **paisa** twins written alongside
(`*_paisa`), the exact-math foundation being `application/money.py`. The eventual drop
of the `REAL` columns is tracked in [`../DEBT.md`](../DEBT.md) and
[ADR 0002](./decisions/0002-integer-paisa-money.md).
