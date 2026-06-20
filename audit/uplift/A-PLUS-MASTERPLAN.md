# LabDesk — Road to A+: Master Plan

**Role:** Lead Auditor synthesis of the seven dimension uplift plans.
**Inputs:** [`A-plus-01-security.md`](./A-plus-01-security.md), [`A-plus-02-architecture.md`](./A-plus-02-architecture.md), [`A-plus-03-testability.md`](./A-plus-03-testability.md), [`A-plus-04-maintainability.md`](./A-plus-04-maintainability.md), [`A-plus-05-performance.md`](./A-plus-05-performance.md), [`A-plus-06-documentation.md`](./A-plus-06-documentation.md), [`A-plus-07-data-and-debt.md`](./A-plus-07-data-and-debt.md).
**Current overall:** B- (Arch C, Sec B, Maint C+, Perf B, Test C+, Docs B+, Data/Debt B-/C+).

---

## Implementation progress (updated 2026-06-16)

| Wave | Status | Evidence |
|------|--------|----------|
| **0** Observability & CI scaffold | ✅ done | ruff/mypy/import-linter/bandit/pip-audit/pytest-cov/pre-commit configured; CI `quality` job (3 gates block, 2 report); `DEBT.md` baseline |
| **1** Trust-core characterization | ✅ done | audit/verify/billing/patient_id at 99% branch as a set; CI critical gate ≥95 BLOCKING; tests 56→115 |
| **2** Service boundary (keystone) | ◑ core done | all 4 privileged write paths (bill-create, result-release, culture-save, user-mutations) behind `require()`+audit services; tests→140. **Deferred:** bill-edit extraction (receipts.py:600), pytest-qt driven widget tests, semgrep write-SQL ban (needs semgrep install) |
| **4a** FK indexes | ✅ done | 5 FK indexes added; planner-uses-index + clean foreign_key_check tested |
| **4b** Money → integer paisa | ◑ mostly done | exact paisa computation (drift eliminated) **+ integer-paisa columns dual-written at every money writer + backfill** (paisa==round(real*100), tested). Only the REAL-column DROP + read-switch remains (kept REAL for read-compat) |
| **5** Security depth | ◑ mostly done | **off-DB audit anchor** (advisory truncation evidence, no false alarms) + keyvault 0→72% / licensing 64→72% coverage. Key-separation (split passphrase) still pending |
| **7** Docs-as-code | ◑ tree written | `docs/` Diátaxis tree (architecture/onboarding/database/security-model) + ADRs 0001/0002; **mkdocs --strict gate deferred** (needs install) |
| **3** Layering / package structure | ◑ meaningful renames done | **services→application, ui→presentation** (the two layers whose generic names clarify role); db/render/report/licensing keep descriptive names (they ARE infra/output/security). Dependency direction enforced by import-linter. Full ports/DI + a `domain` entity layer deferred (artificial for this data-centric app) |
| **6** Perf + god-file decomposition | ✅ god-files done | **all 4 decomposed via mixins/sibling modules**: settings 974→492, catalog 653→279, reception 857→598, receipts 747→431. (Perf budgets/profiling not yet added.) |
| **8** Ratchet (flip gates hard-fail) | ⏳ partial | mypy-strict gate on the security surface is BLOCKING; full ruff/mypy ratchet awaits debt drain |

Also: write-services covered to 95% branch with a BLOCKING ≥90 CI gate; global floor raised to 33.

Commits: `699486b` (W0) · `603bb10` (W1) · `50a8859`/`6cc2b6d`/`54ea3e0` (W2a/b/c) · `f24d4c8` (W4a) · `d7136ab` (W4b money) · `6f7fd1e` (W7 docs) · `4f9190b` (service rollback cov).

---

## 1. Thesis — what separates this B- system from an A+ one

LabDesk is not a *bad* codebase. Its primitives are correct: fail-closed SQLCipher encryption, vendored Ed25519 licensing, a SHA-256 audit chain, pure `compute_bill_totals`, strict Qt isolation, an accurate operator manual, WAL/NORMAL tuning. The audit found **clean bones and one systemic structural defect, surrounded by a near-total absence of enforcement.**

Two things hold the grade at B-:

1. **One architectural defect with security, integrity, and testability blast radius.** The three highest-stakes write paths — bill creation (`ui/reception.py:627`), clinical result/culture release (`ui/worklist.py:425`, `ui/microbiology.py:237`), and user-table mutations (`ui/settings.py:448,473,777`) — run multi-table SQL *inline in Qt widgets*, gated only by UX-level `can()`, with **no `require()` authorization, no service boundary, and no audit in the same transaction.** This single pattern is simultaneously a CWE-862/863 / OWASP A01 / ASVS V8 failure (Security), a Clean/Hexagonal Dependency-Rule violation (Architecture), an untestable un-mockable path (Testability), a god-method (Maintainability), a TOCTOU lab-no allocation hotspot (Performance), and the locus of float-money mutation (Data-Integrity). **Fixing it once moves six dimensions.**

2. **Almost nothing is machine-enforced.** There is no `[tool.ruff]` config (777 latent findings, linter decorative), no mypy/type gate, no coverage instrumentation at all (`addopts="-q"`), no mutation/property testing, no import contract, no SAST/dependency scan, no migration framework (`schema_version='1'` written once, never read), no docs build, no perf budget. CI runs `pytest -q` plus a *non-asserting* selftest. **A regression in any quality attribute is currently undetectable.**

The honest conclusion: **most of the A+ delta is not feature code — it is enforcement.** The 56 green tests, accurate docs, and correct crypto are A-grade *content* with C-grade *governance*. A+ is reached by (a) draining the one structural defect through a real application/service boundary, then (b) installing the CI gates — import-linter, ruff+mypy, branch-coverage fail-under, mutmut, bandit/pip-audit/semgrep, `mkdocs --strict`, `foreign_key_check`, perf budgets — that make every grade **self-enforcing and non-regressing**. Code without gates decays back to C; gates without the boundary fix lock in a B. A+ requires both, in that order, with tests green and DB/license/audit compatibility preserved throughout.

---

## 2. Per-dimension target table

| Dimension | Now | A+ acceptance bar (concrete, CI-enforced) | Plan |
|---|---|---|---|
| **Security** | B | OWASP ASVS 5.0 **L2** self-verified-clean + selected L3 (audit-integrity/key-mgmt). 100% of users/results/receipts/payments/bill mutations behind `roles.require()` at a `services/` boundary, audited in-txn; semgrep rule banning write-SQL in `ui/`; off-DB audit-chain anchor with **key-separated** MAC; SQLCipher KDF/cipher pinned & asserted; NIST 800-63B Rev.4 password policy (≥15 char); committed STRIDE threat model; bandit + pip-audit + semgrep gating on high/critical. HIPAA 164.312 safeguards met. | [01](./A-plus-01-security.md) |
| **Architecture** | C | Named layer tree (`domain/application/infrastructure/presentation/security/audit`) obeying Clean's inward Dependency Rule, **machine-enforced by Import-Linter** (`layers`+`forbidden`+exhaustive, zero violations, CI non-zero on breach). Every mutation through an application service with `require()`+`log_audit`; `grep` for `sqlite3` import and INSERT/UPDATE/DELETE in `ui/*.py` returns 0; ports invert `report⇏db`/`whatsapp⇏report`; composition root in `app.py`; no class >250 / module >400 LOC; `render⇄report` cycle broken. SOLID/Clean/Hexagonal re-graded A-/A. | [02](./A-plus-02-architecture.md) |
| **Testability** | C+ | Measured **branch** coverage in CI: ≥85% global, **≥95% (→100%)** on the trust set (`db/audit.py`, `report/verify.py`, `services/billing.py`, `db/patient_id.py`, `licensing/`, `db/crypto.py`, `db/auth.py`); mutmut ≥80% nightly-gated on the four critical modules; Hypothesis property tests for money/patient-id/crypto invariants; pytest-qt driven tests of the three clinical write paths asserting authz-deny + committed txn; golden-PDF regression. | [03](./A-plus-03-testability.md) |
| **Maintainability** | C+ | No file >400 LOC (8 violate), no function >60 LOC (34 violate), CC ≤10 / Radon rank ≥B everywhere (max is 39 today), MI rank A (≥20); **mypy --strict 0 errors** repo-wide; ruff expanded set (E,F,W,I,C90,N,UP,B,SIM,PLR,PLW,PLC,RUF,ARG,PERF,C4, max-complexity=10) **0 violations** (777 today); duplication <1%; pre-commit + identical CI hard-fail gates; typed `User`/`Session` replaces 78× `self.user[..]`. | [04](./A-plus-04-maintainability.md) |
| **Performance** | B | Measured, **budgeted, CI-enforced** RAIL targets (bill save <150ms, result release <200ms, report <250ms/page, cold start <400ms, main-thread block <100ms); every FK/hot-filter column indexed; `PRAGMA optimize` lifecycle; zero N+1 on print/worklist hot paths; `BEGIN IMMEDIATE` lab-no allocation; repeatable `tests/perf` harness seeding 50k receipts / 300k results, py-spy/scalene + `EXPLAIN QUERY PLAN` in loop, CI fails on budget regression. | [05](./A-plus-05-performance.md) |
| **Documentation** | B+ | **Diátaxis** tree (tutorials/how-to/reference/explanation/decisions); **C4** diagrams as code (Context+Container+Component for the write boundary); ≥10 **MADR** ADRs; mkdocstrings API reference; `mkdocs build --strict` + ruff `D` docstring lint in CI; CONTRIBUTING; consolidated schema reference with the `schema.sql + _EXTRA_COLUMNS` trap documented; ops runbook ≥6 failure modes; **IEC 62304 requirements→code→tests traceability matrix** validated by a CI script; stale docs fixed. | [06](./A-plus-06-documentation.md) |
| **Data-Integrity / Tech-Debt** | B- / C+ | Money in **INTEGER paisa** end-to-end via one tested `services/money.py` (no REAL column remains, migration + reconciliation test); index on every FK column, `foreign_key_check` empty in CI; complete CHECK/NOT-NULL/enum/UNIQUE surface; `PRAGMA user_version`-driven forward-only transactional migration runner with pre-migrate backup; checked-in decreasing `DEBT.md` register + CI debt gate (ruff on changed files, no-new-REAL-money guard); SQALE ratio band A (≤5%) or published downward trend. | [07](./A-plus-07-data-and-debt.md) |

---

## 3. Sequenced execution in WAVES

Principle: **security/data-integrity correctness first, gates before the code they protect, characterization tests before any refactor, keep `pytest -q` green every wave, preserve DB/license/audit compatibility.** Overlapping steps across dimensions are deduplicated — the service-boundary refactor (Waves 2-3) is the shared spine of Security + Architecture + Testability + Maintainability + Data-Integrity.

> Install gate: Waves 0/1 require owner approval to add dev tools (`pytest-cov`, `ruff` config is free, `mypy`, `import-linter`, `bandit`, `pip-audit`, `semgrep`, `hypothesis`, `pytest-qt`, `mutmut`, `radon`, MkDocs). Per memory rule, **ask before installing** — a build task is not install permission. Config-only changes (ruff `[tool.ruff]`, `[tool.mypy]`, coverage `[tool.coverage]`) can be authored without install; the *gate* activates once the tool is approved.

### Wave 0 — Make quality observable (cheap, low-risk, no behavior change)
**Goal:** stand up every measurement and CI scaffold *before* touching logic, so all later work is non-regressing and every grade becomes provable.
**Items:**
- `[tool.ruff]` expanded select + `mccabe.max-complexity=10` + per-file-ignores (`ui/widgets.py`, `licensing/_ed25519.py`) — `pyproject.toml`. *(Maint, Data/Debt)*
- `[tool.mypy] strict=true` with temporary non-strict override for `ui.*`/`app`/`whatsapp` — `pyproject.toml`. *(Maint)*
- `[tool.coverage] branch=true`, `source=["src/labdesk"]`; `addopts` adds `--cov --cov-branch` — `pyproject.toml`. *(Test)*
- Import-Linter config against the **current** tree (baseline green; new violations fail) — `pyproject.toml`. *(Arch)*
- `.pre-commit-config.yaml`: ruff-check(--fix) → ruff-format → mypy. *(Maint)*
- CI scaffold (`.github/workflows/ci.yml`): add ruff job, mypy job, coverage XML, `lint-imports`, `bandit`, `pip-audit`, `foreign_key_check` against a seeded DB, `mkdocs build --strict` (once docs exist). *(All)*
- `DEBT.md` debt register seeded from the 777 ruff findings + 34 long funcs + 8 god-files, with per-item remediation minutes. *(Data/Debt)*

**Lifts:** Maintainability, Testability, Architecture, Data/Debt, Security (CI hooks), foundation for all.

### Wave 1 — Trust-core characterization tests (unblocks every refactor)
**Goal:** pin current behavior of the 0%-coverage trust modules so later boundary/money refactors are provably behavior-preserving. **Gate before code.**
**Items:**
- `tests/test_audit_chain.py` → `db/audit.py:61` verify/rechain/fallback (tamper-detection). *(Test, Sec)*
- `tests/test_report_verify.py` → `report/verify.py:44` HMAC code round-trip + forgery rejection. *(Test, Sec)*
- `tests/test_billing.py` → `services/billing.py:15` both rounding modes, discount/overpay/promo-expiry/float edges. **Precondition for all money work.** *(Test, Data/Debt)*
- `tests/test_patient_id.py` → `db/patient_id.py` check-letter round-trip. *(Test)*
- Hypothesis money/patient-id/crypto invariants (net/due/change ≥0, due*change==0, 2dp). *(Test)*
- `tests/factories.py` + `conftest.py` factories for patient/receipt/result/culture graph. *(Test)*
- CI coverage fail-under: 80 global, **95 on the critical set**. *(Test)*

**Lifts:** Testability (C+ → B+, the single biggest lever), Security (trust-path evidence), Data-Integrity (unblocks money cutover).

### Wave 2 — The application/service boundary for the three hot writes (THE keystone)
**Goal:** route the three highest-stakes writes through an application service with `require()` + `log_audit` **in the same transaction**, thinning the Qt views. This is the shared spine; do it behind Wave 1's green tests.
**Items (each: extract service, add capability, `require()`+audit, `BEGIN IMMEDIATE`, thin the view):**
- **Bill create** `ui/reception.py:627-784` → `services/billing` / `application/receipts.py` (+ `BEGIN IMMEDIATE` lab-no allocation, collapse 500-retry storm). *(Sec, Arch, Maint, Perf, Data/Debt)*
- **Result + culture release** `ui/worklist.py:425-522` + `ui/microbiology.py:237-270` → `services/results.py` with `enter_results`/`finalize_results` caps; **remove `manage_users` admin-proxy** at `ui/worklist.py:308`. *(Sec, Arch, Maint)*
- **User mutations** `ui/settings.py:448,473,777` → `services/users.py` behind `require('manage_users')`/`assign_role`. *(Sec, Arch)*
- **Bill edit + ledger adjustment** `ui/receipts.py:600-668` → `application/receipts.py` (removes duplicated inline money mutation). *(Arch, Maint)*
- Add `enter_results`/`finalize_results`/`assign_role` to `roles.py CAP_MIN_LEVEL`.
- pytest-qt driven tests asserting **authz-deny for low role** + **committed multi-table state** for all three paths. *(Test)*
- semgrep custom rule: ban `con.execute("INSERT|UPDATE|DELETE …")` in `src/labdesk/ui/**`, SARIF + build-block. *(Sec — the regression guard for this wave)*

**Lifts:** Security (B → A — closes the CWE-862/863 systemic defect), Architecture (C → B, application boundary exists), Testability (clinical-write coverage), Maintainability (drains worst god-methods CC 38/39), Data/Debt + Perf (TOCTOU fix).

### Wave 3 — Dependency inversion, ports, composition root, read-path cleanup
**Goal:** make the dependency arrows point inward and remove engine knowledge from presentation, so Import-Linter can flip to exhaustive layers.
**Items:**
- Define `domain/ports.py` Protocols (`ReceiptRepo`/`ResultRepo`/`SettingsRepo`/`AuditSink`/`Authorizer`/`Clock`) + `infrastructure/db/repos.py` adapters wrapping `db/queries.py`; services depend on ports. *(Arch)*
- Break `report→db`: assemble a `ReportData` DTO in application, pass into `report.build_*` — `report/content.py:9`, `export.py:12`, `verify.py:22`, `__init__.py:26`. *(Arch)*
- Invert `whatsapp→report`: inject a `PdfBuilder` callable from the composition root — `whatsapp.py:390,401`, `app.py`. *(Arch)*
- Composition root in `app.py`: construct adapters, inject `Services`/`AppContext`; pages receive context not `con`/`db` — `ui/main_window.py:135-146`, all `ui/*` ctors. *(Arch)*
- Route all UI **reads** through repository/query functions; remove raw SQL + `sqlite3` import from the 13 UI files (one PR each, 241 call-sites). *(Arch)*
- Physically re-fold into `domain/application/infrastructure/presentation/security/audit`; flip Import-Linter to **exhaustive layers, zero violations**. *(Arch)*

**Lifts:** Architecture (B → A, Dependency Rule machine-enforced), Maintainability (typed seams), Testability (headless use-case tests).

### Wave 4 — Data-integrity hardening (money, FKs, constraints, migrations)
**Goal:** convert money to integer paisa and install real schema governance, all behind Wave-1 characterization tests + pre-migrate backups.
**Items:**
- FK/hot-filter indexes in `db/connection.py:381-392` (`receipts.patient_id/doctor_id`, `cultures.receipt_item_id`, `culture_sensitivity.culture_id`, `panel_items.test_id`, `ledger.ref_id`, `micro_lists.kind`, `doctors.active`); drop redundant `ix_results_item`. *(Data/Debt, Perf — shared)*
- `PRAGMA optimize` lifecycle (open `0x10002`, post-CREATE INDEX, on close). *(Perf, Data/Debt)*
- `db/migrations.py`: `user_version`-driven forward-only transactional runner, downgrade guard, pre-migrate backup; fold current additive helpers as baseline. *(Data/Debt)*
- `services/money.py`: paisa↔rupee, single half-up rounding policy, edge formatter (+tests). *(Data/Debt)*
- Money migration: additive `*_paisa` columns + ROUND backfill (keeps old binaries readable) → cut over all money code behind characterization tests → table-rebuild dropping REAL + adding CHECK/NOT-NULL, `foreign_key_check` post-assert. *(Data/Debt)*
- CHECK/NOT-NULL/enum constraints (status/kind/role/sensitivity) via table-rebuild migrations. *(Data/Debt)*
- `ledger.ref_id` orphan-integrity test. *(Data/Debt)*

**Lifts:** Data-Integrity (B- → A), Performance (FK indexes + optimize), Testability (reconciliation tests).

### Wave 5 — Security depth (key separation, anchor, crypto pinning, policy, threat model)
**Goal:** push Security from A to A+ with the controls that don't depend on the boundary fix.
**Items:**
- Off-DB audit-chain anchor exported to append-only witness each launch; audit `rechain_audit()` invocations; **key-separated HMAC** not derivable from DB passphrase — `db/audit.py:31-58,61-92,95-111`, `app.py` launch, `.secrets.json` via `paths.py:67-91`. *(Sec)*
- Pin SQLCipher `kdf_iter=256000`, `cipher_compatibility=4`, `cipher_memory_security=ON` + assert; reject weak header KDF on restore — `db/connection.py:88-93,48-64`, `_driver.py`, `backup.py:175`. *(Sec)*
- Secret Service encrypted DH session — `db/keyvault.py:44-56,88,133`. *(Sec)*
- NIST 800-63B Rev.4 password policy: ≥15 char, breach blocklist, ≤100-attempt rate limit, login-audit after forced change — `ui/login.py:139-143,102-104`, `db/auth.py:54-73`, `db/crypto.py`. *(Sec)*
- Commit STRIDE threat model + DFD with the shared-key trust boundary drawn — `docs/security/threat-model.md`. *(Sec, Docs)*
- Backfill security abuse-case tests + PermissionError tests on the new services; scrub/encrypt PII in fallback/crash logs (`db/audit.py:18-28`, `app.py:200-209`). *(Sec, Test)*

**Lifts:** Security (A → A+), Documentation (threat model), Testability (abuse cases).

### Wave 6 — Performance hot-path & maintainability decomposition (parallelizable)
**Goal:** hit the RAIL budgets and split the god-files now that services exist to absorb the logic.
**Items (Perf):**
- Build `tests/perf/seed_large.py` + `bench.py` budgeted harness; CI perf gate; profiler README (py-spy/scalene). *(Perf)*
- Batch report settings into one query; decode logo once/cache pixmap; single-query cumulative history (`report/content.py:134-138`); JOIN test row into `receipt_items` fetch; batch worklist `test_parameters`+results; catalog counts via GROUP BY; sargable accounts date filters (`ui/accounts.py:121,143`); lazy page construction (`main_window.py:135-146`); defer `urllib/ssl` + `importlib.metadata` imports. *(Perf)*

**Items (Maint, behind GUI regression net):**
- Drain 777 ruff findings (auto-fix + format sweep, E501 wrap, name magic numbers, hoist lazy imports, narrow bare excepts). *(Maint)*
- 100% mypy --strict on non-UI core (db/services/render/report/licensing). *(Maint)*
- Typed `User` dataclass + `Role` StrEnum + `AppContext` threaded through call sites (kills 78× `user[..]`). *(Maint)*
- Extract `_interpret_gateway_reply` from `whatsapp.py` send_pdf/send_text (kills duplication #1); `OkCancelDialog` helper; collapse long parameter lists into dataclasses. *(Maint)*
- Split god-files behind tests: `SettingsPage` (988) → tabbed sub-pages; `ReceptionPage`/`ReceiptsPage`/`WorklistPage` → `_build_*` + ViewModel over services (MVVM); `app.run` (CC 39) → `_single_instance_guard`/`_show_splash`/`_check_license`/`_apply_theme`/`_unlock_db`; `report_doc.py` (667) → package; `catalog.py` (653) split. *(Maint, Arch A6)*
- Break `render⇄report` cycle one-way + Import-Linter independence check (`render/__init__.py:20`, `report/__init__.py:24-26`). *(Arch A7, Maint)*

**Lifts:** Performance (B → A/A+), Maintainability (C+ → A/A+), Architecture (god-objects, cycle → A+).

### Wave 7 — Documentation-as-code & traceability
**Goal:** structure, diagram, decide, generate, and trace — the last B+ → A+ move.
**Items:**
- Fix stale docs (whatsapp Cloud-API mislabel, `__version__`, WeasyPrint/no-branding) — `audit/02-module-map.md`, `README.md`, `report/__init__.py`. *(Docs)*
- Scaffold Diátaxis `docs/` tree + `mkdocs.yml`; port audit content (schema reference with `_EXTRA_COLUMNS` trap warning, module map, architecture overview). *(Docs)*
- C4 diagrams as code (Context/Container/Component-db-write); CONTRIBUTING + developing guide; where-the-rules-live caveat; tutorials; operations runbook (≥6 failure modes); 10 MADR ADRs incl. *inline-write-paths-as-debt*. *(Docs)*
- Enable mkdocstrings API reference; ruff `D` docstring lint scoped to public packages. *(Docs)*
- SRS-lite `requirements.md` (REQ-###) + requirements→code→tests **traceability matrix** for the trust features; `scripts/check_traceability.py` wired into CI so it can't rot. *(Docs, Test)*
- Docs CI job: `mkdocs build --strict`; version-stamp to `__version__`. *(Docs)*

**Lifts:** Documentation (B+ → A+), Testability/Security (traceability evidence for IEC 62304).

### Wave 8 — Lock the ratchet (flip every gate to hard-fail)
**Goal:** make A+ self-enforcing and non-regressing.
**Items:**
- mutmut on the four critical modules: baseline + nightly CI gate ≥80%. *(Test)*
- Golden-PDF render regression for receipt + report. *(Test)*
- Raise coverage gate to 85% global; promote `ui/`/`app`/`whatsapp` into repo-wide mypy --strict (remove override); make `radon cc -nc B` / `mi -nb A` blocking; wily non-regression trend. *(Maint, Test)*
- Import-Linter exhaustive layers blocking; semgrep/bandit/pip-audit fail on high/critical; perf budget gate; `foreign_key_check` empty + no-new-REAL-money-column guard; SQALE ratio (stretch, SonarQube). *(All)*

**Lifts:** every dimension from A to A+ (the difference between "achieved once" and "cannot regress").

---

## 4. CI quality gates to add (the section that locks in every grade)

| # | Gate | Tool | Threshold / failure condition | Locks |
|---|---|---|---|---|
| G1 | Lint | **ruff** (E,F,W,I,C90,N,UP,B,SIM,PLR,PLW,PLC,RUF,ARG,PERF,C4) | **0 violations**, `max-complexity=10` | Maint, Data/Debt |
| G2 | Format | **ruff format --check** | clean | Maint |
| G3 | Static types | **mypy --strict** | **0 errors** (scoped → repo-wide in W8) | Maint |
| G4 | Import contract | **import-linter** (`lint-imports`) | **0 violations**, exhaustive layers, non-zero exit blocks merge | Arch |
| G5 | Branch coverage | **pytest-cov / coverage** `branch=true` | **≥80% global** (→85), **≥95% critical set** | Test |
| G6 | Mutation testing | **mutmut** (4 critical modules) | **≥80%**, nightly-gated | Test |
| G7 | Property invariants | **hypothesis** | money/patient-id/crypto invariants pass | Test |
| G8 | GUI behavior | **pytest-qt** | clinical-write authz-deny + committed-txn assertions pass | Test, Sec |
| G9 | SAST | **bandit** | **0 high/critical** | Sec |
| G10 | Dependency CVEs | **pip-audit** / uv audit | **0 high/critical**, SBOM (cyclonedx/syft) | Sec |
| G11 | Taint + custom rule | **semgrep** | **no write-SQL in `ui/**`**, SARIF, build-block | Sec, Arch |
| G12 | FK integrity | **`PRAGMA foreign_key_check`** (built-in) | **empty** against seeded DB post-migration | Data/Debt |
| G13 | No-new-REAL-money | repo guard script | fails if a new `REAL` money column appears | Data/Debt |
| G14 | Debt budget | **DEBT.md** + ruff-on-changed; stretch **SonarQube** SQALE | no PR raises ratio; band A (≤5%) or downward trend | Data/Debt, Maint |
| G15 | Perf budget | **pytest-benchmark** + seeded DB | fails past RAIL budget (bill save <150ms, report <250ms/page, etc.) | Perf |
| G16 | Query plans | **`EXPLAIN QUERY PLAN`** asserts | no SCAN on history join / accounts range / cascade | Perf, Data/Debt |
| G17 | Docs build | **`mkdocs build --strict`** | **0 warnings / dead links** | Docs |
| G18 | Docstring lint | **ruff `D`** (public packages) | clean | Docs |
| G19 | Traceability | **`scripts/check_traceability.py`** | matrix consistent with `tests/` | Docs, Test |
| G20 | Pre-commit parity | **pre-commit** | identical hooks (ruff→format→mypy) re-run as CI hard-fail | Maint |

**The four highest-priority gates** (install first, they catch the most regressions): **G4 import-linter** (turns "we have an architecture" into a build failure), **G5 branch coverage fail-under** (nothing measures coverage today), **G11 semgrep ban-write-SQL-in-ui** (the regression guard that keeps the Wave-2 boundary from being bypassed), **G1+G3 ruff+mypy** (drains 777 findings, prevents primitive-obsession reintroduction).

---

## 5. Biggest levers — ~10 highest-ROI moves (each lifts multiple grades)

1. **Extract the three hot writes into audited application services with `require()`+`log_audit`+`BEGIN IMMEDIATE`** (Wave 2). Lifts **Security (→A), Architecture, Testability, Maintainability, Data-Integrity, Performance** — the single keystone. The audit's top systemic finding.
2. **Wave 0 CI scaffold** (ruff+mypy+coverage+import-linter+bandit configs and jobs). Lifts **Maintainability, Architecture, Testability, Security, Data/Debt** at once; makes all later work non-regressing.
3. **Branch-coverage instrumentation + fail-under gate** (Wave 1/0). Lifts **Testability** decisively and provides verification evidence for **Security** and **Documentation/IEC 62304**.
4. **Trust-core characterization tests** for `db/audit.py`, `report/verify.py`, `services/billing.py`, `db/patient_id.py` (Wave 1). Lifts **Testability (C+→B+)** and **unblocks the money cutover and every refactor** safely.
5. **Import-Linter contract** (Wave 0 baseline → Wave 3 exhaustive). Lifts **Architecture** and prevents the inline-mutation pattern from ever returning.
6. **semgrep ban-write-SQL-in-`ui/`** custom rule (Wave 2). Locks **Security + Architecture** — the boundary cannot be bypassed in a future PR.
7. **FK indexes + `PRAGMA optimize` lifecycle** (Wave 4). Lifts **Performance and Data-Integrity** simultaneously with near-zero risk.
8. **Money → INTEGER paisa via `services/money.py`** (Wave 4). Lifts **Data-Integrity (→A)** and removes a class of float-drift correctness bugs; gated by lever 4.
9. **Typed `User`/`Session`/`AppContext` + mypy --strict on the core** (Wave 6). Lifts **Maintainability** and enables strict typing across the UI; kills 78× bare-dict access.
10. **Docs-as-code: Diátaxis + C4 + ADRs + traceability matrix in CI** (Wave 7). Lifts **Documentation (→A+)** and supplies the IEC 62304 evidence that strengthens **Security** and **Testability** grades.

---

## 6. Realistic effort & sequencing estimate

Effort: S ≤0.5d, M 1-3d, L ≥1wk. Risk in parentheses.

| Wave | Theme | Rough effort | Risk | Grades moved |
|---|---|---|---|---|
| **0** | Observability & CI scaffold | ~3-4 days (config) | Low | foundation (Maint/Test/Arch/Data) |
| **1** | Trust-core characterization + factories | ~1.5 weeks | Low | Test C+→B+, Sec evidence, unblocks money |
| **2** | Service boundary for 3 hot writes | ~2-3 weeks | **High** | **Sec B→A**, Arch, Maint, Data, Perf |
| **3** | Ports, composition root, read cleanup, re-fold | ~3-4 weeks | Med | **Arch C→A** |
| **4** | Money/FK/constraints/migrations | ~2-3 weeks | **High** (money cutover) | **Data B-→A**, Perf |
| **5** | Security depth (keys/anchor/crypto/policy/STRIDE) | ~2 weeks | Med | **Sec A→A+**, Docs |
| **6** | Perf hot-path + god-file decomposition | ~3-4 weeks | Med-High | **Perf B→A+**, **Maint C+→A+**, Arch |
| **7** | Docs-as-code + traceability | ~2 weeks | Low | **Docs B+→A+** |
| **8** | Flip all gates to hard-fail (mutmut/golden/ratchet) | ~1 week | Low | every dim A→A+ |

**Order to actually do it in:** strictly **0 → 1 → 2** (gates, then tests, then the keystone boundary — never reorder these; the boundary refactor is High-risk and *must* sit behind Wave-1 green tests and the Wave-2 semgrep guard). After Wave 2, **Waves 3, 4, 5 can proceed in parallel tracks** (Architecture inversion / Data-money / Security depth are largely independent once services exist), but Wave 4's money cutover must stay behind Wave-1 characterization tests + a verified pre-migrate backup. **Wave 6 (perf + decomposition) follows Wave 3** (decomposition needs the service layer to absorb logic and the GUI regression net). **Wave 7 (docs)** can start any time after Wave 0 but is best finalized after Waves 2-5 so the architecture/threat-model/ADRs reflect reality. **Wave 8 last** — flip ratchets only when the underlying work is green, so the hard-fail gates lock in achieved grades rather than blocking in-flight work.

**Total realistic span:** ~5-6 months of focused engineering for a small team, with **B- → solid B by end of Wave 2**, **B+ by Wave 4**, **A by Wave 6**, and **A+ locked by Wave 8**. The cheapest, highest-leverage 20% (Waves 0-1) is doable in ~3 weeks and already converts the "undetectable regression" posture into a measured, gated one.

---

## 7. Compatibility invariants to hold every wave
- `pytest -q` stays green (each step ships with its tests).
- **DB compatibility:** money migration is additive-first (`*_paisa` alongside REAL) so older binaries keep reading; the table-rebuild that drops REAL is the last, isolated, backup-gated step.
- **License compatibility:** Ed25519 verification path untouched; no signature-format change.
- **Audit-chain compatibility:** the off-DB anchor and key-separated MAC are additive; existing chain verification (`db/audit.py:61`) must continue to validate historical rows. `rechain_audit()` becomes audited, not removed.
- **No new third-party dependency without owner approval** (memory rule). Prefer stdlib (`typing.Protocol`, hand-wired composition root, ~60-LOC migration runner) over frameworks (no DI container, no Alembic).

---

*Cross-references: each wave item is traced to its source dimension plan in §2 and §3. The per-dimension acceptance bars, citations, and file:line specifics live in the seven `A-plus-0N-*.md` reports.*
