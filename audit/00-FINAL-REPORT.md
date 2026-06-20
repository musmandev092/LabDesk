# LabDesk — Final Audit Report (Capstone)

**System:** LabDesk — Linux desktop Laboratory Information System (LIS)
**Domain:** Sensitive medical, financial, and patient data — Business criticality **HIGH**
**Stack:** Python 3.13, PySide6 (Qt), SQLCipher SQLite, Nuitka, DBus/XDG portals, jeepney, self-hosted WhatsApp (wuzapi/whatsmeow) gateway, Ed25519 licensing, SHA-256 audit chain
**Size:** ~15,500 LOC across 82 Python files
**Audit type:** READ-ONLY. No source/test/config modified. 11 specialist reports synthesized.
**Date:** 2026-06-16

---

## 1. Executive Summary

> Audience: lab owner and engineering lead.

LabDesk is a **solid, security-conscious desktop LIS** that is meaningfully better engineered than the median single-site medical app. It does the hard things right: SQLCipher encryption is **fail-closed** (refuses to open an unencrypted patient DB), passwords use **scrypt with constant-time verify**, the licensing is a **vendored RFC-8032 Ed25519** scheme that resists copying and clock-rollback, the report layer carries an **HMAC verification code**, history is **snapshotted onto receipts/results** so past reports never silently change, and a **SHA-256 audit chain** provides tamper-evidence. The test suite (56 passing, ~22.6s) is small but adversarially smart in the areas it covers. There are **zero Critical security findings** in the classic sense — no SQL injection, no `eval`/`pickle`, no shell-string subprocess, no embedded private key.

The system is held back by **one structural theme that recurs across every specialist report**: the application's most important write paths — **bill creation** (`ui/reception.py:627`) and **clinical result release** (`ui/worklist.py:425`, `ui/microbiology.py:237`) — run full multi-table financial/clinical transactions **inline inside Qt widgets, with no service boundary and, critically, no `require()` authorization gate**. A service layer with `require()`+audit *was* built, but only for the cheaper mutations (void, due-payment, panel edits); the dangerous create/result paths were left behind (verified: `services/receipts.py:27` calls `require()`; `reception.save` and `worklist.save_results` do not). This creates a **false sense of where the rules live** and means the invariant "all mutations are authorized at an audited boundary" is **untrue for ~70% of the most important writes**. Compounding it: all data, the RBAC role table, and the audit chain share **one SQLCipher DB under one passphrase every staff member must know**, and the audit chain head is never anchored off-DB — so a key-holder can edit their own role or delete-and-rechain the log undetected.

The remaining issues are **localized and fixable, not systemic rot**: four UI god-classes (Settings 988 LOC, Reception 857, Receipts 736), foreign-key columns that are never indexed (full scans on the fastest-growing tables), money stored as floating-point `REAL` (sub-cent drift), N+1 query loops on the two hottest paths, and a critical **test gap** — the audit-chain verifier, the report HMAC, and the billing math all have **0% coverage**, i.e. the three features whose entire purpose is trust are unproven.

**Bottom line:** No fire to put out today; the encryption, licensing, and audit primitives are sound. But before this scales to multi-terminal or multi-site, two things are non-negotiable: (1) route bill-create and result-release through an **authorized, audited service boundary**, and (2) **anchor the audit chain off-DB** and **add tests** for the audit/HMAC/billing trust features. The refactor roadmap (`audit/12-refactor-roadmap.md`) sequences this safely in 5 waves with tests kept green throughout.

---

## 2. Scorecard

| Dimension | Grade | Justification |
|---|---|---|
| **Architecture** | **C** | Clean *packaging* by role and a well-layered `db` package, but the core rule is broken: domain + transaction logic lives in Qt views (241 connection call-sites across 13/19 UI files); dependency direction is inverted (`report→db`, `whatsapp→report`). |
| **Security** | **B** | Excellent crypto primitives and fail-closed posture, zero Criticals — but `require()` is bypassed for user-mgmt and result entry (UI-only `can()` gating), and one shared DB passphrase gives every user write access to role/audit tables with no off-DB anchor. |
| **Maintainability** | **C+** | Hygiene is clean (ruff F-rules pass, high-quality comments) but four 526–988 LOC god-classes, CC up to 39 (`app.run`, `ReceptionPage.save`), stringly-typed `user` dict (78 sites), and no ruff config (777 latent findings). |
| **Performance** | **B** | Well-tuned DB (WAL, indexes, LIMIT, debounce, off-thread PDF). Held back by per-page settings re-query, per-page logo re-decode, nested N+1 patient history, eager page construction, and unindexed FK joins. |
| **Testability** | **C+** | 56 green tests, smart where they exist; but the trust features — audit verifier, report HMAC, billing math, patient-ID check-letters, WhatsApp SSRF — are **0% covered**, no coverage gate. Critical-path coverage ~65% vs >95% target. |
| **Documentation** | **B+** | Unusually strong operator/vendor docs (README, WHATSAPP_SETUP) verified against source; excellent per-file docstrings. Gap is the inverse of most projects: no consolidated architecture/schema/onboarding reference; a few stale map entries. |
| **Technical Debt** | **C+** | Concentrated and *named*, not sprawling: the unfinished service-extraction seam, UI god-classes, FK-index/money-type data debt, and the test gap. All localized and addressable incrementally. |
| **Overall** | **B-** | A genuinely well-secured, well-documented LIS with sound cryptographic and data-integrity foundations, pulled down from a B+ by one repeated architectural gap (unaudited inline UI mutations + shared-key trust model) and a critical test gap on the very features that establish trust. Not shippable to multi-terminal until the authz boundary and audit anchor land; safe and competent for the current single-site deployment. |

---

## 3. Top 25 Risks (severity-ranked)

1. **[Critical] Bill-creation financial transaction runs inline in a Qt widget with no service boundary or `require()` gate** — `ui/reception.py:627-784`. Patient upsert + receipt + lab-number allocation + receipt_items + ledger income credit, all in the view. Any code path or shared-key user bypasses authorization on money writes.
2. **[Critical] Clinical result + culture release performed inline in views with no authorized/audited boundary** — `ui/worklist.py:425-522`, `ui/microbiology.py:237-270`. Releasing a wrong result is a patient-safety event; it must pass one audited gate, not the UI's `can()`.
3. **[Critical] Audit-chain integrity verifier has zero tests** — `db/audit.py:61 verify_audit_chain`, `:95 rechain_audit`. The tamper-evidence feature's entire purpose is unproven; no test asserts the SHA-256 chain detects a mutated/deleted row.
4. **[Critical] Report forensic HMAC verification codes entirely untested** — `report/verify.py:44-90`. A forgeable/incorrect verification code on a medical report is a medical-legal liability.
5. **[High] Audit hash chain is forgeable: head never anchored off-DB** — `db/audit.py:95-111`. `rechain_audit()` rewrites a self-consistent chain that `verify_audit_chain` accepts; delete-then-rechain leaves no record of what was purged.
6. **[High] One shared SQLCipher passphrase = no server-side trust boundary** — `roles.py:65-77`, `db/audit.py:95-111`, `schema.sql:25`. Every staff member holds the key and can directly edit `role`, `audit_log`, or `failed_attempts`. `require()` is defence-in-depth only.
7. **[High] User-management + result mutations authorized only in the Qt UI (`can()`), not the data-layer `require()`** — `ui/settings.py:448,473,777`, `ui/worklist.py:425-485`. A lower-privilege user with the shared key can set their own role to admin.
8. **[High] Half-finished service extraction creates a false rules boundary** — `services/receipts.py:27` gates void with `require()`; `reception.save:627` and `worklist.save_results:425` do not (verified inline `con.execute`). New engineers will copy the unaudited pattern.
9. **[High] Foreign-key columns never indexed — full scans on JOIN and ON DELETE CASCADE** — `schema.sql` FK cols vs `db/connection.py:382-391`. Missing: `receipts(patient_id)`, `receipts(doctor_id)`, `cultures(receipt_item_id)`, `culture_sensitivity(culture_id)`, `panel_items(test_id)`, `ledger(ref_id)` on the fastest-growing tables.
10. **[High] Billing money math untested across both rounding modes** — `services/billing.py:15 compute_bill_totals`, `:58 get_active_promo_discount`. Two call sites with different rounding is exactly where money bugs hide; no regression net.
11. **[High] Money stored as floating-point `REAL` across receipts and ledger** — `schema.sql:148-153,251,260-261`. Float can't represent decimal cents; summed ledgers drift sub-cent over time.
12. **[High] N+1 query loops on the two hottest paths** — `ui/worklist.py:326-340` (per-item params+results on result entry), `render/report_doc.py:520` / `report/html.py:192` (per-item `SELECT is_culture`).
13. **[High] Three parallel reference-range resolvers risk clinical divergence** — `report/formatting.py:57`, `render/report_doc.py:189`, `ui/worklist.py:33`. Screen and printed report can silently disagree on high/low flags.
14. **[High] WhatsApp SSRF guards + 512-LOC gateway have no tests** — `whatsapp.py:147,163,176,73,195,288`. Largest untested file; SSRF + patient-PDF/token exfil surface with zero regression net.
15. **[High] Patient-ID check-letter algorithm untested** — `db/patient_id.py:22-41`. A format/collision bug mislabels patient specimens.
16. **[Medium] SQLCipher KDF/cipher params unpinned** — `db/connection.py:88-93`, `db/_driver.py:24-31`. KDF strength depends on linked-version defaults and the attacker-modifiable DB header on open.
17. **[Medium] "Remember password" stores master passphrase over a `plain` (cleartext) D-Bus session** — `db/keyvault.py:44-56,88,133`. The key that unlocks all patient data crosses the session bus sniffable by any process in the login session.
18. **[Medium] Lab-number allocation not wrapped in `BEGIN IMMEDIATE`** — `ui/reception.py:743-767`. Unique partial index keeps it correct, but two terminals collide and retry up to 500x (cross-terminal storm).
19. **[Medium] `date(received_at) BETWEEN` defeats `ix_receipts_date`** — `ui/accounts.py:121,143`. Wrapping the indexed column forces a full scan on the accounts screen.
20. **[Medium] No ANALYZE / `PRAGMA optimize` — planner runs blind** — absent in `db/connection.py`. Composite/partial indexes may be ignored without statistics.
21. **[Medium] Weak password policy (min 6) and `login` audit row emitted before forced password change** — `ui/login.py:102-104,139-143`, `db/auth.py:54-73`.
22. **[Medium] Report rendering re-queries all ~16 lab settings on every page** — `render/report_doc.py:36-110`, `report/content.py:21`. A 5-page report issues ~80 redundant single-row settings queries.
23. **[Medium] Nested N+1 building cumulative patient-history columns** — `report/content.py:100-148`. Per item: 1 prior-visits query + 1 query per prior visit (M×9).
24. **[Medium] No consolidated architecture/schema reference; `schema.sql` alone is incomplete** — true shape = `schema.sql` + `db/_config.py::_EXTRA_COLUMNS`. Engineers trusting `schema.sql` get the wrong table shape.
25. **[Low] Patient PII written to plaintext fallback/crash logs outside the encrypted DB** — `db/audit.py:18-28`, `app.py:200-209`. Files are 0600/0700 but PII is unencrypted on disk.

---

## 4. Top 25 Fixes (ranked by value/effort)

1. **Add the six missing FK indexes** in `_ensure_indexes` (`db/connection.py:382`): `receipts(patient_id)`, `receipts(doctor_id)`, `cultures(receipt_item_id)`, `culture_sensitivity(culture_id)`, `panel_items(test_id)`, `ledger(ref_id)`. *(S effort, high impact — kills full scans/cascades.)*
2. **Write P0 audit-verifier tests** — `db/audit.py:61,95`: log rows, mutate/delete a middle row, assert `verify_audit_chain → (False, bad_id)`; assert rechain keeps validity after authorized purge.
3. **Write P0 report-HMAC tests** — `report/verify.py:44-90`: deterministic across reprints, changes on result/flag/sensitivity edit, `verify()` accepts separator variants and rejects altered codes.
4. **Write P0 billing-math tests** — `services/billing.py:15,58`: both rounding modes, discount %, 100% discount, overpayment change, promo expiry, clamp to [0,100].
5. **Extract `create_receipt(con, dto, *, actor_role, username)` into `services/receipts.py`** with `require()` + `log_audit`, mirroring `void_receipt` — drains `reception.save:627-784`.
6. **Extract `services/results.py` for result/culture writes + `status='reported'` transition** behind `require()` — covers `worklist.py:425`, `microbiology.py:237`.
7. **Anchor the audit chain head off-DB at each launch** — `db/audit.py`: export/HMAC the head to an append-only witness staff don't control; audit `rechain` invocations.
8. **Consolidate the three reference-range resolvers** into one shared function in `report.formatting` consumed by HTML renderer, vector renderer, and worklist UI (`report/formatting.py:57`, `render/report_doc.py:189`, `ui/worklist.py:33`).
9. **Move user-mgmt mutations behind `require()`** with `manage_users`/role-change auditing — `ui/settings.py:448,473,777`; stop overloading `manage_users` as the admin proxy in `worklist.py:308`.
10. **Load all settings once per report build** into a dict and pass it down — `render/report_doc.py:36-110` — removes ~80 redundant per-page queries.
11. **Batch the result-entry / report N+1 queries** with `WHERE receipt_item_id IN (...)` — `worklist.py:326-340`, `report_doc.py:520`, `report/html.py:192`.
12. **Wrap lab-number allocation in `BEGIN IMMEDIATE`** — `ui/reception.py:743-767`.
13. **Rewrite accounts date filter as a sargable half-open range** (`received_at >= ? AND received_at < date(?, '+1 day')`) — `ui/accounts.py:121,143`; the pattern already exists in `_config.RECEIVED_TODAY`.
14. **Cache the decoded/autocropped logo once per report build** — `render/primitives.py:204-217`, called per page from `report_doc.py:62,72`.
15. **Negotiate an encrypted D-Bus Secret Service session** (dh-ietf1024-sha256-aes128-cbc-pkcs7) instead of `'plain'` — `db/keyvault.py:44-56`.
16. **Pin `PRAGMA kdf_iter (>=256000)` + cipher settings** right after `PRAGMA key` and assert them in `_assert_cipher_active` — `db/connection.py:88-93`.
17. **Add `PRAGMA optimize` on connection close** (or `ANALYZE` after seed sync) — `db/connection.py`.
18. **Add WhatsApp SSRF security tests** — `whatsapp.py:147,163,176,73,195,288`: reject non-http(s)/loopback/private/link-local, block cross-host redirect, sanitize numbers/filenames.
19. **Add patient-ID check-letter tests** — `db/patient_id.py:22-41`: round-trip, transposition/single-digit rejection, year handling.
20. **Add the non-colour out-of-range cue** (▲/▼ or H/L) beside the red/amber text — `ui/worklist.py:385-394` (colour-blind safety on a clinical signal).
21. **Batch cumulative patient-history into one `IN (...)` query** and bucket in Python — `report/content.py:100-148`.
22. **Defer `urllib/http.client/ssl` imports into the WhatsApp send functions** — `whatsapp.py:23-24` — removes ~30ms from every cold start.
23. **Lazy-construct main-window pages on first navigation** — `ui/main_window.py:135-146` — cuts login latency + idle memory.
24. **Add `setAccessibleName`/`setBuddy`** to inputs and icon-only buttons (×, lock, +Add) — global `ui/`, esp. `reception.py:593-602`, `login.py:53-61`.
25. **Add a `[tool.ruff]` config** with `select = E,F,W,C90,B,SIM,PLR,N,UP`, line-length, and per-file ignores for `ui/widgets.py` (Qt naming) and `licensing/_ed25519.py` (crypto spec) — surfaces 777 latent findings meaningfully.

---

## 5. Top 25 Refactors

1. **Complete the application layer**: route ALL receipt/result mutations through `services/` with `require()`+`log_audit` — `services/receipts.py` vs `ui/reception.py:627`, `ui/receipts.py:600`.
2. **Extract `services/receipts.py:create_receipt`** from `ReceptionPage.save` (206 LOC, CC 38) — `ui/reception.py:627`.
3. **Extract `services/results.py`** from `worklist.save_results`/`microbiology` — `ui/worklist.py:425`, `ui/microbiology.py:237`.
4. **Split `SettingsPage`** (988 LOC, 42 methods) into tabbed per-card widgets (General/WhatsApp/Backup/Users/Licensing/Security), none >~250 LOC — `ui/settings.py:62`.
5. **Split `ReceptionPage`** (857 LOC) along construction/validation/business/DB/print — `ui/reception.py:56`.
6. **Split `ReceiptsPage`** (736 LOC, 30 methods) — `ui/receipts.py:53`.
7. **Split `WorklistPage`** (567 LOC) — `ui/worklist.py:42`.
8. **Decompose `app.run`** (CC 39, 195 LOC) into bootstrap steps: single-instance, splash, license, theme, unlock — `app.py:289`.
9. **Decompose `ReceptionPage.save`** into `validate()`/`resolve_patient_identity()`/`persist()`/`print()` — `ui/reception.py:627`.
10. **Introduce a frozen `User(id, name, role)` dataclass** to replace the 78 stringly-typed `self.user["..."]` accesses — global `ui/`.
11. **Introduce an `AppContext`/`Session` object** to replace the `(con, user)` data clump in 11 UI classes — `ui/dashboard.py:13`, `doctors.py:73`, `logs.py:86`, etc.
12. **Route all reads through repository/query functions** in `db/`/`services/`; remove raw SQL + `sqlite3` imports from views (241 call-sites, 13/19 UI files) — `ui/reception.py:5`, `receipts.py:5`, `doctors.py:130`, etc.
13. **Break the `render⇄report` module-level cycle**: make `report` depend on `render` one-way or factor shared types into a leaf module — `render/__init__.py:20`, `report/__init__.py:24-26`.
14. **Invert the `whatsapp→report` dependency**: inject a `build_pdf` callable into the gateway instead of importing `report` — `whatsapp.py:390`.
15. **Invert the `report→db` dependency**: introduce a repository/port so `report` receives DTOs — `report/content.py:9`, `report/export.py:12`, `report/verify.py:22`.
16. **Extract `_interpret_gateway_reply(status, body, number)`** shared by `send_pdf` and `send_text` (~40 duplicated lines) — `whatsapp.py:294,451`.
17. **Promote magic literals to named constants** (pixel sizes, crypto sizes) — `render/image.py:26-41`, `licensing/_ed25519.py:105-148`.
18. **Pass render primitives a geometry/style struct** instead of 8–11 positional args — `render/_shared.py:79`, `render/primitives.py:163`.
19. **Resolve the `db.connection⇄db.backup` responsibility split** so local-import cycle-breakers are unnecessary — `db/connection.py:246`, `db/backup.py:181`.
20. **Reduce the 70-symbol flat `db` facade** used as an ambient service-locator; pass explicit collaborators — `db/__init__.py:119-189`.
21. **Migrate money from `REAL` to INTEGER minor units (or TEXT decimal)** with an additive, round-trip-tested migration — `schema.sql:148-153,251,260-261`.
22. **Drop the redundant `ix_results_item`** (covered by the `UNIQUE(receipt_item_id,parameter_id)` autoindex) to cut write amplification on the hottest table — `db/connection.py:384`.
23. **Replace 14 silent `try/except/pass`** with `contextlib.suppress(SpecificError)` + debug logging — `app.py:178,225`, `db/connection.py:393`, `ui/main_window.py:276`.
24. **Modernize `%`-format strings to f-strings** (UP031) — `db/connection.py:93,224,257,284`.
25. **Remove stale `# noqa` directives** for non-enabled rules (5× RUF100) — `db/__init__.py:19-28`, `db/_driver.py:25,29`, `ui/receipts.py:412,465`, `ui/widgets.py:43-71`.

---

## 6. Top 25 Security Improvements

1. **Route bill-create through `require()`+audit** at a service boundary — `ui/reception.py:627`.
2. **Route result/culture release through `require()`+audit** with `enter_results`/`finalize_results` capabilities — `ui/worklist.py:425`, `ui/microbiology.py:237`.
3. **Move user CRUD/role-assignment/password-reset/enable-disable behind `require(manage_users)`** in the data layer; audit every role change — `ui/settings.py:448,473,777`.
4. **Stop overloading `manage_users` as the admin proxy** for result finalization — `ui/worklist.py:308`.
5. **Anchor the audit chain head off-DB** at each launch (append-only witness) — `db/audit.py:95-111`.
6. **HMAC the audit chain with a key staff do not hold** so delete-then-rechain is detectable — `db/audit.py:95-111`.
7. **Audit `rechain_audit` invocations themselves** so purges leave a record — `db/audit.py:95`.
8. **Document the trust boundary explicitly**: one shared key = every user can touch role/audit; `require()` is defence-in-depth only — `roles.py:65-77`, `schema.sql:25`.
9. **Pin `PRAGMA kdf_iter (>=256000)` + cipher params** and assert in `_assert_cipher_active` — `db/connection.py:88-93`, `db/_driver.py:24-31`.
10. **Negotiate an encrypted Secret Service D-Bus session** instead of `OpenSession('plain')` — `db/keyvault.py:44-56,88,133`.
11. **Enforce a real password policy** (>=10 chars, reject common passwords) and raise scrypt N — `db/auth.py:54-73`, `ui/login.py`.
12. **Emit the `login` audit event only after** any required password change completes — `ui/login.py:102-104,139-143`.
13. **Add SSRF unit tests + keep guards**: reject non-http(s)/loopback/private/link-local, block cross-host redirect — `whatsapp.py:147,163,176,73`.
14. **Validate/normalize phone numbers and sanitize filenames** with tests — `whatsapp.py:195,288`.
15. **Scrub or encrypt PII** in `audit_fallback.log` and crash logs — `db/audit.py:18-28`, `app.py:200-209`.
16. **Add report-HMAC tamper tests** (forensic verification code) — `report/verify.py:44-90`.
17. **Add audit-chain tamper-detection tests** — `db/audit.py:61`.
18. **Add keyvault round-trip + error-path tests** (mocked Secret Service) — `db/keyvault.py:59-142`.
19. **Make billing math non-negative-clamp + promo-bounds tested** (defence against negative/over-discount) — `services/billing.py:15,58`.
20. **Wrap lab-number allocation in `BEGIN IMMEDIATE`** to close the concurrent-allocation window — `ui/reception.py:743-767`.
21. **Remove raw `sqlite3` driver imports from views** so the presentation layer can't hand-roll privileged SQL — `ui/reception.py:5`, `receipts.py:5`.
22. **Add patient-ID check-letter tests** to prevent specimen mislabeling — `db/patient_id.py:22-41`.
23. **Keep the offline-license deterrent as designed** but document it as reverse-engineerable (public key + verify logic + rollback HMAC key are local) — `licensing/__init__.py:54-80,134-153`.
24. **Add a ruff `B`/`SIM`/`S`-class lint job in CI** to catch broad excepts and unsafe patterns over time — `pyproject.toml`, `.github/workflows/ci.yml`.
25. **Add a per-tier coverage gate (Critical >=95%)** once package install is permitted, so trust-feature regressions become visible — `.github/workflows/ci.yml`. *(Blocked on install permission; escalated to owner.)*

---

## 7. Top 25 Performance Improvements

1. **Add the six missing FK indexes** — `db/connection.py:382` — eliminates full child-table scans on JOIN/CASCADE.
2. **Cache lab settings once per report build** (~80 redundant queries on a 5-page report) — `render/report_doc.py:36-110`, `report/content.py:21`.
3. **Collapse the cumulative-history nested N+1** into one `IN (...)` query (M×9 → ~M) — `report/content.py:100-148`.
4. **Cache the decoded/autocropped logo once per build** instead of per page — `render/primitives.py:204-217`.
5. **Batch result-entry per-item params+results** into one query — `worklist.py:326-340`.
6. **JOIN `is_culture` into the receipt_items fetch** instead of per-item `SELECT` — `report_doc.py:520`, `report/html.py:192`.
7. **Lazy-construct main-window pages** on first navigation — `ui/main_window.py:135-146` — lower login latency + idle memory.
8. **Defer `urllib/http.client/ssl` imports** into WhatsApp send functions (~30ms off cold start) — `whatsapp.py:23-24`.
9. **Make the accounts date filter sargable** so `ix_receipts_date` is used — `ui/accounts.py:121,143`.
10. **Run `PRAGMA optimize` on close / `ANALYZE` after seed** so the planner has statistics — `db/connection.py`.
11. **Select `is_culture,report_head,method_note` once per item** instead of 2–3× re-query — `report_doc.py:519-524,220,555`.
12. **Replace per-panel test-count queries with one `GROUP BY`** — `ui/catalog.py:352-360`.
13. **Drop the redundant `ix_results_item`** to cut write amplification on the hottest table — `db/connection.py:384`.
14. **Add small picker indexes** `micro_lists(kind)`, `doctors(active)` — `db/connection.py`.
15. **Wrap lab-number allocation in `BEGIN IMMEDIATE`** to avoid up-to-500x retry storms cross-terminal — `ui/reception.py:743-767`.
16. **Bound/pre-filter the audit-log search** (leading-wildcard LIKE + non-sargable `date()` = growing full scan) — `ui/logs.py:142-156`; long-term FTS index.
17. **Checkpoint WAL before backup reads** (`PRAGMA wal_checkpoint(TRUNCATE)`) — `db/backup.py:16-29`.
18. **Memoize `_g` settings getter per report build** — `report/content.py:21`.
19. **Reuse the report font load** (already done once — keep it; verify no per-page reload creeps in) — render layer.
20. **Migrate money to INTEGER minor units** — also removes per-aggregate `round()` overhead and float drift — `schema.sql:148-153`.
21. **Profile and cap eager QObject retention** from god-pages held for the whole session — `ui/main_window.py`.
22. **Add a composite index** to cover the hottest accounts/ledger reporting range once it's sargable — `db/connection.py`.
23. **Batch culture-sensitivity loads** alongside cultures when rendering micro reports — `render/report_doc.py`, `report/content.py`.
24. **Confirm `temp_store=MEMORY`/`synchronous=NORMAL`/WAL stay set** after any rekey/restore path — `db/connection.py`, `db/backup.py`.
25. **Add a golden-PDF/perf smoke** that fails if report-build query count regresses — `tests/`. *(Acts as a regression guard for items 2–6, 11.)*

---

## 8. Top 25 Maintainability Improvements

1. **Introduce a frozen `User` dataclass** to kill 78 stringly-typed `self.user["..."]` accesses (35 are `["role"]`) — global `ui/`.
2. **Introduce `AppContext`/`Session`** to retire the `(con, user)` clump in 11 classes — `ui/dashboard.py:13` et al.
3. **Split `SettingsPage`** (988 LOC) into tabbed sub-widgets — `ui/settings.py:62`.
4. **Split `ReceptionPage`/`ReceiptsPage`/`WorklistPage`** god-classes — `ui/reception.py:56`, `receipts.py:53`, `worklist.py:42`.
5. **Decompose `app.run` (CC 39) and `ReceptionPage.save` (CC 38)** into named steps — `app.py:289`, `ui/reception.py:627`.
6. **Add a `[tool.ruff]` config** (`E,F,W,C90,B,SIM,PLR,N,UP` + line-length + per-file ignores) — surfaces the 777 latent findings — `pyproject.toml`.
7. **Consolidate the three reference-range resolvers** so the clinical rule has one home — `report/formatting.py:57`, `render/report_doc.py:189`, `ui/worklist.py:33`.
8. **Extract the shared WhatsApp gateway-reply interpreter** to stop shotgun surgery — `whatsapp.py:294,451`.
9. **Route SQL through a repository layer** so views stop importing `sqlite3` and embedding SQL (241 sites) — `ui/`.
10. **Write the architecture overview + 20-table schema doc**, prominently noting true shape = `schema.sql` + `_EXTRA_COLUMNS` — `docs/`, vs `schema.sql`, `db/_config.py`.
11. **Add `docs/DEVELOPING.md`** (uv sync, run-from-source, pytest, ruff, layering, env overrides `LABDESK_DATA_DIR/LABDESK_DB_KEY/LABDESK_SELFTEST`) — repo root.
12. **Add a "where the rules actually live" note** to the contributor doc until the service layer is finished (don't copy inline-UI mutations) — `audit/04`, `ui/reception.py`, `ui/worklist.py`.
13. **Break the `render⇄report` cycle** so the packages are independently reusable — `render/__init__.py:20`, `report/__init__.py:24-26`.
14. **Resolve `db.connection⇄db.backup`** so cycle-breaker local imports disappear — `db/connection.py:246`, `db/backup.py:181`.
15. **Trim the 70-symbol `db` facade**; prefer explicit collaborators over service-locator reach-ins — `db/__init__.py:119-189`.
16. **Promote magic literals to named constants** (render pixel + crypto sizes) — `render/image.py:26-41`, `licensing/_ed25519.py:105-148`.
17. **Replace 8–11-arg render primitives** with a geometry/style struct — `render/_shared.py:79`, `render/primitives.py:163`.
18. **Replace 14 silent `try/except/pass`** with `contextlib.suppress(Specific)` + debug logging — `app.py:178,225`, `db/connection.py:393`, `ui/main_window.py:276`.
19. **Remove 5 stale `# noqa` directives** (or enable ruff so they mean something) — `db/__init__.py:19-28`, `ui/receipts.py:412,465`.
20. **Convert the `LABDESK_SELFTEST` page-build smoke into an assertive test** — `.github/workflows/ci.yml`, `app.py`.
21. **Add coverage instrumentation (pytest-cov) + per-tier gates** once install is allowed — `pyproject.toml`. *(Blocked on permission.)*
22. **Fix stale `audit/02-module-map.md` entries**: whatsapp is self-hosted wuzapi/whatsmeow (not Meta Cloud-API); `__init__` exports only `__version__` (not `APP_NAME/APP_VERSION`) — `audit/02-module-map.md` vs `whatsapp.py:1-13`, `__init__.py`.
23. **Mark WeasyPrint as removed** in the `report`/`render` docstrings (native Qt QPainter→QPdfWriter is current) — `report/__init__.py`, `render/__init__.py`.
24. **Keep `scripts/check_version.py` in sync** between `pyproject` version and `labdesk/__init__.py` — `pyproject.toml`, `__init__.py`.
25. **Add golden-PDF + driven-UI-page tests** (settings save/validation, micro culture+sensitivity, logs integrity indicator) so the largest untested views gain a regression net — `tests/test_gui_e2e.py`, `ui/`.

---

## Appendix — Source Reports

| # | Report | Grade |
|---|---|---|
| 01 | System Map (`audit/01-system-map.md`) | B (Discovery) |
| 02 | Module Map (`audit/02-module-map.md`) | — |
| 03 | Dependency Graph (`audit/03-dependency-graph.md`) | — |
| 04 | Architecture Review (`audit/04-architecture-review.md`) | C- |
| 05 | Security Audit (`audit/05-security-audit.md`) | B |
| 06 | Database Review (`audit/06-database-review.md`) | B- |
| 07 | Clean Code Review (`audit/07-clean-code-review.md`) | C+ |
| 08 | Test Report (`audit/08-test-report.md`) | C+ |
| 09 | UX Review (`audit/09-ux-review.md`) | B |
| 10 | Performance Review (`audit/10-performance-review.md`) | B |
| 11 | Documentation Review (`audit/11-documentation-review.md`) | B+ |
| 12 | Refactor Roadmap (`audit/12-refactor-roadmap.md`) | — |

*Key claims spot-verified against source during synthesis: the `require()` authorization gap (`services/receipts.py:27` gates void; `ui/reception.py:627` + `ui/worklist.py:425` do not), unindexed FK columns (`db/connection.py:382-391`), money-as-`REAL` (`schema.sql:148-153`), and the audit verifier shape (`db/audit.py:61`).*
