# A+ Uplift Plan — Database / Data-Integrity & Technical Debt

> **Dimension:** Database & Data-Integrity (current **B−**) + Technical Debt (current **C+**)
> **Target:** SOLID **A / A+** on both.
> **Scope:** `src/labdesk/schema.sql`, `src/labdesk/db/*`, `src/labdesk/services/billing.py`, and every money/FK/migration call site.
> **Method:** grounded in `audit/06-database-review.md` + `audit/12-refactor-roadmap.md`, confirmed against live source, benchmarked against primary standards (SQLite docs, SonarQube/SQALE, Stripe/Modern-Treasury money guidance).
> **Constraint:** planning only — this is the only file written. No source/test/config touched.

---

## 1. Where we are (evidence)

The schema design ideas are A-grade (encryption fail-closed, WAL+NORMAL, history snapshotting, tamper-evident audit chain, additive catalog sync). What holds the dimension at B−/C+ is **operational data engineering and an un-versioned, ad-hoc migration story**:

| # | Defect | Evidence (file:line) | Class |
|---|--------|----------------------|-------|
| D1 | Money stored as binary `REAL` (float) everywhere | `schema.sql` — `tests.charges`, `receipt_items.charge`, `receipts.{subtotal,discount_pct,less,net_amount,paid,due}`, `ledger.{debit,credit}`, `expenses.amount`, `medicines.{price,qty}` | Integrity |
| D2 | FK columns unindexed → JOIN/CASCADE full-scan | `receipts.patient_id/doctor_id`, `cultures.receipt_item_id`, `culture_sensitivity.culture_id`, `panel_items.test_id`, `ledger.ref_id` vs `connection.py:377-397` | Performance/Integrity |
| D3 | **No real migration framework.** `schema_version='1'` is written once (`schema.sql` last line) and **never read or bumped**; evolution is done by `_ensure_columns` (`connection.py:368`) + `_ensure_indexes` (`connection.py:377`) driven by `_EXTRA_COLUMNS` (`_config.py:93`). No ordering, no down-grade guard, no "DB newer than app" detection, no transactional batch. | Tech-Debt |
| D4 | Thin constraint surface: almost no `CHECK`, almost no `NOT NULL` on money/enum/status, enums (`status`, `kind`, `part_type`, `role`, sensitivity `result`) are free TEXT | `schema.sql` (receipts/ledger/cultures/users) | Integrity |
| D5 | Logical-only references can orphan financial rows: `ledger.ref_id`, `wa_messages.receipt_id` have no FK | `schema.sql`; ERD note `06-database-review.md:69` | Integrity |
| D6 | `round(…,2)` discipline is scattered across call sites, not centralized; two different rounding policies coexist | `services/billing.py:36-47`, `db/queries.py:92-93`, `ui/accounts.py` dues filter | Tech-Debt |
| D7 | No planner statistics (`ANALYZE`/`PRAGMA optimize` absent); non-sargable `date()` filters | `connection.py` (absent); `ui/accounts.py:121,143` | Performance |
| D8 | Lab-no allocation read→update not under `BEGIN IMMEDIATE` | `ui/reception.py:743-767` | Integrity/robustness |
| D9 | **No tracked technical-debt register / quota.** No ruff config, no debt ratio measured, no gate. | repo-wide; `12-refactor-roadmap.md` P4.6 | Tech-Debt |

**0% test coverage** on the trust/math seams (`services/billing.py`, `db/audit.py` verifier, `report/verify.py`) means none of the above can be changed safely today — every integrity fix below is gated on a characterization test landing first.

---

## 2. What "A+" means for THIS dimension (the bar, with sources)

### 2.1 Money — A+ definition
Store and compute money in **integer minor units** (paisa; PKR has 100 paisa = 1 rupee), convert to major units only at the UI/report/WhatsApp edges. Floating `REAL`/`double` for currency is a recognized defect because most decimal fractions (e.g. 0.10) are not representable in binary floating point, so arithmetic drifts and sums fail to reconcile to the penny ([SQLite/IEEE-754 floating-point representation](https://blog.codeminer42.com/be-cool-dont-use-float-double-for-storing-monetary-values/); [Modern Treasury — "Floats Don't Work For Storing Cents"](https://www.moderntreasury.com/journal/floats-dont-work-for-storing-cents)). The authoritative remediation is fixed-point `DECIMAL` **or** an integer count of the smallest currency unit; the integer-minor-unit ("store $5 as 500") pattern is the one Stripe/Modern Treasury standardize on ([cardinalby — storing currency values: best practices](https://cardinalby.github.io/blog/post/best-practices/storing-currency-values-data-types/)). SQLite has no native `DECIMAL` (it would store as `REAL` or `TEXT`), so **INTEGER paisa is the correct, native, lossless choice here.**

**Acceptance:** all money columns are INTEGER paisa; one shared money module owns rupee↔paisa conversion and rounding (banker's/half-up policy chosen explicitly and tested); `SUM()` is over integers (exact); a forward migration converts existing float rows with documented rounding; no `REAL` remains in any money column.

### 2.2 Foreign keys & referential integrity — A+ definition
`PRAGMA foreign_keys = ON` per connection (already done, `connection.py:143`) **and an index on every child/FK column.** SQLite does not auto-index FK columns; the docs are explicit: *"in most real systems, an index should be created on the child key columns of each foreign key constraint"* because a parent delete runs `SELECT … FROM child WHERE child_key=:val` which, without an index, *"are forced to do a linear scan of the entire child table … prohibitively expensive"* ([SQLite Foreign Key Support, §Indexes](https://www.sqlite.org/foreignkeys.html)). FK enforcement only works with the pragma on, which is per-connection and a no-op inside a transaction ([SQLite PRAGMA reference](https://sqlite.org/pragma.html)).

**Acceptance:** every declared FK column carries an index; logical references that must not orphan financial rows (`ledger.ref_id`) are either promoted to a guarded relationship or covered by an integrity test; `PRAGMA foreign_key_check` returns empty in CI on a representative DB.

### 2.3 Constraints — A+ definition
Schema-enforced invariants, not just app-enforced: `NOT NULL` on every column the code assumes present (money, status, FKs that are mandatory), `CHECK` on numeric ranges (`net_amount >= 0`, `paid >= 0`, `due >= 0`, `discount_pct BETWEEN 0 AND 100`, money `>= 0`), `CHECK (… IN (…))` on enums (`status`, `ledger.kind`, `part_type`, `users.role`, `culture_sensitivity.result IN ('S','I','R')`), and `UNIQUE` where uniqueness is a business rule (already good: `ux_receipts_labno`, `username`, `results(receipt_item_id,parameter_id)`).

### 2.4 Migrations — A+ definition
A **versioned, forward-only, transactional** migration runner keyed on `PRAGMA user_version` — SQLite's built-in 32-bit slot reserved for exactly this. The model: read `user_version`, run every numbered migration with a higher number in order, each wrapped `BEGIN … COMMIT` so a failure leaves `user_version` un-bumped and retryable; refuse to open a DB whose `user_version` is **newer** than the app knows (downgrade guard) ([Lev Lazinskiy — SQLite DB Migrations with PRAGMA user_version](https://levlaz.org/sqlite-db-migrations-with-pragma-user_version/); [gluer.org — user_version for schema versioning](https://gluer.org/blog/sqlites-user_version-pragma-for-schema-versioning/); [SQLite forum — raw-SQL migration tooling](https://sqlite.org/forum/forumpost/0f9dd8806f)). Heavy frameworks (Alembic/Flyway) are explicitly out of scope for a single-file desktop SQLite app; the principles are the same and a ~60-line runner is the right weight.

**Acceptance:** `user_version` drives a deterministic, ordered, transactional migration list; backup taken before migrating; newer-than-app DB refused with a clear error; `_EXTRA_COLUMNS`/`_ensure_indexes` either folded into numbered migrations or kept as an idempotent "v0 bootstrap" that the runner records as a baseline.

### 2.5 Technical debt — A to A+ definition
Move from *unmeasured* debt to a **measured, gated, decreasing** debt register using the SQALE model: Technical Debt Ratio = remediation effort ÷ (cost-to-develop-one-LOC × LOC). The SonarQube/SQALE Maintainability-Rating bands are: **A ≤ 5%**, B 5–<10%, C 10–<20%, D 20–<50%, E ≥ 50% ([SonarQube — Metric definitions](https://docs.sonarsource.com/sonarqube-server/10.8/user-guide/code-metrics/metrics-definition/); [Sonar — SQALE quality model](https://www.sonarsource.com/blog/sqale-the-ultimate-quality-model-to-assess-technical-debt)).

**Acceptance (A):** a checked-in debt register (`DEBT.md` / issue labels) with a remediation-minute estimate per item; CI gate that fails on **new** debt (ruff clean on changed files, no new `REAL` money column, `foreign_key_check` empty); a measured debt ratio in band **A (≤5%)** or a published downward trend with a quota ("no PR may raise the ratio"). **Stretch (A+):** SonarQube (or equivalent) wired into CI emitting the ratio per build, plus a "debt budget" enforced on the diff.

---

## 3. Concrete schema / constraint / index plan

These land as **numbered migrations** (see §5). DDL shown is the target state.

### 3.1 FK indexes (closes D2) — satisfies §2.2 (SQLite FK §Indexes)
Add to the migration runner / `_ensure_indexes`, all `IF NOT EXISTS`:
```sql
CREATE INDEX IF NOT EXISTS ix_receipts_patient  ON receipts(patient_id);
CREATE INDEX IF NOT EXISTS ix_receipts_doctor   ON receipts(doctor_id);
CREATE INDEX IF NOT EXISTS ix_cultures_item     ON cultures(receipt_item_id);
CREATE INDEX IF NOT EXISTS ix_culsens_culture   ON culture_sensitivity(culture_id);
CREATE INDEX IF NOT EXISTS ix_panel_items_test  ON panel_items(test_id);
CREATE INDEX IF NOT EXISTS ix_ledger_ref        ON ledger(ref_id);
CREATE INDEX IF NOT EXISTS ix_micro_lists_kind  ON micro_lists(kind);
CREATE INDEX IF NOT EXISTS ix_doctors_active    ON doctors(active);
DROP INDEX IF EXISTS ix_results_item;  -- redundant: UNIQUE(receipt_item_id,parameter_id) leads on receipt_item_id
```

### 3.2 Constraints (closes D4) — satisfies §2.3
SQLite **cannot `ALTER TABLE … ADD CONSTRAINT`**, so CHECK/NOT-NULL on existing tables require the documented **12-step table rebuild** (create new table with constraints, `INSERT … SELECT`, drop old, rename) run inside a migration with `foreign_keys=OFF` for the swap then re-validated with `foreign_key_check`. Target invariants:
- `receipts`: `net_amount_paisa INTEGER NOT NULL DEFAULT 0 CHECK(net_amount_paisa>=0)`, same for `subtotal/paid/due/less`; `discount_pct REAL CHECK(discount_pct BETWEEN 0 AND 100)`; `status TEXT NOT NULL CHECK(status IN ('pending','in_progress','reported','delivered'))`.
- `ledger`: `kind TEXT NOT NULL CHECK(kind IN ('income','expense','due_recovery'))`; `debit_paisa/credit_paisa INTEGER NOT NULL DEFAULT 0 CHECK(>=0)`.
- `culture_sensitivity`: `result TEXT CHECK(result IN ('S','I','R') OR result IS NULL)`.
- `users.role TEXT NOT NULL CHECK(role IN ('admin','operator','viewer'))`; `test_parameters.part_type CHECK(part_type IN ('N','L','H','Y','T'))`.

**Sequencing note:** because rebuilds are heavy/risky, do constraints **per-table, one migration each**, lowest-traffic table first, each behind its own characterization test. Constraints on `receipts`/`ledger` ride the **same** rebuild that converts money to INTEGER (§3.3) — do them together to avoid two rewrites of the hot tables.

### 3.3 Money → INTEGER paisa (closes D1/D6) — satisfies §2.1
**Strategy that preserves DB compatibility and data.** Two viable shapes; recommend **(A) parallel-column + rebuild**:

1. **Migration N (additive, zero-downtime read-compat):** add `*_paisa INTEGER` siblings next to each money REAL (`net_amount_paisa`, `paid_paisa`, `due_paisa`, `subtotal_paisa`, `less_paisa` on `receipts`; `debit_paisa`, `credit_paisa` on `ledger`; `charge_paisa` on `receipt_items`; `charges_paisa` on `tests`; `amount_paisa` on `expenses`; `price_paisa` on `medicines`). Backfill: `UPDATE … SET x_paisa = CAST(ROUND(x*100) AS INTEGER)`. `ROUND` here is the **one documented rounding event** for legacy float→int conversion. Old REAL columns remain readable → old binaries still open the DB.
2. **Code cutover (separate, test-gated):** `services/billing.py:compute_bill_totals` rewritten to take/return paisa ints (drop the dual `round_to_paisa` mode — paisa makes it moot, satisfying D6); all readers (`render/*`, `report/*`, `ui/accounts.py`, `ui/receipts.py`, `db/queries.py:receive_due`) switch to paisa + a single `paisa_to_str()`/`str_to_paisa()` edge formatter in a new `services/money.py` (or `db/_config.py`).
3. **Migration N+1 (rebuild, after a release of soak):** drop the REAL columns via table rebuild and rename `*_paisa → *` (or keep the `_paisa` suffix permanently — cleaner, recommend keeping the suffix so the type is self-documenting and no rename churn touches 200+ call sites).

A new `services/money.py` is the single home for: `to_paisa(rupees)`, `from_paisa(p)`, `fmt(p)` (e.g. `"1,234.50"`), and the rounding policy (recommend **half-up** to match invoice convention, stated and unit-tested). This collapses the scattered `round(…,2)` (D6) into one tested seam.

### 3.4 Referential integrity for `ledger.ref_id` (closes D5) — satisfies §2.2
`ref_id` is polymorphic (receipt id *or* expense id) so a single FK is impossible. Two A-grade options: (a) split into `receipt_id`/`expense_id` nullable FK columns with a `CHECK` that exactly one is set for income/due rows; or (b) keep polymorphic but add a CI integrity test asserting no `kind='income'` ledger row points at a missing receipt (`LEFT JOIN … WHERE r.id IS NULL`). Recommend **(b)** short-term (low risk), **(a)** as the A+ stretch.

---

## 4. Migration framework plan (closes D3) — satisfies §2.4

Introduce `db/migrations.py` with a `user_version`-driven runner; keep the existing additive helpers as **migration 1 = baseline**.

```python
# db/migrations.py  (sketch — ~60 LOC)
MIGRATIONS: list[tuple[int, str | Callable]] = [
    (1, _baseline),            # = current schema.sql + _ensure_columns + _ensure_indexes (idempotent)
    (2, _v2_fk_indexes),       # §3.1
    (3, _v3_money_paisa_add),  # §3.3 step 1 (additive, backfill)
    (4, _v4_constraints_lowtraffic),  # §3.2 small tables
    (5, _v5_receipts_ledger_rebuild), # §3.2 + §3.3 step 3 on hot tables
]

def migrate(con):
    cur = con.execute("PRAGMA user_version").fetchone()[0]
    head = MIGRATIONS[-1][0]
    if cur > head:
        raise DatabaseTooNewError(cur, head)   # downgrade guard (§2.4)
    backup_before_migrate(con)                 # reuse db/backup.py
    for ver, step in MIGRATIONS:
        if ver > cur:
            con.execute("BEGIN")
            try:
                step(con)
                con.execute(f"PRAGMA user_version = {ver}")
                con.commit()
            except Exception:
                con.rollback(); raise
```

Call `migrate(con)` from `init_db` **in place of** the current `executescript + _ensure_columns + _ensure_indexes` sequence (`connection.py:168-171`). The legacy `schema_version='1'` settings row stays for backward display but `user_version` becomes the source of truth. Each step is `IF NOT EXISTS`/existence-checked so re-running migration 1 on a long-lived DB is a no-op (preserves the established idempotent contract).

**Compatibility guarantees preserved:** additive-only steps (2,3) keep old binaries working; the rebuild steps (4,5) bump `user_version` so an older binary that lacks them simply re-applies nothing new; a *newer* DB is refused rather than silently misread.

---

## 5. Ordered gap-closing plan

Effort **S** ≤0.5d · **M** 1–3d · **L** ≥1wk. Every integrity change is **gated on a characterization test first** (the roadmap's hard rule, `12-refactor-roadmap.md:8`).

| # | Step | Files | Effort | Risk | Impact | Satisfies |
|---|------|-------|--------|------|--------|-----------|
| 1 | **Money-math characterization tests** (both rounding modes, discount, 100%, overpay/change, float edges, promo expiry) — unblocks all money work | `services/billing.py` → `tests/test_billing.py` | M | Low | High | §2.1 / roadmap P3.3 |
| 2 | **FK-column indexes + drop redundant `ix_results_item`** (additive, idempotent — safe early win) | `db/connection.py:377-397` (or migration 2) | S | Low | High | §2.2 / SQLite FK §Indexes |
| 3 | **`PRAGMA optimize` on close + sargable date filters** | `db/connection.py` close path, `ui/accounts.py:121,143` | S | Low | Med | §2.2 perf / D7 |
| 4 | **`user_version` migration runner** with downgrade guard + pre-migrate backup; fold baseline | new `db/migrations.py`, `db/connection.py:168-171`, `db/__init__.py` | M | Med | High | §2.4 |
| 5 | **`services/money.py`**: paisa conversion + single rounding policy + edge formatter (+ tests) | new `services/money.py`, `tests/test_money.py` | M | Low | High | §2.1 / D6 |
| 6 | **Money migration step 1 (additive `*_paisa` + backfill)**; backfill verified by a reconciliation test (`SUM(REAL*100)≈SUM(paisa)`) | migration 3, `schema.sql` (new cols) | M | Med | High | §2.1 / D1 |
| 7 | **Cutover code to paisa** (`compute_bill_totals`, all readers/writers) behind the §5.1 tests | `services/billing.py:15`, `db/queries.py:80-108`, `render/*`, `report/html.py`, `ui/{accounts,receipts,reception,dashboard}.py` | **L** | **High** | High | §2.1 / D1 |
| 8 | **CHECK/NOT-NULL/enum constraints on low-traffic tables** (table-rebuild, one migration each) | migration 4, `schema.sql` | M | Med | Med | §2.3 / D4 |
| 9 | **Receipts/ledger rebuild**: drop REAL money, add CHECK/NOT-NULL, finalize paisa (one combined rewrite) + `foreign_key_check` post-assert | migration 5, `schema.sql` | **L** | **High** | High | §2.1+§2.3 / D1,D4 |
| 10 | **`ledger.ref_id` integrity test** (no orphaned income rows) + optional split-column stretch | `tests/test_ledger_integrity.py`, (stretch) migration 6 | S/M | Low/Med | Med | §2.2 / D5 |
| 11 | **Lab-no allocation in `BEGIN IMMEDIATE`** (collapse 500-retry); ideally folded into the `create_receipt` service | `ui/reception.py:743-767` (→ `services/receipts.py`) | S | Med | Med | §2.3 / D8 |
| 12 | **Ruff config + debt register `DEBT.md`** (per-item remediation minutes) | new `ruff.toml`/`pyproject.toml`, `DEBT.md`, remove stale `RUF100` noqa | S | Low | Med | §2.5 / D9 |
| 13 | **CI debt gates**: ruff on changed files, `foreign_key_check` empty, "no new `REAL` money column" grep guard, optional SonarQube ratio | `.github/workflows/ci.yml` *(needs install permission — flag to owner)* | M | Low | High | §2.5 (A→A+) |

**Wave order:** 1 → 2,3 (cheap safe wins) → 4,5 (framework + money module) → 6 (additive) → 7 (cutover, isolate) → 8 → 9 (highest data risk, last) → 10,11 → 12,13 (debt gates). Steps 9 and 7 are the only **High**-risk items and must each ship behind a green characterization suite and a verified pre-migrate backup.

---

## 6. Recommended tooling (recommendations only — not installed)

- **pytest + pytest-cov** — needed to land the characterization tests that gate every integrity change; enforce `--cov-fail-under` on `services/billing.py`, `services/money.py`, `db/migrations.py`. *(Install permission required — escalate.)*
- **ruff** — single fast linter+formatter; gives the measurable debt baseline for §2.5. Config: `select = E,F,W,C90,B,SIM,PLR,N,UP` per roadmap P4.6.
- **SonarQube / SonarCloud (stretch, A+)** — emits the SQALE Technical-Debt Ratio per build so "A ≤5%" is *measured*, not asserted ([SonarQube metrics](https://docs.sonarsource.com/sonarqube-server/10.8/user-guide/code-metrics/metrics-definition/)). For a small repo, a lightweight checked-in `DEBT.md` register with per-item minutes is sufficient for an A; Sonar is the A+ upgrade.
- **`PRAGMA integrity_check` + `PRAGMA foreign_key_check`** (built-in, no install) — run in CI against a seeded DB after migrations to prove referential and structural integrity.
- **No heavy migration framework** — Alembic/Flyway are over-weight for a single-file embedded SQLite desktop app; the ~60-LOC `user_version` runner is the right tool ([SQLite forum guidance](https://sqlite.org/forum/forumpost/0f9dd8806f)).

---

## 7. A+ acceptance checklist (done = all true)

- [ ] No money column is `REAL`; all are `INTEGER` paisa, converted only at edges via `services/money.py`; rounding policy stated + tested.
- [ ] A forward migration converted existing float money with a documented rounding event and a reconciliation test.
- [ ] `PRAGMA foreign_keys=ON` (already) **and** every FK column indexed; `PRAGMA foreign_key_check` empty in CI.
- [ ] CHECK / NOT-NULL / enum constraints complete on money, status, kind, role, sensitivity.
- [ ] `user_version`-driven, forward-only, transactional migration runner with a downgrade guard and pre-migrate backup.
- [ ] Tracked, decreasing technical-debt register with per-item remediation estimates; CI gate blocks new debt; measured SQALE ratio in band **A (≤5%)** or on a published downward trend.
