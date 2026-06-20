# LabDesk — Performance Uplift Plan (B → A/A+)

**Dimension:** Performance
**Current grade:** B (per `audit/10-performance-review.md`); DB sub-grade B− (per `audit/06-database-review.md`)
**Target:** Solid A / A+
**Method:** grounded in the two read-only audit reports + confirmation reads of `db/connection.py`, `report/content.py`, `ui/main_window.py`; external bar set from primary sources (SQLite docs, Qt docs, Google RAIL, SQLite/Python tooling docs).
**Constraint:** planning only — no source/test/config changed.

---

## 1. What "A+" means for performance on a desktop LIS

The audit graded LabDesk **on inspection** (`-X importtime`, profile-by-reading). That is the
core reason it cannot exceed B: **there are no measured budgets and no repeatable harness.**
An A/A+ performance posture is not "the code looks fast" — it is *"we have stated latency
budgets, we measure against them in CI, and nothing on the UI thread exceeds the budget."*

### 1.1 Latency budgets (the A+ bar, derived from the RAIL response model)

Google's RAIL model is the recognized, citable user-perception standard: respond to user
input within **100 ms** to feel instant, and keep animation/redraw frames under **~16 ms**
(60 fps); 100 ms–1 s is the "uninterrupted flow of thought" band where the user *notices* the
delay ([web.dev/RAIL](https://web.dev/articles/rail)). For a Qt desktop LIS this translates to:

| Interaction | Budget (A) | Stretch (A+) | Rationale |
|---|---|---|---|
| Main-thread block per event-loop turn | **< 100 ms** | < 50 ms | RAIL "response"; beyond this the window visibly stutters |
| Screen open (`go()` → painted) on a realistic DB | **< 200 ms** | < 100 ms | flow-of-thought band; reception/worklist/receipts |
| Cold start (process → login window painted) | **< 400 ms warm FS** | < 300 ms | currently ~211 ms wall on a *tiny* DB; must hold as data grows |
| Single bill save (reception) | **< 150 ms** | < 80 ms | highest-stakes write; must not stall other terminals under the WAL writer lock |
| Result release (worklist/microbiology) | **< 200 ms** | < 100 ms | multi-table write |
| Per-page report build (steady state) | **< 250 ms/page** | < 120 ms/page | drives batch printing throughput |
| No single SQL query on a hot path issues **> O(1) round-trips per row** (no N+1) | required | required | SQLite docs: covering/joined fetch over per-row probes |

"A" = these budgets are **defined and met on a seeded realistic dataset**. "A+" = the budgets
are **enforced by a benchmark harness in CI** that fails the build on regression, plus the
stretch numbers.

### 1.2 Structural requirements for A (table-stakes)

1. **Every foreign-key column and every hot-path filter/join column is indexed.** SQLite does
   not auto-index FK columns; un-indexed FK columns force a full child-table scan on every join
   and every `ON DELETE CASCADE`
   ([SQLite query planner](https://www.sqlite.org/queryplanner.html),
   [moldstud FK best practices](https://moldstud.com/articles/p-understanding-foreign-key-support-in-sqlite-best-practices-for-developers)).
2. **Planner has statistics.** Run `PRAGMA optimize` per the official lifecycle: `optimize=0x10002`
   on open for long-lived connections, plain `optimize` periodically and *after CREATE INDEX*
   ([SQLite PRAGMA optimize](https://www.sqlite.org/pragma.html#pragma_optimize)). Without it
   "the choice of which index to use is arbitrary" ([query planner doc](https://www.sqlite.org/queryplanner.html)).
3. **No N+1 on reception, worklist, microbiology, or report rendering** — batch with a JOIN or a
   single `WHERE id IN (…)` and bucket in Python.
4. **Every long/IO/multi-table operation runs off the UI thread** via the existing
   `QThreadPool`/`QRunnable` pattern, with the worker holding no Qt-widget references and
   reporting back via signals ([Qt QThread doc](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html),
   [pythonguis QThreadPool](https://www.pythonguis.com/tutorials/multithreading-pyside6-applications-qthreadpool/)).
5. **Large lists use Qt Model/View, not eager widget population**, or stay strictly `LIMIT`-bounded
   (LabDesk already does the latter — keep it).

### 1.3 Tooling / CI gates for A+ (stretch)

- A **perf-benchmark harness** (`tests/perf/`) that seeds a synthetic large DB (e.g. 50k receipts,
  300k results, 200k ledger, 100k audit rows) and asserts each budget.
- A **profiler in the loop**: `py-spy` for zero-overhead sampling of a running headless session,
  `scalene` for CPU-vs-native-vs-memory line attribution
  ([Scalene/py-spy comparison](https://johal.in/profiling-scalene-py-spy-memory-cpu-flamegraphs-2025/)).
- A CI job that runs the harness on the seeded DB and **fails on regression past the budget**.

---

## 2. Honest current state

**Already A-grade (keep, do not touch):** WAL + `synchronous=NORMAL` + `busy_timeout=8000` +
`temp_store=MEMORY` (`db/connection.py:143-152`); all UI list/search queries `LIMIT`-bounded;
debounced search (`ui/tasks.py:146`); PDF + WhatsApp off-thread on `QThreadPool` with per-thread
connections and shiboken-validity guards (`ui/tasks.py`); font preloaded once (`render/fonts.py`);
desktop-cache refresh daemon-threaded (`app.py:170`). These are correct and cited as strengths in
both audits.

**What blocks A:**

- **No measured budgets, no harness** — the grade rests on inspection, not numbers. *This is the
  single biggest blocker.*
- **Un-indexed FK / filter columns** — `receipts.patient_id`, `receipts.doctor_id`,
  `cultures.receipt_item_id`, `culture_sensitivity.culture_id`, `panel_items.test_id`,
  `ledger.ref_id`, plus small wins `micro_lists.kind`, `doctors.active`
  (`db/06` §H-1/§6; confirmed `db/connection.py:381-392` lists none of them).
- **No planner statistics** — no `ANALYZE`/`PRAGMA optimize` anywhere (`db/06` §M-4).
- **N+1 on the hottest paths** — report settings/logo re-query per page (H1/H2), cumulative-history
  per-prior-visit results loop (`report/content.py:135`, confirmed), `is_culture`/test-row re-probe
  per item (H4 / `db/06` §H-2), worklist `test_parameters`+`results` per item (H9 / §H-2).
- **Eager page construction** — all ~10 pages built at login (`ui/main_window.py:141`, confirmed),
  inflating login latency and idle memory (H5).
- **`urllib`/`ssl` on the cold-start import path** via `whatsapp.py` (H6).
- **Non-sargable date filters** in accounts (`ui/accounts.py:121,143`, `db/06` §M-6).
- **Bill save / lab-no allocation not in `BEGIN IMMEDIATE`** — read-then-write TOCTOU + a 500-iter
  retry storm under the writer lock (`ui/reception.py:743-767`, `db/06` §M-3); a latency hotspot
  under contention even though correctness is guarded by the unique index.

None are data-loss bugs. All are throughput/scaling issues that grow with `results`/`receipts`/
`ledger`/`audit_log` — exactly the tables that only ever grow.

---

## 3. Gap-closing plan (ordered)

Effort S < ~½ day, M ~1–2 days, L > 2 days. Each step names the file(s) and the standard it satisfies.

### Phase 0 — Make it measurable (the actual B→A unlock)

**P0.1 — Seed + benchmark harness.** *(Effort M, Risk Low, Impact High)*
New `tests/perf/seed_large.py` (programmatically inserts 50k receipts / 300k results / 200k ledger /
100k audit rows into a temp encrypted DB) and `tests/perf/bench.py` (times: cold import via
`-X importtime`, reception search, worklist load of a 12-test receipt, report build per page,
bill save, accounts date-range). Assert the §1.1 budgets. *Satisfies:* A+ "repeatable
perf-benchmark harness with budgeted targets." Without this, no other claim is provable.

**P0.2 — Profiler wiring (docs + dev dep recommendation).** *(Effort S, Risk Low, Impact Med)*
Document a `py-spy record -o flame.svg --pid <app>` and `scalene -m labdesk.app` recipe in
`tests/perf/README.md`. *Recommend adopting* `py-spy` and `scalene` as dev-only tools (see §4).
*Satisfies:* A+ tooling.

**P0.3 — CI perf gate.** *(Effort S, Risk Low, Impact Med)*
Add a CI job (extend existing workflow) that runs `tests/perf/bench.py` against the seeded DB with
`QT_QPA_PLATFORM=offscreen` and fails past-budget. *Satisfies:* A+ "CI gate."

### Phase 1 — Database (cheap, high-leverage; do first after P0)

**P1.1 — Add the missing FK / filter indexes.** *(Effort S, Risk Low, Impact High)*
In `db/connection._ensure_indexes` (`db/connection.py:381-392`) add, matching the established
idempotent pattern:

```sql
CREATE INDEX IF NOT EXISTS ix_receipts_patient   ON receipts(patient_id);
CREATE INDEX IF NOT EXISTS ix_receipts_doctor    ON receipts(doctor_id);
CREATE INDEX IF NOT EXISTS ix_cultures_item      ON cultures(receipt_item_id);
CREATE INDEX IF NOT EXISTS ix_culsens_culture    ON culture_sensitivity(culture_id);
CREATE INDEX IF NOT EXISTS ix_panel_items_test   ON panel_items(test_id);
CREATE INDEX IF NOT EXISTS ix_ledger_ref         ON ledger(ref_id);
CREATE INDEX IF NOT EXISTS ix_micro_lists_kind   ON micro_lists(kind);
CREATE INDEX IF NOT EXISTS ix_doctors_active     ON doctors(active);
```

*Satisfies:* "all FK/hot-path columns indexed" (SQLite query planner; FK best practices). High
priority items 1–3 kill the full child-table scans on history joins and cascade deletes.

**P1.2 — Planner statistics via `PRAGMA optimize`.** *(Effort S, Risk Low, Impact Med)*
In `db/connection.connect()` add `PRAGMA optimize = 0x10002` right after the existing PRAGMA block
(the app uses long-lived connections); run plain `PRAGMA optimize` (a) on connection close where
connections are closed, and (b) once in `init_db()` *after* `_ensure_indexes()` (the docs require it
after `CREATE INDEX`). *Satisfies:* "give the planner statistics" — without it index choice is
"arbitrary" per the SQLite docs.

**P1.3 — Drop the redundant `ix_results_item`.** *(Effort S, Risk Low, Impact Low)*
`results` UNIQUE(receipt_item_id, parameter_id) already covers `WHERE receipt_item_id=?` via its
leading column; `ix_results_item` is a prefix-duplicate that adds write amplification on the hottest
table. SQLite docs: "never contain two indices where one index is a prefix of the other." Confirm in
`db/connection.py` / `schema.sql`, then remove. *Satisfies:* SQLite redundant-index rule.

**P1.4 — Sargable accounts date filters.** *(Effort S, Risk Low, Impact Med)*
`ui/accounts.py:121,143`: rewrite `date(received_at) BETWEEN ? AND ?` →
`received_at >= ? AND received_at < date(?, '+1 day')` so `ix_receipts_date` is usable (the codebase
already does this in `_config.RECEIVED_TODAY`). *Satisfies:* sargability / index usability.

**P1.5 — `BEGIN IMMEDIATE` for lab-no allocation + bill save.** *(Effort M, Risk Med, Impact Med)*
`ui/reception.py:743-767` (and the bill-save txn): take the writer lock before the `MAX(lab_no)`
read so the read→write window closes; collapse the `range(500)` retry to a small bounded retry.
*Risk Med* because it changes locking semantics under multi-terminal use — must be benchmarked under
the P0.1 harness with 2 simulated writers. *Satisfies:* removes a contention hotspot under the WAL
single-writer lock.

### Phase 2 — Report/receipt render hot path (core print workflow)

**P2.1 — Batch settings into one query per build.** *(Effort S, Risk Low, Impact High)*
H1: `render/report_doc.py` letterhead/footer call `g(...)` ~16× *per page*. Load all settings once
per `build_report` (`SELECT key,value FROM settings`) into a dict and thread it down (or memoize
`_g` in `report/content.py:21` with a per-build cache). Replaces 16×N point queries with 1.
*Satisfies:* no N+1 on hot path / per-page budget.

**P2.2 — Decode the logo once per build.** *(Effort S, Risk Low, Impact High)*
H2: `render/primitives.py Doc.image()` re-reads + autocrops + smooth-scales the logo on every page.
Decode+autocrop+scale once (keyed by path+target height) at the top of `build_report` and reuse the
cached pixmap. *Satisfies:* per-page budget (removes PNG decode × N pages).

**P2.3 — Single-query cumulative history.** *(Effort M, Risk Low, Impact High)*
H3 (confirmed `report/content.py:134-138`): the per-prior-visit `SELECT … FROM results WHERE
receipt_item_id=?` loop is M×(1..8). Fetch all prior-visit result rows in one
`WHERE receipt_item_id IN (…)` and bucket by `item_id` in Python; collapses M×9 → ~M. *Satisfies:*
no N+1; matters most for returning-patient cumulative reports.

**P2.4 — Fetch the test row once per item.** *(Effort S, Risk Low, Impact Med)*
H4 / `db/06` §H-2: JOIN `is_culture, report_head, method_note` into the `receipt_items` fetch
(`render/report_doc.py:504`) exactly as `worklist.py:276` already does, instead of 2–3 `tests`
re-probes per item. *Satisfies:* no per-row re-probe.

### Phase 3 — UI thread & startup

**P3.1 — Lazy page construction.** *(Effort M, Risk Med, Impact Med)*
H5 (confirmed `ui/main_window.py:135-146`): build each `PageCls(con, user)` on first `go(idx)` and
cache, instead of eagerly in the login loop. *Risk Med* — must preserve `page.navigate`,
`setObjectName("page")`, `_page_index` wiring, and role-visibility filtering. Benchmark login under
P0.1. *Satisfies:* screen-open / cold-start budget + lower idle memory.

**P3.2 — Worklist batched load.** *(Effort M, Risk Low, Impact Med)*
H9 (`ui/worklist.py:327-335`): replace per-item `test_parameters` + `results` queries with one
`test_parameters … WHERE test_id IN (…)` and one `results … WHERE receipt_item_id IN (…)`, bucketed
in Python. Same for `ui/microbiology.py` if it mirrors the pattern. *Satisfies:* no N+1 on result
entry; result-release budget.

**P3.3 — Catalog panel counts in one query.** *(Effort S, Risk Low, Impact Low)*
H7 (`ui/catalog.py:352-360`): replace per-panel `db.panel_tests()` `len()` with one
`SELECT panel_id, COUNT(*) … GROUP BY panel_id`. *Satisfies:* no N+1.

**P3.4 — Defer `urllib`/`ssl` import.** *(Effort S, Risk Low, Impact Low)*
H6 (`labdesk/whatsapp.py:23-24`): move `import urllib.request`/`urllib.error` inside the send
functions. ~30 ms off cold start; honors the file's own "stdlib-only, lean AppImage" comment.
*Satisfies:* cold-start budget / Python lazy-import guidance
([PEP 690 rationale](https://peps.python.org/pep-0690/), [InfoWorld lazy imports](https://www.infoworld.com/article/4145854/speed-boost-your-python-programs-with-new-lazy-imports.html)).

**P3.5 — Audit the `importlib.metadata` pull.** *(Effort S, Risk Low, Impact Low)*
`labdesk/__init__` pulls `importlib.metadata` (~31 ms, `10` measurements). Defer the version lookup
to first use if it is import-time. *Satisfies:* cold-start budget.

### Phase 4 — Money precision (correctness-adjacent, flagged by DB audit)

**P4.1 — Money as INTEGER minor units.** *(Effort L, Risk High, Impact Med)*
`db/06` §M-5: REAL money columns (`schema.sql` subtotal/net/paid/due/amount/debit/credit/price)
drift on `SUM()`. Migrate to INTEGER paisa (or enforce rounded aggregates everywhere). *Risk High* —
schema migration touching billing/ledger; out of scope for a pure perf pass but listed because the
DB audit ties it to reconciliation integrity. **A-grade for *performance* does not require this**;
include only if pursuing the broader data-engineering A−.

---

## 4. Recommended tooling (recommendations only — not installed)

- **py-spy** (dev) — Rust sampling profiler, attaches to the running PySide6 process with near-zero
  overhead, no code changes; produces flamegraphs of the real hot path. Best first look.
  ([comparison](https://johal.in/profiling-scalene-py-spy-memory-cpu-flamegraphs-2025/))
- **scalene** (dev) — line-level CPU split (Python vs native vs IO) **and** memory; ideal for
  attributing time inside `report_doc.py` / `primitives.py` (Qt native paint vs Python).
- **pytest-benchmark** (dev) — to host `tests/perf/bench.py` assertions and produce stable
  per-commit timing baselines for the CI gate.
- **`PRAGMA optimize`** (no dependency) — official planner-stats mechanism, the recommended way to
  run ANALYZE since SQLite 3.46
  ([docs](https://www.sqlite.org/pragma.html#pragma_optimize)).
- **`EXPLAIN QUERY PLAN`** (no dependency) — assert in tests that hot queries use the new indexes
  (e.g. the history join uses `ix_receipts_patient`, not a `SCAN receipts`).

All are dev/CI-only; none ship in the AppImage, preserving the lean-binary goal.

---

## 5. Definition of done (the A+ checklist)

- [ ] Budgets in §1.1 documented and asserted in `tests/perf/bench.py`.
- [ ] Harness seeds a realistic large DB; CI fails on regression past budget.
- [ ] All FK + hot-filter columns indexed (`_ensure_indexes`); `ix_results_item` dropped.
- [ ] `PRAGMA optimize` lifecycle wired (open `0x10002`, periodic, post-`CREATE INDEX`).
- [ ] `EXPLAIN QUERY PLAN` tests prove no `SCAN` on history join / accounts date range / cascade.
- [ ] Zero N+1 on reception, worklist, microbiology, report render (P2.1–P2.4, P3.2–P3.3).
- [ ] No main-thread block > 100 ms on any hot interaction (verified via py-spy on the seeded DB).
- [ ] Lazy page construction; cold start holds < 400 ms warm-FS as the DB grows.
- [ ] `urllib`/`ssl` and `importlib.metadata` off the cold-start import path.

Hitting the first eight gives a **solid A**. Add the CI gate + stretch budgets (50 ms response,
<100 ms screen-open) and the P4 money-precision fix for **A+**.
