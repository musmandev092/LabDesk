# LabDesk — Testability Uplift Plan: C+ → A/A+

**Dimension:** Testability
**Current grade:** C+
**Target:** A / A+
**Author:** Test-Strategy uplift (planning-only; no source/test/config modified)
**Date:** 2026-06-16
**Grounded in:** `audit/08-test-report.md` + direct reads of `src/labdesk/services/billing.py`, `src/labdesk/db/patient_id.py`, `src/labdesk/report/verify.py`, `src/labdesk/db/audit.py`, `src/labdesk/whatsapp.py`, `tests/conftest.py`, `pyproject.toml`, `.github/workflows/ci.yml`.

---

## 1. Where we are (evidence)

- **56 tests, all green, ~22.6 s.** Adversarially smart where present (clock-rollback, fail-closed crypto, legacy-hash upgrade, ledger reversal, A4-PDF E2E). Source: `audit/08-test-report.md` §1–2.
- **No coverage instrumentation at all.** `pyproject.toml` has only `addopts = "-q"`; there is no `pytest-cov`, no `[tool.coverage.*]`, no `--cov-fail-under`. CI (`.github/workflows/ci.yml`) runs `uv run pytest -q` + a non-asserting `LABDESK_SELFTEST` page-build. **A coverage regression cannot be detected today.**
- **Disqualifying zero-coverage on the highest-trust modules** (confirmed by reading source):
  - `db/audit.py::verify_audit_chain` (the tamper-evidence core) and `rechain_audit` — **0%**.
  - `report/verify.py` — HMAC report forensic codes (`report_fingerprint`/`verification_code`/`verify`) — **0%**.
  - `services/billing.py::compute_bill_totals` — money math with **two distinct rounding modes** in one function (`round_to_paisa` False vs True), money stored as `float` — **0%**.
  - `db/patient_id.py` — mod-23 weighted check-letter that gates specimen labeling — **0%**.
  - `whatsapp.py` SSRF guards (`validate_url`/`is_local_url`/`is_loopback_url`/`_NoCrossHostRedirect`) and `wa_number`/`_safe_filename` — **0%** across 512 LOC.
- **Estimated tier coverage** (call-graph, not measured): Unit ~55–60%, Integration ~60%, Critical-modules ~65% — all three MISS their goals.
- **No test quality measure.** Even where coverage exists, nothing proves the assertions would *catch a regression*. There is no mutation testing, no property-based testing, and the existing `compute_bill_totals` is a textbook target for both.

The grade is C+ not because the existing tests are weak, but because the modules whose *entire purpose is trust* (audit chain integrity, report verification, money) have no assertions and no CI gate stops that from persisting.

---

## 2. What "A+" means for Testability — researched bar

Testability A+ for **safety-critical, regulated-adjacent** software is defined by four independent axes, each backed by a recognized standard or tool. Code coverage alone is explicitly insufficient.

### 2.1 Structural coverage with the *right granularity* (branch / MC-DC), not line coverage
- Line coverage hides un-exercised branches; **branch coverage** measures both sides of every `if/else`. coverage.py supports it via `branch = true`, enforced in CI with `--cov-fail-under`. ([coverage.py docs](https://coverage.readthedocs.io/), [pytest-cov config](https://pytest-cov.readthedocs.io/en/latest/config.html))
- The highest safety integrity levels demand **Modified Condition/Decision Coverage (MC/DC)** — every *condition* in a compound boolean independently shown to affect the outcome. MC/DC is the Level-A requirement in DO-178C and is recommended for the highest classes in **IEC 62304** (medical-device software), ISO 26262, and IEC 61508. ([MC/DC — Wikipedia](https://en.wikipedia.org/wiki/Modified_condition/decision_coverage), [DO-178C §6.4.4.2 — arc42](https://quality.arc42.org/standards/do-178c), [LDRA MC/DC](https://ldra.com/capabilities/mc-dc/))
- **IEC 62304** classifies each software item A/B/C by severity of possible harm; Class C (death/serious injury possible) mandates the most rigorous unit verification — "each unit verified through testing, inspection, or static analysis based on classification." LabDesk's clinical-result-release and billing paths are effectively **Class B–C**: a wrong released result or mislabeled specimen can cause serious harm. ([Johner Institute — 62304 safety classes](https://blog.johner-institute.com/iec-62304-medical-software/safety-class-iec-62304/), [Greenlight Guru — 62304](https://www.greenlight.guru/glossary/iec-62304))

> **coverage.py / pytest-cov is mature, but `branch=true` only approximates MC/DC.** True MC/DC requires per-condition instrumentation that coverage.py does not provide. For LabDesk the pragmatic A+ stance is: **branch coverage as the enforced gate + manual MC/DC review of the 4 critical boolean-heavy functions** (documented in the test file), since the critical functions are small (`compute_bill_totals`, `verify_audit_chain`, `validate_patient_id`, `verify`).

### 2.2 Coverage *thresholds* tuned to criticality
- Generic safety-net advice: enforce branch coverage with a `fail-under` gate in CI to stop untested code reaching production. ([Scientific-Python coverage guide](https://learn.scientific-python.org/development/guides/coverage/))
- Thresholds should be **risk-graded**, not uniform: critical modules far higher than UI glue. This matches IEC 62304's "rigor scales with safety class."

### 2.3 Test *quality* proven by mutation testing (coverage is a vanity metric otherwise)
- Mutation testing injects small faults (mutants); a test suite that doesn't fail on a mutant has a coverage gap the percentage hid. It is the true measure of suite quality. ([Codecov — mutation testing vs vanity coverage](https://about.codecov.io/blog/mutation-testing-how-to-ensure-code-coverage-isnt-a-vanity-metric/))
- **Threshold guidance:** start 70–80%, raise over time; **100% is rarely needed and thresholds should scale with component criticality**; a typical gate is high=80 / break=50. Run on critical paths nightly with sign-off when the score drops. ([Master Software Testing — mutation guide](https://mastersoftwaretesting.com/testing-fundamentals/types-of-testing/specialized-testing/mutation-testing))
- **Tooling:** `mutmut` is the most actively maintained and preserves source formatting when applying mutants (cleaner than AST-dump tools); `cosmic-ray` has stronger build-tool integration and scored higher mutation competency in a comparative study but is heavier to install/run. ([mutmut design — kodare.net](https://kodare.net/2016/12/01/mutmut-a-python-mutation-testing-system.html), [Analysis & Comparison of Python mutation tools — IEEE](https://ieeexplore.ieee.org/document/10818231/)) → **Recommend `mutmut`**, scoped to the 4 critical modules only.

### 2.4 Property-based testing for arithmetic/crypto invariants
- Hypothesis generates inputs across a described range and finds edge cases you didn't enumerate; the **round-trip property** is the canonical fit for encode/decode and validate pairs, and the **decimal/float rounding** domain is exactly where it shines — "floating-point division is not exact… values exceed expected bounds due to precision." ([Hypothesis docs](https://hypothesis.readthedocs.io/), [TDS — let Hypothesis break your code](https://towardsdatascience.com/let-hypothesis-break-your-python-code-before-your-users-do/)) LabDesk stores money as `float` → property tests on `compute_bill_totals` are not optional for A+.

### 2.5 GUI behavior verified, not just constructed
- **pytest-qt** provides `qtbot` to drive PySide6 widgets — click, set text, and `waitSignal` to block on async signals — and auto-closes registered widgets. Today LabDesk's GUI is tested only via the bespoke A4-PDF E2E and a *non-asserting* self-test. ([pytest-qt docs](https://pytest-qt.readthedocs.io/en/latest/tutorial.html), [pytest-qt on PyPI](https://pypi.org/project/pytest-qt/)) The clinical write paths (`ui/worklist.py:425`, `ui/microbiology.py:237`, `ui/reception.py:627`) — the systemic finding of the whole audit — have no driven GUI test asserting authorization + the multi-table transaction outcome.

### 2.6 Maintainable test data — fixtures + factories
- `factory_boy` / `pytest-factoryboy` replace static, hard-to-maintain fixtures with declarative factories, letting a test declare only the fields it cares about. ([pytest-factoryboy docs](https://pytest-factoryboy.readthedocs.io/en/stable/), [factory_boy on PyPI](https://pypi.org/project/factory-boy/3.0.1/)) LabDesk has one good DB fixture chain (`conftest.py`) but no way to mint a receipt/patient/result graph compactly — every new integration test will hand-roll inserts.

### Concrete A+ acceptance bar for LabDesk

| Axis | A (table-stakes) | A+ (stretch) |
|---|---|---|
| Overall branch coverage gate in CI | `--cov-branch --cov-fail-under=80` global, PR-blocking | 85% global |
| Unit (pure logic) | ≥ 85% branch | ≥ 90% |
| Integration (services/db/backup/GUI flows) | ≥ 75% branch | ≥ 80% |
| **Critical modules** (`db/audit.py`, `report/verify.py`, `services/billing.py`, `licensing/`, `db/crypto.py`, `db/auth.py`, `db/patient_id.py`) | ≥ 95% **branch** + documented MC/DC review of the boolean-heavy functions | 100% branch on the 4 zero-coverage cores |
| Mutation testing | `mutmut` configured + run on the 4 critical modules; baseline recorded; **break < 60** | **≥ 80%** mutation score on critical modules, nightly CI job, drop fails build |
| Property-based | Hypothesis tests for `compute_bill_totals` (money) + `patient_id` round-trip/check-letter + `verify`/`verification_code` (crypto) | invariants also on `get_active_promo_discount` clamp and `wa_number` |
| GUI | pytest-qt smoke for every page (asserts no error dialog/exception) + driven tests for the 3 clinical write paths asserting `require()` denial for low role | full happy+sad path for worklist/microbiology/reception release with audit-row assertion |
| Test data | `conftest.py` factories for patient/receipt/result/culture graphs | `pytest-factoryboy`-injected factories |
| CI gates | coverage fail-under + `ruff` lint job + self-test made assertive | + mutation gate + golden-PDF regression |

---

## 3. Gap-closing backlog (ordered; every step ties to real files)

Effort S=<½ day, M=½–2 days, L=>2 days. Phases ordered so the **gate exists before** the tests it will protect, and the **0%-coverage trust modules** come first.

### Phase 0 — Make coverage observable and enforced (prerequisite for everything)

**Step 1 — Add coverage tooling + branch-coverage config.** *(S, Low risk, High impact)*
Add `pytest-cov`/`coverage` to the `dev` dependency-group in `pyproject.toml`; add `[tool.coverage.run] branch = true / source = ["src/labdesk"]`, `[tool.coverage.report] show_missing = true`, and per-tier omit rules. Set `addopts = "-q --cov=labdesk --cov-branch --cov-report=term-missing"`.
*Satisfies:* §2.1 branch coverage, §2.2 thresholds. *Note:* needs install permission — currently blocked per memory rule.
*Files:* `pyproject.toml`.

**Step 2 — CI coverage fail-under gate + ruff job.** *(S, Low, High)*
In `.github/workflows/ci.yml`: change test step to `uv run pytest --cov=labdesk --cov-branch --cov-fail-under=80 --cov-report=xml`; add a second `coverage report --fail-under=95 --include="src/labdesk/db/audit.py,src/labdesk/report/verify.py,src/labdesk/services/billing.py,src/labdesk/db/patient_id.py,src/labdesk/licensing/*"` step that hard-gates the critical set; add a `ruff check` job.
*Satisfies:* §2.2 risk-graded gate, §2.5 assertive CI.
*Files:* `.github/workflows/ci.yml`.

### Phase 1 — The four zero-coverage trust modules (P0)

**Step 3 — Audit-chain tamper detection.** *(M, Low, High)*
New `tests/test_audit_chain.py`: log N entries → `verify_audit_chain` returns `(True, None)`; `UPDATE audit_log SET detail=…` on a middle row → `(False, that_id)`; delete a row → mismatch propagates; legacy `hash IS NULL` rows before chain start tolerated, a NULL *after* chaining started → `(False, id)`. Then `rechain_audit` after an authorized purge → `verify` returns `(True, None)`; document whether rechain can launder a content tamper. Plus `_audit_fallback`: force `sqlite3.Error` (closed con) → fallback file written, never raises.
*Satisfies:* §2.2 critical ≥95% branch; backlog P0-1/2/3 in `08-test-report.md`.
*Files:* `tests/test_audit_chain.py` → `src/labdesk/db/audit.py`.

**Step 4 — Report verification code: correctness + forgery resistance.** *(M, Low, High)*
New `tests/test_report_verify.py`: `verification_code` deterministic across reprints; changes when a result value / `hidden` flag / culture sensitivity changes; `verify()` accepts canonical + separator/space/case variants and **rejects** any altered code; empty report → `""` and `verify` → False; `_verify_key` race — two first-writers converge on one key (call twice, assert equal). Build the receipt/results/cultures graph via the Phase-3 factory.
*Satisfies:* §2.2 critical ≥95%, §2.4 crypto invariants; backlog P0-4.
*Files:* `tests/test_report_verify.py` → `src/labdesk/report/verify.py`.

**Step 5 — Billing money math (example-based core).** *(M, Low, High)*
New `tests/test_billing.py`: both modes — `round_to_paisa=False` (reception raw subtotal) vs `True` (receipts 2-dp net). Assert discount %, `net=max(0,…)` clamp, `due`/`change` non-negative & mutually exclusive, paisa rounding, 100% discount → net 0, overpayment → change, the float edge (`0.1+0.2`). `get_active_promo_discount`: expiry passed → 0, malformed `promo_until`/`promo_discount_pct` → safe default, clamp to `[0,100]`.
*Satisfies:* §2.2 critical, money correctness; backlog P0-5.
*Files:* `tests/test_billing.py` → `src/labdesk/services/billing.py`.

**Step 6 — Patient-ID algorithm.** *(S, Low, High)*
New `tests/test_patient_id.py`: `format`/`validate` round-trip across a seq range; check-letter correctness; single-digit and adjacent-transposition mutation fails `validate`; year/default handling; rejects malformed + legacy `MR…`.
*Satisfies:* §2.2 critical, specimen-labeling integrity; backlog P1-6.
*Files:* `tests/test_patient_id.py` → `src/labdesk/db/patient_id.py`.

### Phase 2 — Property-based invariants (the A+ differentiator)

**Step 7 — Hypothesis property tests for money + patient-id + crypto.** *(M, Med, High)*
Add `hypothesis` to dev deps. In `tests/test_billing.py`/`test_patient_id.py`/`test_report_verify.py` add `@given` strategies:
- **Money:** for any `items` (floats ≥0), any `discount_pct∈[0,100]`, any `paid≥0`: `net≥0`, `due≥0`, `change≥0`, `due*change==0` (mutually exclusive), `net≤subtotal`, and with `round_to_paisa=True` every returned value is 2-dp. Catches the float-storage class of bugs.
- **Patient-ID round-trip:** `validate_patient_id(format_patient_id(seq, year))` is True for all `seq≥0`, all `year`.
- **Verify round-trip:** `verify(con, rid, verification_code(con, rid))` is True; flipping any one character makes it False.
*Satisfies:* §2.4 property-based money/crypto invariants — A+ acceptance line item.
*Files:* `pyproject.toml`, `tests/test_billing.py`, `tests/test_patient_id.py`, `tests/test_report_verify.py`.

### Phase 3 — Test-data factories (unblocks GUI + integration depth)

**Step 8 — Factory fixtures for the domain graph.** *(M, Low, Med)*
In `tests/conftest.py` (or new `tests/factories.py`): factory fixtures `make_patient`, `make_receipt(items=…)`, `make_result`, `make_culture` that insert through the real `db`/`services` layer and return ids. Lets Steps 4, 10, 11 declare only the fields they care about. Optionally adopt `pytest-factoryboy` for injection.
*Satisfies:* §2.6 maintainable test data.
*Files:* `tests/conftest.py`, `tests/factories.py`.

### Phase 4 — GUI behavior + the systemic clinical-write finding

**Step 9 — Adopt pytest-qt; make self-test assertive.** *(M, Med, High)*
Add `pytest-qt` to dev deps. New `tests/test_gui_smoke.py`: with `qtbot`, construct every UI page and assert no `QMessageBox` error / no logged exception (turn the current non-asserting `LABDESK_SELFTEST` into real assertions). Register widgets with `qtbot.addWidget`.
*Satisfies:* §2.5 GUI smoke; backlog P3-20.
*Files:* `pyproject.toml`, `tests/test_gui_smoke.py`.

**Step 10 — Drive the three clinical write paths and assert authz + transaction.** *(L, Med, High)*
New `tests/test_clinical_release.py` using `qtbot` + factories: drive bill creation (`ui/reception.py:627`), result release (`ui/worklist.py:425`), microbiology release (`ui/microbiology.py:237`). Assert the multi-table transaction's committed end-state (receipt/result/audit rows) for an authorized role, and that a **low role is denied** (this is the audit's top systemic finding — even before the code is refactored to add `require()`, the test pins current behavior and will catch the regression once a service boundary lands).
*Satisfies:* §2.5 driven GUI + §2.1 critical-path branch; backlog P2-17. *Risk note:* couples to widget internals until the write paths are extracted into services — document that coupling.
*Files:* `tests/test_clinical_release.py` → `ui/reception.py`, `ui/worklist.py`, `ui/microbiology.py`.

### Phase 5 — Remaining high-value gaps (P1/P2)

**Step 11 — WhatsApp SSRF guards + normalization (pure functions, high ROI).** *(M, Low, High)*
New `tests/test_whatsapp.py`: `validate_url` rejects non-http(s)/missing host; `is_local_url`/`is_loopback_url` flag loopback/private/link-local IPs and DNS names resolving to them; `_NoCrossHostRedirect.redirect_request` blocks cross-host redirect; `wa_number` country-code prefix / leading-zero strip / invalid→None; `_safe_filename` strips path separators/control chars + fallback. `config_ready`/`recipient_ready` readiness gates with mocked settings.
*Satisfies:* §2.2 high-criticality, SSRF/PII regression net; backlog P1-7/8/9.
*Files:* `tests/test_whatsapp.py` → `src/labdesk/whatsapp.py`.

**Step 12 — Keyvault (mocked Secret Service) + connection key-source precedence.** *(M, Med, Med)*
New `tests/test_keyvault.py` with a mocked jeepney/D-Bus session: `store_key`→`load_key` round-trip, `clear_key`, `available()` true/false, D-Bus error paths return False/None without raising. Extend `tests/test_connection_encryption.py`: env-key vs keyvault vs prompt precedence; idempotent schema migration on an older DB; `ParameterInUseError` path in `db/queries.py::save_test_parameters`.
*Satisfies:* §2.2 high-criticality; backlog P1-10/11/12.
*Files:* `tests/test_keyvault.py`, `tests/test_connection_encryption.py` → `src/labdesk/db/keyvault.py`, `db/connection.py`, `db/queries.py`.

### Phase 6 — Mutation testing (proves the above are real) + render regression

**Step 13 — mutmut on the four critical modules, baseline + nightly gate.** *(L, Med, High)*
Add `mutmut` to dev deps; `[tool.mutmut] paths_to_mutate = "src/labdesk/db/audit.py,src/labdesk/report/verify.py,src/labdesk/services/billing.py,src/labdesk/db/patient_id.py"`; record baseline score; add a **nightly** CI job (`schedule:` cron) that fails if mutation score on the critical set drops below the gate (start break<60, ramp to ≥80). Surviving mutants → add the missing assertion.
*Satisfies:* §2.3 mutation testing — the A+ definition of test quality.
*Files:* `pyproject.toml`, `.github/workflows/ci.yml` (or new `mutation.yml`).

**Step 14 — Golden-PDF render regression.** *(M, Low, Med)*
Extend `tests/test_gui_e2e.py`: hash/normalize a rendered receipt + report PDF against a committed golden to catch layout drift (today the E2E only asserts a PDF is produced, not its content).
*Satisfies:* §2.5 stretch; backlog P3-18.
*Files:* `tests/test_gui_e2e.py`, `tests/golden/*.pdf`.

---

## 4. Sequencing & exit criteria

1. **Phase 0** first — without the gate, every later gain can silently erode. (Blocked on install permission for `pytest-cov`.)
2. **Phase 1** clears the four 0%-coverage trust modules → moves the *critical* tier from ~65% toward ≥95% branch. This is the single biggest grade lever (C+ → B+).
3. **Phases 2–4** (property-based + factories + pytest-qt GUI + clinical write paths) take it to **A**.
4. **Phases 5–6** (whatsapp/keyvault breadth + **mutmut ≥80% on critical** + golden PDFs) take it to **A+**.

**A is reached when:** CI enforces ≥80% global / ≥95% critical *branch* coverage, all four trust modules have assertions, property tests guard money/patient-id/crypto, and pytest-qt smoke covers every page.
**A+ is reached when:** mutation score ≥80% on the critical four (nightly-gated), the three clinical write paths are driven with authz + transaction assertions, MC/DC of the critical boolean functions is reviewed and documented, and golden-PDF regression is in place.

---

## 5. Recommended tooling (recommendations only — install not performed)

| Tool | Why | Source |
|---|---|---|
| `pytest-cov` + `coverage[toml]` (`branch=true`) | Measured branch coverage + `--cov-fail-under` CI gate; nothing measures coverage today | [pytest-cov](https://pytest-cov.readthedocs.io/en/latest/config.html), [coverage.py](https://coverage.readthedocs.io/) |
| `hypothesis` | Property-based invariants for float money math + patient-id/crypto round-trips — A+ requirement | [Hypothesis](https://hypothesis.readthedocs.io/) |
| `pytest-qt` | Drive PySide6 widgets (`qtbot`, `waitSignal`); turn the non-asserting self-test into real GUI tests | [pytest-qt](https://pytest-qt.readthedocs.io/en/latest/tutorial.html) |
| `mutmut` (scoped to 4 critical files) | True test-quality measure; actively maintained, source-preserving | [mutmut](https://kodare.net/2016/12/01/mutmut-a-python-mutation-testing-system.html), [comparison](https://ieeexplore.ieee.org/document/10818231/) |
| `factory_boy` / `pytest-factoryboy` (optional) | Declarative domain-graph factories for receipt/patient/result/culture | [pytest-factoryboy](https://pytest-factoryboy.readthedocs.io/en/stable/) |
| `ruff` (already a dev dep) | Enforce as a CI job — currently not gated in CI | existing `pyproject.toml` dev group |

---

## 6. Standards mapping (why this bar is the right one)

- **IEC 62304** (medical-device software): rigor of unit verification scales with safety class; LabDesk's result-release/billing are Class B–C → mandates the ≥95% critical-tier + documented per-unit verification. ([Johner Institute](https://blog.johner-institute.com/iec-62304-medical-software/safety-class-iec-62304/))
- **DO-178C / MC/DC** (highest integrity boolean coverage): justifies MC/DC review of the small critical boolean functions beyond branch coverage. ([arc42 DO-178C](https://quality.arc42.org/standards/do-178c), [MC/DC](https://en.wikipedia.org/wiki/Modified_condition/decision_coverage))
- **Mutation testing** (coverage-isn't-quality): justifies the mutmut gate. ([Codecov](https://about.codecov.io/blog/mutation-testing-how-to-ensure-code-coverage-isnt-a-vanity-metric/), [thresholds](https://mastersoftwaretesting.com/testing-fundamentals/types-of-testing/specialized-testing/mutation-testing))
- **Property-based testing** (float/decimal invariants): justifies Hypothesis on `compute_bill_totals`. ([Hypothesis](https://hypothesis.readthedocs.io/), [TDS](https://towardsdatascience.com/let-hypothesis-break-your-python-code-before-your-users-do/))
