# 12 — Refactor Roadmap (Principal Refactoring Lead)

> **Scope.** This is a *plan*, not a refactor. It sequences the findings of reports 01–11 into a prioritized, incremental program of work for LabDesk (a HIGH-criticality desktop LIS handling medical/financial/patient data).
>
> **Governing constraints (apply to EVERY item):**
> 1. **One subsystem at a time.** No big-bang rewrites. Each item is independently shippable.
> 2. **Tests after every change.** `pytest -q` must stay green (currently 56 passed); add the item's own tests *before or with* the change.
> 3. **No behavior changes** during a refactor item unless the item is explicitly a security/correctness *fix* (P0–P2). Refactors (P3–P5) are behavior-preserving by definition.
> 4. **Preserve DB / license / audit compatibility.** No schema break without an additive migration; the SHA-256 audit chain and Ed25519 license format must keep verifying old data.
> 5. **Read-only-friendly seams first.** Prefer extracting *pure* functions (headless-testable) over moving Qt code.

---

## Priority bands

| Band | Theme | Why it leads |
|------|-------|--------------|
| **P0** | Critical Security | Forgeable audit chain + cleartext passphrase on the bus = direct compromise of the trust story for a medical/financial system. |
| **P1** | Data Integrity | Money-as-float, missing FK indexes, unindexed lab-no allocation, divergent reference ranges = silent wrong numbers on clinical/financial output. |
| **P2** | Authorization | The `require()` boundary is bypassed for the most dangerous writes (bill create, result release, user/role mutation). |
| **P3** | Testability | Critical paths (audit verifier, HMAC codes, billing math, check-letters, SSRF) have 0% coverage; no coverage gate. |
| **P4** | Maintainability | God-classes, primitive-obsession user dict, dead noqa, no ruff config, duplicated gateway code. |
| **P5** | UX | Accessibility, colour-only clinical flags, contrast leaks, flow gaps. |

**Sequencing principle:** P0–P2 are *fixes* that change behavior deliberately and must land first (they also create the audited service seams P3/P4 depend on). P3 testability is interleaved — each fix ships with tests, and the dedicated test items harden the seams those fixes create. P4 maintainability is mostly behavior-preserving extraction that gets *safer* once P3 coverage exists. P5 is independent and can run in parallel by a separate contributor.

---

## Master roadmap table

Effort: **S** ≈ ≤0.5d, **M** ≈ 1–3d, **L** ≈ ≥1wk. Risk/Impact: Low/Med/High.

### P0 — Critical Security

| # | Item | Files | Effort | Risk | Impact | Depends on / Sequencing |
|---|------|-------|--------|------|--------|--------------------------|
| P0.1 | **Anchor the audit chain off-DB + HMAC it.** Export chain-head hash to an append-only witness file (0600) at each launch & on each append; HMAC the chain with a key staff do not hold so a delete-then-`rechain_audit` is detectable. Audit every `rechain_audit` invocation. | `db/audit.py:61` (`verify_audit_chain`), `:95` (`rechain_audit`), `app.py:200-209` | M | Med | High | **Must be preceded by P3.1** (write the verifier tests first so the new anchoring can't regress detection). Compat: append-only, no schema break. |
| P0.2 | **Encrypt the Secret Service session.** Negotiate `dh-ietf1024-sha256-aes128-cbc-pkcs7` instead of `OpenSession('plain')` so the master DB passphrase stops crossing the session bus in cleartext. | `db/keyvault.py:44-56,88,133` | M | Med | High | Needs **P3.6** (keyvault round-trip tests with mocked D-Bus) landed first so the crypto change is regression-covered. Compat: only the transport changes; stored secret format unchanged. |
| P0.3 | **Pin SQLCipher KDF/cipher params + assert them.** Set `PRAGMA kdf_iter (>=256000)` and explicit cipher settings right after `PRAGMA key`, and assert in `_assert_cipher_active` so a substituted header can't silently weaken encryption. | `db/connection.py:88-93`, `db/_driver.py:24-31` | S | **High** | High | Sequence carefully: **must round-trip existing encrypted DBs.** Test open of a DB created with old defaults *and* rekey path before shipping. Leans on existing encryption tests (rekey round-trip) + add an explicit kdf-iter assertion test. |
| P0.4 | **Scrub PII from plaintext fallback/crash logs.** Remove/redact patient names + lab numbers from `audit_fallback.log` and crash logs (or encrypt them). | `db/audit.py:18-28`, `app.py:200-209` | S | Low | Med | Independent. After P0.1 (same files). |

### P1 — Data Integrity

| # | Item | Files | Effort | Risk | Impact | Depends on / Sequencing |
|---|------|-------|--------|------|--------|--------------------------|
| P1.1 | **Consolidate the three reference-range resolvers** into one shared pure function consumed by HTML renderer, vector renderer, and worklist UI. Clinically load-bearing; three impls can silently diverge between screen and print. | `report/formatting.py:57` (`_resolve_ref`), `render/report_doc.py:189` (`_ref_lines`), `ui/worklist.py:33` (`resolve_ref`) | M | Med | High | **Pairs with P3 golden tests.** Write a characterization test that pins current output of all three across sex/age edge cases *before* merging, so "no behavior change" is provable. Pure-function extraction = headless-testable. |
| P1.2 | **Money: stop using REAL for currency.** Migrate `receipts`/`ledger` money columns to INTEGER minor units (or TEXT decimal); at minimum `round()` every aggregate and never `SUM()` raw REAL. | `schema.sql:148-153,251,260-261`, `services/billing.py:15` (`compute_bill_totals`) | **L** | **High** | High | **Hard gate: needs P3.3 (billing math tests) FIRST.** Requires an additive migration + read-compat shim for existing float data. Sequence after the billing service tests pin both rounding modes. This is the highest-risk data item; isolate it. |
| P1.3 | **Index the foreign-key columns.** Add indexes in `_ensure_indexes` for `receipts(patient_id)`, `receipts(doctor_id)`, `cultures(receipt_item_id)`, `culture_sensitivity(culture_id)`, `panel_items(test_id)`, `ledger(ref_id)`. SQLite does not auto-index FKs; JOIN/CASCADE do full scans. | `db/connection.py:382-391`, `schema.sql` | S | Low | High | Independent, additive, idempotent (`CREATE INDEX IF NOT EXISTS`). Safe early win. Drop redundant `ix_results_item` (same item). |
| P1.4 | **Wrap lab-number allocation in `BEGIN IMMEDIATE`.** Take the write lock before the MAX-read so two terminals don't collide & retry up to 500×. Correctness already safe via the unique partial index; this removes the retry storm. | `ui/reception.py:743-767` | S | Med | Med | **Best done as part of P2.1** (the bill-create extraction) — the allocation moves into the service where the transaction boundary naturally belongs. If P2.1 is deferred, do this in place first. |
| P1.5 | **Sargable date filters.** Rewrite `date(received_at) BETWEEN ...` as half-open range `received_at >= ? AND received_at < date(?, '+1 day')` so `ix_receipts_date` is used. | `ui/accounts.py:121,143` | S | Low | Med | Independent. Behavior-preserving (same rows, faster). |
| P1.6 | **Add `PRAGMA optimize` / `ANALYZE`.** Run `PRAGMA optimize` on connection close or `ANALYZE` after catalog sync so the planner has statistics. | `db/connection.py` (absent), close path | S | Low | Med | After P1.3 (indexes must exist to be analyzed). Independent otherwise. |
| P1.7 | **Backup WAL checkpoint.** `PRAGMA wal_checkpoint(TRUNCATE)` before backup source reads; document that restore inputs must be checkpointed. | `db/backup.py:16-29,204-208` | S | Med | Med | Independent. Add a backup round-trip test alongside. |

### P2 — Authorization (complete the application layer)

| # | Item | Files | Effort | Risk | Impact | Depends on / Sequencing |
|---|------|-------|--------|------|--------|--------------------------|
| P2.1 | **Extract bill creation into `services/receipts.py:create_receipt(con, dto, *, actor_role, username)`** with `require(...)` + `log_audit` at the boundary, mirroring existing `void_receipt`. Pull patient upsert + receipt insert + lab-no allocation + receipt_items + ledger income credit out of the 206-LOC Qt `save`. | `ui/reception.py:627-784` → `services/receipts.py` | **L** | **High** | High | **First major service extraction.** Sequence: (a) write characterization test of current bill output (P3.3 helps), (b) extract pure persist fn, (c) add `require()` + audit, (d) thin the view to wiring. Absorbs **P1.4**. Establishes the pattern P2.2 follows. |
| P2.2 | **Extract result + culture saving into `services/results.py`** guarded by `require()` (new caps `enter_results`, `finalize_results`); move the `receipts.status='reported'` transition behind the audited boundary. Releasing a wrong result is a patient-safety event. | `ui/worklist.py:425-522`, `ui/microbiology.py:237-270` | **L** | **High** | High | After **P2.1** (reuse the established service+authz pattern) and after **P1.1** (ref-range consolidated, so the worklist no longer owns clinical logic it's about to move). |
| P2.3 | **Move user-management mutations behind `require()`** with dedicated cap `manage_users` (create user, role assign, password reset, enable/disable). Stop overloading `manage_users` as the admin proxy in `worklist.py:308`. Currently gated only by Qt `can()`/page-visibility — any holder of the shared DB key can self-promote to admin. | `ui/settings.py:448,473,777`, `ui/worklist.py:308` | M | Med | High | After **P2.1/P2.2** establish the service+audit idiom. Pairs with **P0.1** (role changes must be audited and anchored). |
| P2.4 | **Route all UI reads through `db/` query functions.** Remove raw SQL strings and the `sqlite3` driver-type import from views (13/19 UI files, 241 call-sites) so presentation stops knowing the engine. | `ui/reception.py:5`, `ui/receipts.py:5`, `ui/doctors.py:130`, `ui/dashboard.py:66`, `ui/logs.py:145`, + others | **L** | Med | Med | Incremental, **one UI file at a time**, after the write paths (P2.1–P2.3) are extracted. Behavior-preserving. Lowest-risk slice of the layering fix; can run in background between higher items. |
| P2.5 | **Document the trust boundary.** Add an explicit "where the rules live / single shared key = `require()` is defence-in-depth only" note. Until the service layer is complete, warn contributors not to copy the inline-UI mutation pattern. | `audit/04-*.md` follow-up → `docs/DEVELOPING.md`, `roles.py` header | S | Low | Med | Anytime; do it *now* (cheap) so new code stops adding to the debt while P2.1–P2.4 land. |

### P3 — Testability

| # | Item | Files | Effort | Risk | Impact | Depends on / Sequencing |
|---|------|-------|--------|------|--------|--------------------------|
| P3.1 | **Test the audit-chain verifier.** Mutate/delete a middle `audit_log` row → assert `verify_audit_chain` returns `(False, bad_id)`; assert NULL-hash-after-chaining flagged; assert `rechain_audit` keeps chain valid after authorized purge. Tamper-evidence currently has **zero** tests. | `db/audit.py:61,95` ; `tests/` | M | Low | High | **Prereq for P0.1.** Do this *first* in the whole program — it's cheap, headless, and unblocks the audit hardening. |
| P3.2 | **Test report HMAC verification codes.** Deterministic across reprints; changes when a result value/hidden flag/sensitivity changes; `verify()` accepts case/space/separator variants & rejects altered codes; empty report → `''`. | `report/verify.py:44-90` ; `tests/` | M | Low | High | **Prereq for P1.1** (consolidating ref-ranges touches report content; the code must stay stable). Independent otherwise. |
| P3.3 | **Test billing money math** across both rounding modes: `round_to_paisa` T/F, discount %, net/due/change non-negative clamps, 100% discount, overpayment change, float edges; promo expiry & malformed-promo clamp to [0,100]. | `services/billing.py:15,58` ; `tests/` | M | Low | High | **Hard prereq for P1.2 (money migration)** and **P2.1 (bill create)**. Pin behavior before either touches money. |
| P3.4 | **Test patient-ID check-letters.** Format/validate round-trip over a seq range; check-letter correctness; single-digit & transposition rejection; year handling. A format/collision bug mislabels specimens. | `db/patient_id.py:22-41` ; `tests/` | S | Low | Med | Independent. Quick win. |
| P3.5 | **Test WhatsApp SSRF guards.** Reject non-http(s)/loopback/private/link-local; block cross-host redirect; normalize/reject phone numbers; sanitize filenames. Largest untested file (512 LOC), SSRF + PII surface. | `whatsapp.py:73,147,163,176,195,288` ; `tests/` | M | Low | High | **Prereq for P4.4** (gateway-response dedup) — pin behavior before extracting the shared handler. |
| P3.6 | **Test keyvault round-trip** (store→load→clear, error paths return False/None without raising) with mocked Secret Service/D-Bus. | `db/keyvault.py:59-142` ; `tests/` | M | Med | Med | **Prereq for P0.2** (encrypted-session change). Risk = D-Bus mocking infra. |
| P3.7 | **Add coverage instrumentation + CI gates** (pytest-cov, per-tier `--cov-fail-under`, Critical files ≥95%), add a ruff CI job, make `LABDESK_SELFTEST` assertive. *(Requires package-install permission — out of audit scope; flag for owner.)* | `.github/workflows/ci.yml`, `pyproject.toml` | S | Low | High | After P3.1–P3.6 exist (so the gate has something to enforce). **Blocked on install permission.** |
| P3.8 | **Golden-PDF + GUI-flow regressions** for receipt/report layout, worklist result entry, settings save, microbiology, logs integrity indicator. | `tests/test_gui_e2e.py` ; `ui/*` | L | Low | Med | After P1.1 / P2.1 / P2.2 stabilize the rendered output and write paths. Lowest test priority. |

### P4 — Maintainability

| # | Item | Files | Effort | Risk | Impact | Depends on / Sequencing |
|---|------|-------|--------|------|--------|--------------------------|
| P4.1 | **Introduce frozen `User(id, name, role)` dataclass** replacing the stringly-typed dict accessed in 78 places (35 are `["role"]`). Eliminates KeyError-on-typo and makes capability checks type-checked. | `ui/*` (global), `roles.py` | M | Low | Med | **Do early in P4** — it ripples through every page, so land it before the god-class splits (P4.2) to avoid double-touching. Behavior-preserving. |
| P4.2 | **Split the four god-page classes** along responsibilities. `SettingsPage` (988 LOC/42m → tabbed sub-pages: general/WhatsApp/backup/theme/users/licensing, none >~250 LOC); `ReceptionPage` (857), `ReceiptsPage` (736), `WorklistPage` (567). Extract `_build_<section>()` helpers from god-constructors. | `ui/settings.py:62`, `ui/reception.py:56`, `ui/receipts.py:53`, `ui/worklist.py:42` | **L** | Med | High | **Reception & Worklist splits should follow P2.1/P2.2** (business logic already moved to services, so the split is pure view decomposition). Settings split can start after **P2.3** (user mutations) lands. **Needs P3.8 GUI tests** as a safety net. One page at a time. |
| P4.3 | **Decompose extreme-complexity methods.** `app.run` (CC 39/195 LOC) → bootstrap steps (single-instance/splash/license/theme/unlock); `ReceptionPage.save` (CC 38/206 LOC) → `validate()/resolve_patient_identity()/persist()/print()`. | `app.py:289`, `ui/reception.py:627` | M | Med | High | `ReceptionPage.save` decomposition **is largely absorbed by P2.1**. `app.run` is independent — do after a smoke/bootstrap test exists. |
| P4.4 | **Extract shared `_interpret_gateway_reply(status, body, number)`** from the ~40 duplicated lines across `send_pdf`/`send_text`. | `whatsapp.py:322-365` vs `:466-...` | S | Low | Med | **After P3.5** (SSRF/gateway tests pin behavior). |
| P4.5 | **Replace the `(con, user)` data clump** in 11 UI classes with a single `AppContext`/`Session` object. | `ui/dashboard.py:13`, `doctors.py:73`, `logs.py:86`, `worklist.py:43`, `accounts.py:30`, `microbiology.py:30`, `receipts.py:54`, `main_window.py:68`, `settings.py:63`, `catalog.py:266` | M | Low | Med | **Combine with P4.1** — both touch every page constructor; do them in one sweep to avoid re-churning the same lines. |
| P4.6 | **Add a real ruff config** (`select` E,F,W,C90,B,SIM,PLR,N,UP + line-length + per-file ignores for `ui/widgets.py` Qt naming and `licensing/_ed25519.py` crypto naming). Remove the 5 stale `RUF100` noqa directives. | `pyproject.toml`/`ruff.toml`; `db/__init__.py:19-28`, `db/_driver.py:25,29`, `ui/receipts.py:412,465`, `ui/widgets.py:43-71` | S | Low | Med | **Do early** (cheap, makes all later P4 work measurable). Land before the god-class splits so new code is linted. The 777-finding backlog is then burned down incrementally, file-by-file, behind the config. |
| P4.7 | **Break the `render⇄report` module-level cycle** (make `report→render` one-way or factor shared types into a leaf module) and the `whatsapp→report` inversion (inject a `build_pdf` callable). Resolve the `db.connection⇄db.backup` local-import dodge. | `render/__init__.py:20`, `report/__init__.py:24-26`, `whatsapp.py:390`, `db/connection.py:246`, `db/backup.py:181` | M | Med | Med | **Late** — only matters if render/report are ever extracted. After P1.1 (ref-range merge changes report/render coupling anyway). Low urgency; risk of import-order breakage. |
| P4.8 | **Hot-path performance** (behavior-preserving): settings cache per report build; cache decoded/autocropped logo per build; collapse cumulative-history N+1 to one `IN (...)` query; collapse per-item `is_culture` N+1; lazy-construct main-window pages; defer `urllib/http.client/ssl` imports in `whatsapp.py`. | `render/report_doc.py:36-110,519-524`, `report/content.py:21,100-148`, `render/primitives.py:204-217`, `ui/main_window.py:135-146`, `whatsapp.py:23-24` | M | Low | Med | **After P3.8 golden-PDF tests** (output must be byte-stable to prove "no behavior change"). The N+1 collapses pair naturally with the **P1.3 indexes** and **Database N+1** items. Independent of the authz track. |
| P4.9 | **Replace silent `try/except/pass`** with `contextlib.suppress(SpecificError)` + debug logging; modernize `%`-format to f-strings. | `app.py:178,225`, `db/connection.py:93,224,257,284,393`, `ui/main_window.py:276` | S | Low | Low | Independent, anytime. In a medical system, do not let these mask failures. |

### P5 — UX (parallel track, independent owner)

| # | Item | Files | Effort | Risk | Impact | Depends on / Sequencing |
|---|------|-------|--------|------|--------|--------------------------|
| P5.1 | **Add accessible names/descriptions** to all inputs & icon-only buttons (×, lock, +Add); give Reception/Worklist grid fields real labels / `setBuddy`. | `ui/*` (global), `reception.py:593-602`, `login.py:53-61` | M | Low | High | Independent of all backend tracks. Largest UX gap. |
| P5.2 | **Non-colour cue for out-of-range results** (▲/▼ glyph or H/L tag) alongside the red/amber text. Clinical signalling must not be colour-only. | `ui/worklist.py:385-394` | S | Low | High | Should land **after/with P4.2 Worklist split** (same file) to avoid conflicts; pairs with **P5.5**. |
| P5.3 | **Explicit tab order + keyboard-operable stat cards / glyph buttons.** | `ui/*` (0 `setTabOrder`), `widgets.py:295-314` | M | Low | Med | After P5.1 (same accessibility sweep). |
| P5.4 | **Fix dark-mode contrast leaks** — replace inline grey hex with theme muted token / `QLabel#muted`. | `ui/activation.py:66`, `ui/settings.py:576` | S | Low | Med | `settings.py` item coordinates with **P4.2** Settings split. |
| P5.5 | **Flow & discoverability**: "Save & print report" bridge on Worklist; group the 12-button Receipts bar under split/icon menus with inline disabled-reasons; surface Alt+1..9 nav in-app. | `ui/worklist.py:136-142`, `ui/receipts.py:88-139,333-334`, `main_window.py:195-196` | M | Med | Med | After **P4.2** (Receipts/Worklist splits) so the action bars are restructured once. |
| P5.6 | **Login/Unlock & setup polish**: show-password + Caps-Lock cue; replace forced-change `QInputDialog` chain with inline form; step/section the setup wizard with focus-on-error. | `ui/login.py:58-61,127-154`, `unlock.py:51-56`, `setup_wizard.py:74-222` | M | Low | Med | Independent. Coordinate `login.py` change with **P0** nothing (no overlap). |

---

## Execution sequence (recommended order of landing)

The bands are priorities, **not** strict serial phases — testability (P3) is *pulled forward* to unblock the security/integrity fixes that depend on it. Recommended landing order:

**Wave 0 — cheap unblockers & safety nets (parallelizable, low risk)**
1. **P3.1** audit-verifier tests → unblocks P0.1
2. **P3.3** billing-math tests → unblocks P1.2 & P2.1
3. **P3.2** HMAC-code tests, **P3.4** check-letter tests, **P3.5** SSRF tests, **P3.6** keyvault tests
4. **P4.6** ruff config + **P1.3** FK indexes + **P1.5** sargable dates + **P1.6** ANALYZE + **P2.5** trust-boundary doc — all small, additive, safe wins
5. **P3.7** coverage CI gate *(blocked on install permission — escalate to owner)*

**Wave 1 — P0 critical security** (each preceded by its Wave-0 test)
6. **P0.1** audit anchoring/HMAC → **P0.3** SQLCipher pinning (highest-risk; round-trip old DBs) → **P0.2** encrypted D-Bus session → **P0.4** PII log scrub

**Wave 2 — P1 data integrity**
7. **P1.1** consolidate reference-range resolvers (with characterization tests)
8. **P1.4**/**P1.7** lab-no `BEGIN IMMEDIATE` (or fold into P2.1) + backup checkpoint
9. **P1.2** money-as-integer migration — **isolate; highest data risk; behind P3.3**

**Wave 3 — P2 authorization (the architectural spine)**
10. **P2.1** `create_receipt` service (absorbs P1.4, P4.3 save-decomp) → **P2.2** `results` service → **P2.3** user-mgmt behind `require()` → **P2.4** route reads through `db/` queries (one UI file at a time)

**Wave 4 — P4 maintainability** (now safe atop P3 coverage + P2 service seams)
11. **P4.1**+**P4.5** `User` dataclass & `AppContext` sweep (one pass) → **P4.2** god-class splits (Reception/Worklist after their services exist) → **P4.3** `app.run` decomposition → **P4.4** gateway dedup → **P4.8** hot-path perf (behind golden PDFs) → **P4.7** cycle breaking → **P4.9** suppress/f-string cleanup → burn down the 777-finding ruff backlog file-by-file

**Wave 5 — P3.8 golden/GUI regression suite** (lock the now-stable output) — note P3.8 also gates P4.2/P4.8, so seed it incrementally during Wave 4.

**Parallel track — P5 UX** (separate contributor, independent of Waves 1–4; coordinate only the `settings.py`/`worklist.py`/`receipts.py` edits with the P4.2 splits)

---

## Target architecture (the destination these waves walk toward)

```
presentation/   ui/*  — thin Qt views: wiring + AppContext + User dataclass only. NO SQL, NO require(), NO money math.
      │ (calls)
application/    services/{receipts,results,billing,users}.py — every mutation behind require()+log_audit; DTOs in, no Qt.
      │ (calls)
domain/         pure rules: ONE reference-range resolver, billing totals, patient-id, check-letters — headless, fully tested.
      │ (calls)
infrastructure/ db/ (repository/query fns, no engine leak upward), whatsapp (build_pdf injected), render/report (one-way).
security/       roles.require() enforced at the application boundary, not the view; User/Session as the only auth carrier.
audit/          SHA-256 chain HMAC'd + off-DB anchored; every privileged service call logs; rechain is itself audited.
```

**How the waves map onto it:**
- **P0** hardens the *security/audit* corners (anchored, HMAC'd chain; pinned crypto; encrypted secret transport).
- **P1** restores *domain* correctness (single ref-range resolver, integer money, indexed/sargable persistence).
- **P2** builds the *application* layer and makes `require()` the real boundary, draining logic out of *presentation*.
- **P3** gives every *domain*/*infrastructure* seam a regression net so the moves are provably safe.
- **P4** finishes *presentation* (thin views, `User`/`AppContext`, no engine leak) and de-cycles *infrastructure*.
- **P5** makes the *presentation* layer accessible and discoverable — orthogonal, parallelizable.

Each item is independently shippable, behavior-preserving where it is a refactor, and keeps `pytest -q` green; no item breaks DB/license/audit compatibility without an additive, round-trip-tested migration.
