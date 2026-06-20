# Technical Debt Register

This file is the tracked, **decreasing** debt baseline for LabDesk's A+ uplift
(see `audit/uplift/A-PLUS-MASTERPLAN.md`). Every quality gate is measured today
but runs in **report mode** (non-blocking) until the Wave 8 ratchet flips it to
hard-fail. The rule from Wave 0 onward: **no PR may raise any number below.**

Baseline measured: **2026-06-16** · tools pinned in `pyproject.toml` dev group.

> **Wave 1 update (2026-06-16):** trust-core characterization tests landed. Test
> count 56 → **115**. Critical trust modules (`db/audit.py` 97%, `report/verify.py`
> 100%, `services/billing.py` 100%, `db/patient_id.py` 100%) now at **99% branch**
> as a set — CI gate `>=95` is live and BLOCKING. Global branch coverage 32% → **33%**
> with a ratcheting floor gate at 30. ruff baseline restated to the **configured**
> count (741, was 794 raw — the difference is the per-file-ignores now in effect).
>
> **Wave 2 update (2026-06-16):** the keystone. The four privileged write paths now
> run through authorized, audited service boundaries instead of inline SQL in Qt
> widgets — closing the CWE-862/863 systemic finding: bill-create
> (`services/receipts.create_receipt`), result-release (`services/results.release_results`),
> culture-save (`services/results.save_culture`), user-mutations (`services/users.*`).
> New caps in `roles.py`: create_receipt(2), enter/finalize_results(3),
> edit_finalized_results(5). Tests 115 → **140** (test_bill_create_service,
> test_results_service, test_users_service — each asserts authz-deny-writes-nothing +
> committed multi-table state). ruff floor held (**733** ≤ 741). Services coverage:
> billing/users 100%, receipts 88%, results 79%.
>
> **Wave 4a update (2026-06-16):** indexed the 5 unindexed FK columns
> (`_ensure_indexes`, idempotent on existing DBs); `test_schema_indexes.py` asserts
> existence + planner-uses-index + clean `foreign_key_check`. Global floor raised
> 30 → **33** (current 34%).

How to reproduce every number here:

```bash
uv run ruff check src tests            # G1  lint
uv run mypy                            # G3  types (scoped strict)
uv run lint-imports                    # G4  architecture contracts
QT_QPA_PLATFORM=offscreen uv run pytest # G5 tests + branch coverage
uv run bandit -r src/labdesk -q        # G9  SAST
uv run pip-audit                       # G10 dependency CVEs
QT_QPA_PLATFORM=offscreen uv run mutmut run  # G6 mutation testing (trust-core)
```

## G6 — mutation testing (do the trust-core tests KILL mutants?)

`mutmut` (3.6) over the 4 critical trust modules, config in `pyproject.toml`
`[tool.mutmut]` (the `also_copy=["src/labdesk"]` is REQUIRED so the mutated
module's cross-imports + DB fixtures work inside mutmut's sandbox). Run offscreen.

| Module | Mutants | Killed | Survived | Score |
|--------|--------:|-------:|---------:|------:|
| `db/patient_id.py` | 40 | 34 | 6 | **85%** |
| `application/billing.py` | 57 | 46 | 11 | **81%** |
| `db/audit.py` | 253 | 194 | 59 | **77%** |
| `report/verify.py` | 174 | 114 | 60 | 66% |
| **total** | **524** | **388** | **134** | **74%** |

patient_id + billing clear the ≥80% target. `db/audit.py` was triaged: 8 targeted
tests killed the genuinely-killable survivors (71% → 77%), e.g. a **tampered row
after a legacy NULL row is now detected** (the `continue`-not-`break` guard), the
audit fields/detail are asserted persisted verbatim, empty-field handling is
pinned in both verify + rechain, the garbled-anchor guard and the in-place-edit
("same count, different head" → `behind`) anchor path are tested, and the fallback
log's 0600 perms are checked.

The **remaining survivors are genuinely equivalent mutants** — killing them would
be gaming the metric, not strengthening tests:
- SQLite is case-insensitive for keywords AND column names, so `"SELECT … hash"`
  ↔ `"select … HASH"` and `row["hash"]` ↔ `row["HASH"]` are no-ops.
- Python codec names are case-insensitive (`"utf-8"` ↔ `"UTF-8"`), and `encoding=
  None` is the platform default (utf-8) for our ASCII content.
- `[:64]`→`[:65]` truncation only differs at an exact-length boundary; `started =
  None`/`False` are both falsy.
- `report.verify._verify_key` is **self-healing** (regenerates a valid key on a
  bad read), so mutating its read path has no observable effect — which is why
  `verify` sits at 66%; the behavioral mutants (forgery rejection) ARE killed.

Triage survivors with `mutmut results` / `mutmut show <name>`.

---

## Gate status @ baseline

| Gate | Tool | Baseline | Now | Target | Status |
|------|------|----------|-----|--------|--------|
| G1 Lint | ruff (configured select+ignores) | 794 raw | **406** | 0 | 🟡 draining (remainder largely intentional: lazy imports, magic-values, cohesive-but-complex fns) |
| G2 Format | ruff format --check | n/a | **clean** | clean | 🟢 **BLOCKING, met** (repo fully formatted) |
| G3 Types | mypy --strict (scoped, report) | 588 | **555** | 0 | 🟡 draining |
| G3b Types | mypy --strict on security-critical surface | n/a | **0** | 0 | 🟢 **BLOCKING, met** (services + licensing + audit/crypto/patient_id/verify/roles) |
| G4 Architecture | import-linter | 3 kept / 0 broken | **3/0** | 0 broken | 🟢 green — **do not regress** |
| G5 Coverage — critical | pytest-cov (4 trust modules) | 0–68% | **99%** | ≥95 | 🟢 **BLOCKING, met** |
| G5 Coverage — global | pytest-cov | 32% | **33%** | ≥80 (Wave 8) | 🟡 floor 30, ratcheting |
| G9 SAST | bandit | **0 High**, ~18 Medium, ~19 Low | same | 0 High/Med | 🟡 partial |
| G10 Dep CVEs | pip-audit | **0 vulnerabilities** | 0 | 0 | 🟢 green — **do not regress** |

> Four gates now at/near target (import-linter, pip-audit, bandit-High, **critical
> coverage**). The two big debts remain **ruff (741)** and **mypy (588)** — drained
> incrementally per owning wave, never bulk-autofixed.

---

## G1 — ruff findings (794), by rule

| Count | Rule | What | Remediation |
|------:|------|------|-------------|
| 410 | E501 | line-too-long | reflow during the wave that touches each file (don't mass-reformat) |
| 96 | PLC0415 | import-outside-top-level | hoist where safe; some are deliberate lazy imports (keep + `# noqa` w/ reason) |
| 47 | PLR2004 | magic-value-comparison | extract named constants (esp. status strings, money, role caps) |
| 24 | ARG001 | unused-function-argument | Qt slot signatures — prefix `_` or `# noqa` |
| 22 | SIM118 | in-dict-keys | `x in d` not `x in d.keys()` (safe autofix) |
| 21 | N806 | non-lowercase var in function | rename locals |
| 17 | I001 | unsorted-imports | safe autofix (`ruff check --fix`) |
| 16 | PLR0913 | too-many-arguments | dataclass/params object (ties into primitive-obsession debt) |
| 16 | E402 | import-not-at-top | module-level reorg |
| 15 | PLR0915 | too-many-statements | function extraction (god-method debt) |
| 14 | SIM105 | suppressible-exception | `contextlib.suppress` |
| 11 | C901 | complex-structure (CC>10) | **see complexity debt below** |
| 11 | ARG005 | unused-lambda-argument | — |
| ~74 | (other) | UP/N/RUF/PERF/B/SIM/PLW… | per-rule during file-local work |

Safe-autofixable now (review the diff): 22 fixable + 55 unsafe-fixable (`--fix` / `--unsafe-fixes`).
**Policy:** autofix only I001/SIM118-class rules in isolated PRs; everything else is fixed by the wave that owns the file.

## G3 — mypy strict (588 errors / 47 files)

Scoped strict per `pyproject.toml`: `ui.*`, `app`, `whatsapp` are non-strict for now
(folded into strict in Waves 6/8). Largest contributors are missing annotations and
untyped `dict`-shaped data (the `self.user[...]` primitive-obsession pattern, 78×).
Drain order: `db` → `services` → `report`/`render` → `licensing` → presentation.

## Complexity hotspots (C901, CC > 10)

11 functions exceed cyclomatic complexity 10 (max observed in audit: **39**). Tracked
for extraction during their owning wave; do not let any new function exceed 10.

## God-files (> 400 LOC) — 8 violators

| LOC | File | Target |
|----:|------|--------|
| 988 | `src/labdesk/ui/settings.py` | split by settings domain (Wave 6) |
| 857 | `src/labdesk/ui/reception.py` | extract bill-create service (Wave 2) + view split (Wave 6) |
| 736 | `src/labdesk/ui/receipts.py` | extract receipt service + view split (Wave 6) |
| 667 | `src/labdesk/render/report_doc.py` | decompose renderer (Wave 6) |
| 653 | `src/labdesk/ui/catalog.py` | view/service split (Wave 6) |
| 567 | `src/labdesk/ui/worklist.py` | extract result-release service (Wave 2) + view split |
| 512 | `src/labdesk/whatsapp.py` | adapter decomposition (Wave 6) |
| 492 | `src/labdesk/app.py` | composition root cleanup (Wave 3) |

34 functions exceed 60 LOC — tracked, capped at "no new ones."

## G5 — coverage on the trust-core

**Wave 1 CLOSED the four worst gaps** (`tests/test_audit_chain.py`,
`tests/test_report_verify.py`, `tests/test_billing.py`, `tests/test_patient_id.py`,
plus `tests/factories.py`). The CI critical-set gate (`>=95` branch) is live:

| Module | Before | Now | Note |
|--------|------:|----:|------|
| `services/billing.py` | 59% | **100%** | both rounding modes + promo edges pinned |
| `report/verify.py` | 68% | **100%** | HMAC round-trip + forgery + culture/sensitivity |
| `db/patient_id.py` | (low) | **100%** | check-letter round-trip + single-digit catch |
| `db/audit.py` | 41% | **97%** | tamper/delete/rechain/fallback (miss: chmod OSError 27-28) |

**Remaining coverage debt (next waves):**

| Module | Branch cov | Gap |
|--------|-----------:|--------------|
| `db/keyvault.py` | **0%** | entire key-vault path untested — Wave 5 (security depth) |
| `db/connection.py` | 61% | encryption fail-closed branches partial — Wave 5 |
| `licensing/__init__.py` | 64% | signature/expiry failure branches — Wave 5 |
| `db/auth.py` | 86% | lockout/upgrade edges |

Global branch coverage rises as UI is covered (pytest-qt, Wave 6+). Floor gate at 30.

## G9 — bandit (0 High, ~18 Medium, ~19 Low)

0 High-severity. Mediums to triage in Wave 5 (security depth) — most are expected
(subprocess use for portals/printing, `assert` usage). Each will be either fixed or
annotated with `# nosec` + justification so the count goes to 0 unexplained.

## Known architectural debt (tracked, not yet a contract)

- `licensing/__init__.py:89,95` imports `db.paths.data_dir` — a low-level coupling
  from licensing down into db. Acceptable today; invert (move `data_dir` to a neutral
  paths module) in Wave 3 so licensing becomes truly self-contained, then tighten the
  import-linter contract.

---

_Update this file in the same PR that changes any number. The CI debt-budget gate
(G14, activated later) will fail any PR that increases a tracked count._
