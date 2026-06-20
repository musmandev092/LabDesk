# LabDesk — QA & Test-Coverage Audit (08)

**Role:** Principal QA Engineer (Agent_QA)
**Scope:** READ-ONLY. Existing test suite assessment + prioritized missing-test backlog.
**Date:** 2026-06-16
**Headline grade:** **C+** (a genuinely good security/licensing/auth core, undermined by zero coverage of several HIGH-criticality modules: audit-chain integrity, report forensic codes, billing math, patient-ID, keyvault, and the entire WhatsApp/SSRF surface.)

---

## 1. Current pytest results (actual run)

```
platform linux -- Python 3.13.14, pytest-9.1.0, pluggy-1.6.0
rootdir: /home/mosman092/Projects/LabDesk
configfile: pyproject.toml   (testpaths = ["tests"], addopts = "-q")
collected 56 items

tests/test_auth.py ....... [7]
tests/test_backup_restore.py ..... [5]
tests/test_catalog_mutations.py ..... [5]
tests/test_connection_encryption.py ....... [7]
tests/test_gui_e2e.py ..... [5]
tests/test_licensing.py ............ [12]
tests/test_receipts_service.py ....... [7]
tests/test_roles.py ..... [5]
tests/test_single_instance.py ... [3]

============================= 56 passed in 22.59s ==============================
```

- **Pass: 56 / Fail: 0 / Skip: 0 / Error: 0**
- **Runtime: ~22.6 s** (slowest are SQLCipher rekey/verify and backup/restore round-trips — 0.5–1.3 s each; offscreen Qt GUI setup ~0.6 s/test).
- **No coverage instrumentation is configured** (`pyproject.toml` has no `pytest-cov`/`--cov`; `addopts = "-q"` only). All percentages below are derived by **call-graph mapping**, not measured line coverage. *Installing `pytest-cov` is not permitted in this audit, so numbers are estimates.*

### CI posture (`.github/workflows/ci.yml`)
- Runs `pytest -q` on push/PR to `main`/`dev` with offscreen Qt — good.
- Adds a **headless self-test** (`LABDESK_SELFTEST=1`, `python -m labdesk`) that builds every UI page — this is a valuable smoke test but produces **no assertions** (only catches import/constructor crashes).
- **No coverage gate, no coverage report, no flake/ruff gate visible in the test job.** A coverage regression cannot be detected by CI today.

---

## 2. What each existing test covers

| Test file | # | Target source module(s) | What it verifies |
|---|---|---|---|
| `test_auth.py` | 7 | `db/auth.py`, `db/crypto.py` | Correct/wrong/unknown-user auth, lockout after max fails, counter reset on success, **legacy SHA256→scrypt upgrade**, corrupt-timestamp lock handling. Strong. |
| `test_connection_encryption.py` | 7 | `db/connection.py`, `db/crypto.py` | DB encrypted on disk, cipher active, `verify_passphrase` accept/reject/empty/plaintext, **fail-closed when encryption unavailable**, **rekey preserves data**. Strong. |
| `test_licensing.py` | 12 | `licensing/__init__.py`, `licensing/_ed25519.py`, `licensing/fingerprint.py` | Valid/tampered/wrong-machine signatures, 1/2/3-signal fingerprint matching tolerance, expiry, **clock-rollback high-water defense**, seen-file tamper ignored, JSON+base64 parse, enforced-default on/off. Excellent. |
| `test_receipts_service.py` | 7 | `services/receipts.py`, `db/queries.py` (`receive_due`) | Void denied for low role, **void reverses ledger**, double-void idempotent, receive-due role-gate, payment records+balances, no-op when nothing owed, mark-delivered role-gate. Good — but only `services/receipts.py`; **billing math untested** (see gaps). |
| `test_catalog_mutations.py` | 5 | `db/queries.py` (`save_panel`/`delete_panel`/`save_test_parameters`) | Authz inside data layer (deny low role), create/update/delete **emit audit rows**. Verifies audit *write*, not chain integrity. |
| `test_backup_restore.py` | 5 | `db/backup.py`, `db/audit.py` (fallback) | Backup round-trip, source validation, reject empty users DB, preserve prior rollback, **audit fallback log written on restore**. Good. |
| `test_roles.py` | 5 | `roles.py` | Level hierarchy, `can()` capabilities, unknown cap denied by default, `require()` raise/pass. Solid for the pure-logic module. |
| `test_single_instance.py` | 3 | `app.py` (single-instance lock) | No-instance ping fails, primary acquires + second refused + ping works, lock releases on close. |
| `test_gui_e2e.py` | 5 | `ui/reception.py`, `ui/receipts.py`, `render/*`, `app.py` | Reception creates receipt, **print receipt & report to a real A4 PDF** (virtual printer), admin can void at page level, receptionist cannot. Best-in-class integration tests; only the happy paths. |

**Strengths:** auth, encryption/rekey, licensing, single-instance, and the receipt void/payment ledger are well covered, including adversarial cases (tamper, rollback, fail-closed). The A4-PDF GUI E2E harness is a notable asset.

---

## 3. Coverage-gap matrix (module × tested?)

Legend: ✅ direct tests · ◐ exercised indirectly (no assertions on its own contract) · ❌ untested · ⬛ UI/integration-only.
Criticality: **C**=Critical, **H**=High, **M**=Medium, **L**=Low.

| Module | LOC | Crit | Tested? | Est. cov | Notes |
|---|---|---|---|---|---|
| `db/auth.py` | 73 | C | ✅ | ~90% | Excellent. |
| `db/crypto.py` | 62 | C | ✅ | ~85% | scrypt + legacy upgrade + dummy-verify timing path covered. |
| `db/connection.py` | 396 | C | ◐ | ~45% | Encrypt/verify/rekey/fail-closed tested; **schema migration paths, key-source precedence, env-key handling largely untested.** |
| `db/crypto`/rekey | — | C | ✅ | — | rekey round-trip covered. |
| `licensing/__init__.py` | 274 | C | ✅ | ~80% | `install_license`, `license_info`, `check()` install path partially indirect. |
| `licensing/_ed25519.py` | — | C | ✅ | high | via signature tests. |
| `licensing/fingerprint.py` | 107 | C | ✅ | ~70% | signal-match tested; `_disk_serial`/`_primary_mac` collectors not. |
| `db/audit.py` — `log_audit` | 111 | C | ◐ | ~50% | Written via catalog/backup tests. |
| **`db/audit.py` — `verify_audit_chain`** | — | **C** | **❌** | **0%** | **Tamper-evidence core. The whole point of the SHA256 chain is untested. No test mutates a row and asserts `(False, bad_id)`.** |
| **`db/audit.py` — `rechain_audit`** | — | **C** | **❌** | **0%** | Post-purge rechain never verified to keep chain valid. |
| **`report/verify.py`** | 90 | **C** | **❌** | **0%** | **HMAC report forensic codes (`report_fingerprint`/`verification_code`/`verify`). Zero tests. A wrong/forgeable code is a medical-legal liability.** |
| **`services/billing.py`** | 71 | **H** | **❌** | **0%** | **`compute_bill_totals` money math (rounding, discount, due/change, clamp-at-zero) untested. Two call sites with different rounding modes — exactly where money bugs hide.** `get_active_promo_discount` expiry/clamp untested. |
| `db/queries.py` — catalog | 187 | H | ✅/◐ | ~55% | panel save/delete/params + `receive_due` covered; `ParameterInUseError`, `list_panels(include_inactive)`, `panel_tests` not. |
| `services/receipts.py` | 65 | C | ✅ | ~85% | Good. |
| **`db/patient_id.py`** | 48 | **H** | **❌** | **0%** | **Check-letter algorithm, format & validate round-trip, year rollover — untested. A collision/format bug mislabels patient specimens.** |
| **`db/keyvault.py`** | 172 | **H** | **❌** | **0%** | **Secret-Service store/load/clear of the DB passphrase. `available()`, error paths, label/attrs — untested.** (Hard to test without a keyring; needs mocking.) |
| `db/settings.py` | 39 | M | ◐ | ~40% | get/set hit via GUI E2E; `set_settings` mapping, `currency()` default untested. |
| `db/backup.py` | 212 | H | ✅ | ~60% | round-trip/validation good; `auto_backup` scheduling, `_usable_dir` fallback, encrypted-copy key handling untested. |
| **`whatsapp.py`** | 512 | **H** | **❌** | **0%** | **Largest untested file. `validate_url`/`is_local_url`/`is_loopback_url` are SSRF guards; `_NoCrossHostRedirect`, `wa_number` normalization, `_safe_filename`, `recipient_ready`/`config_ready` — all untested. SSRF + PII-leak surface with zero regression net.** |
| `render/report_doc.py` | 667 | H | ⬛ | ~30% | Only via PDF E2E (renders, no content assertions). |
| `render/receipt.py`, `render/image.py`, `render/preview.py` | — | M | ⬛ | ~30% | E2E render-only. |
| `report/content.py`,`html.py`,`export.py`,`formatting.py` | — | M | ❌/⬛ | low | export/HTML path not asserted. |
| `ui/*` (settings 988, reception 857, receipts 736, catalog 653, worklist 567, …) | ~6k | M | ◐ | ~10% | Only reception+receipts touched by E2E; settings/worklist/catalog/microbiology/accounts/doctors/logs/wa/dashboard/setup_wizard/activation/unlock/login/tasks **not driven by any test** (self-test only constructs them). |
| `roles.py` | 77 | C | ✅ | ~90% | Good. |
| `app.py` | 492 | H | ◐ | ~30% | single-instance covered; startup wiring, migration triggers, selftest path untested-with-assertions. |

### Coverage vs goals

| Tier | Goal | Estimated actual | Verdict |
|---|---|---|---|
| Unit (pure logic: roles, crypto, auth, licensing, patient_id, billing, audit, verify) | **>85%** | ~55–60% | **MISS** — dragged down by billing/patient_id/audit-chain/report-verify at 0%. |
| Integration (services, db mutations, backup, GUI flows) | **>75%** | ~60% | **MISS** — receipts/catalog/backup strong; whatsapp/settings/worklist absent. |
| Critical modules (security, licensing, db, audit, billing, receipts) | **>95%** | ~65% | **MISS** — auth/crypto/licensing/receipts near goal, but **audit-chain verify=0%, report-verify=0%, billing=0%** pull the critical tier well below 95%. |

---

## 4. Prioritized missing-test backlog

Priority: **P0** = ship-blocker for a medical LIS · **P1** = high · **P2** = medium · **P3** = nice-to-have.

### P0 — Critical, zero current coverage

1. **Audit-chain tamper detection** — *Unit/Security* — `db/audit.py::verify_audit_chain`
   - Scenario: log N entries; assert `(True, None)`. Then `UPDATE audit_log SET detail=...` on a middle row → assert `(False, that_id)`. Delete a row → assert mismatch propagates. Legacy rows (`hash IS NULL`) before chain start tolerated; a NULL **after** chaining started → `(False, id)`.
2. **Audit rechain integrity** — *Unit/Security* — `db/audit.py::rechain_audit`
   - Scenario: build chain, purge oldest rows, call `rechain_audit`, then `verify_audit_chain` must return `(True, None)`. Assert rechain does NOT silently launder a *content* tamper that wasn't an authorized purge (document expected behavior).
3. **`log_audit` fallback on DB failure** — *Unit* — `db/audit.py::_audit_fallback`
   - Scenario: force a `sqlite3.Error` (read-only/closed con) → assert fallback file written with username/action/detail and never raises.
4. **Report verification code: correctness & forgery resistance** — *Security/Unit* — `report/verify.py`
   - `verification_code` deterministic across reprints; changes when a result value/hidden flag/culture sensitivity changes; `verify()` accepts canonical and separator/space/case variants and **rejects** any altered code; empty report → `""` and `verify` returns False; `_verify_key` race (two first-writers converge on one key).
5. **Billing money math** — *Unit/Regression* — `services/billing.py::compute_bill_totals`
   - Both modes: `round_to_paisa=False` (reception, raw subtotal) vs `True` (receipts, 2-dp net). Assert: discount %, `net=max(0, …)` clamp, `due`/`change` non-negative & mutually exclusive, paisa rounding, 100% discount → net 0, overpayment → change, floating-point edge (e.g., 0.1+0.2 charges). `get_active_promo_discount`: expiry passed → 0, malformed `promo_until`/`promo_discount_pct` → safe default, clamp to [0,100].

### P1 — High-criticality gaps

6. **Patient-ID algorithm** — *Unit* — `db/patient_id.py`
   - `format_patient_id`/`validate_patient_id` round-trip across a range of seqs; check-letter correctness; a single-digit/transposition mutation fails `validate`; year/default handling; rejects malformed codes.
7. **WhatsApp SSRF guards** — *Security/Regression* — `whatsapp.py::validate_url/is_local_url/is_loopback_url/_NoCrossHostRedirect`
   - `validate_url` rejects non-http(s), missing host; `is_local_url` flags loopback/private/link-local IPs and DNS names resolving to them; `_NoCrossHostRedirect.redirect_request` blocks cross-host redirect (anti-SSRF). These are pure-ish functions — high value, low cost.
8. **WhatsApp number normalization & filename safety** — *Unit* — `whatsapp.py::wa_number`, `_safe_filename`
   - Country-code prefixing, leading-zero strip, invalid → `None`; `_safe_filename` strips path separators/control chars and applies fallback.
9. **WhatsApp readiness gates** — *Integration* — `config_ready`, `recipient_ready`, `_log_wa`
   - Missing URL/token → not ready with message; missing patient phone → not ready; `_log_wa` writes a wa-log row with ok/message.
10. **Keyvault (mocked Secret Service)** — *Unit* — `db/keyvault.py`
    - With a mocked `_conn`/session: `store_key`→`load_key` round-trip; `clear_key`; `available()` true/false; D-Bus error paths return False/None without raising. (Needs jeepney/dbus mock — note infra cost.)
11. **`ParameterInUseError` path** — *Integration* — `db/queries.py::save_test_parameters`
    - Editing a parameter referenced by existing results raises `ParameterInUseError` with the offending names.
12. **Connection key-source precedence & migration** — *Integration* — `db/connection.py`
    - Env key vs keyvault vs prompt precedence; schema migration runs idempotently on an older DB; corrupt/locked DB surfaces a clear error (fail-closed).

### P2 — Medium

13. **Backup auto-scheduling & dir fallback** — `db/backup.py::auto_backup/_usable_dir/fallback_backup_dir` — keep-N pruning, unwritable dir → fallback, encrypted-copy uses key.
14. **Settings mapping & currency** — `db/settings.py::set_settings/currency` — bulk set, default currency, missing key.
15. **Report HTML/export content** — `report/html.py`, `report/export.py`, `report/content.py` — assert rendered HTML contains expected fields, hidden results suppressed, export writes a file.
16. **Catalog read queries** — `db/queries.py::list_panels(include_inactive)`, `panel_tests` — active filter, ordering.
17. **GUI flows not yet driven** — *GUI* — worklist result entry → report ready; settings save/validation; microbiology culture+sensitivity entry; catalog add/edit via UI; accounts create/role-change; logs page renders audit + integrity indicator.

### P3 — Lower

18. **Render snapshot/regression** — *Regression* — hash or pixel-diff of receipt/report PDFs against a golden to catch layout drift (the E2E currently only checks a PDF is produced).
19. **CI coverage gate** — *Process* — add `pytest-cov` + `--cov-fail-under` once dependency install is permitted; fail PRs below the per-tier goals. Add a `ruff` job to CI.
20. **Self-test → assertive smoke** — *Regression* — extend `LABDESK_SELFTEST` so page construction asserts no error dialogs / no exception logs, not just "didn't crash."

---

## 5. Process & tooling recommendations

- **Add `pytest-cov` and a coverage gate in CI** (currently none). Track per-package thresholds; the audit-chain/report-verify/billing files should be hard-gated to ≥95%.
- **Add a `ruff` lint job** to the CI test workflow (tool is available locally but not enforced in CI).
- **The headless self-test asserts nothing** — convert into an assertive smoke test.
- **Introduce property-based tests** (`hypothesis`, if/when install is allowed) for `compute_bill_totals` and `patient_id` check-letters — both are arithmetic invariants ideal for fuzzing.
- Maintain golden PDF fixtures for render regression.

---

## 6. Bottom line

The suite is **small but adversarially smart** where it exists (clock-rollback, fail-closed crypto, legacy hash upgrade, ledger reversal, A4-PDF E2E). The disqualifying problem for a HIGH-criticality medical LIS is **what is entirely untested**: the audit chain's *integrity verification* (the feature's whole purpose), the HMAC report-verification codes, the billing money math, patient-ID labeling, the keyvault, and the 512-LOC WhatsApp/SSRF surface. None of these have a single assertion. No CI coverage gate exists to stop this from getting worse.

**Headline grade: C+.**
