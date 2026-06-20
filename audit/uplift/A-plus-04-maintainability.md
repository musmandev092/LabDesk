# LabDesk — Maintainability Uplift Plan (C+ → A/A+)

**Dimension:** Maintainability
**Current grade:** C+ (per `audit/07-clean-code-review.md`)
**Target:** Solid A / A+
**Author:** Agent_Maintainability_Uplift
**Date:** 2026-06-16
**Scope:** PLANNING ONLY. No source/test/config modified. Grounded in `audit/07-clean-code-review.md` plus direct inspection of `pyproject.toml`, `.github/workflows/ci.yml`, and `src/labdesk/` LOC/annotation metrics.

---

## 1. Why we are at C+ today (grounded facts)

From `audit/07-clean-code-review.md` and confirmed against the live tree:

- **Linter is effectively decorative.** `pyproject.toml` declares `ruff>=0.15.17` as a dev dep but ships **no `[tool.ruff]` config** and no `ruff.toml`. Ruff runs on its tiny default set → only **19 findings** visible; under an extended set (`E,F,W,C90,N,UP,B,SIM,PLR,PLW,PLC,RUF,ARG,PERF,C4`) there are **777**. CI (`.github/workflows/ci.yml`) runs pytest + a headless self-test only — **no lint gate, no type gate, no complexity gate**.
- **No static typing gate at all.** No `mypy`/`pyright`/`ty` in deps or CI. (Good news baseline: **459 of 525 `def`s already carry a `-> return` annotation (~87%)** — the project is much closer to type-clean than the grade implies; the gap is enforcement + the last ~13% + parameter annotations.)
- **No `.pre-commit-config.yaml`.** Nothing prevents a non-conforming commit locally.
- **Four UI god-classes** mix construction + validation + business rules + DB + print/export:
  - `ui/settings.py` → `SettingsPage` **927 LOC / 36 methods** (file 988 LOC)
  - `ui/reception.py` → `ReceptionPage` **802 LOC / 23 methods** (file 857 LOC)
  - `ui/receipts.py` → `ReceiptsPage` **684 LOC / 30 methods** (file 736 LOC)
  - `ui/worklist.py` → `WorklistPage` **526 LOC** (file 567 LOC)
  - Plus 4 more files >400 LOC: `render/report_doc.py` 667, `ui/catalog.py` 653, `whatsapp.py` 512, `app.py` 492.
- **Worst complexity/length offenders:** `app.run` (CC **39**, 195 LOC), `ReceptionPage.save` (CC **38**, 206 LOC), `whatsapp.send_pdf` (CC **32**, 88 LOC), `build_receipt` (CC 26, 245 LOC), `ReceptionPage.__init__` (248 LOC), `build_qss` (160 LOC). **34 functions exceed 60 LOC; 11 trigger C901.**
- **Duplication ~3–4%**, concentrated in `whatsapp.py` (`send_pdf` vs `send_text` ~40-line response-handling clone, `:322-365` vs `:466-…`).
- **Primitive obsession:** current user passed as a bare `dict`; **78× `self.user["…"]`, 35× `["role"]`**. Data clump `(con, user)` recurs across **11 UI classes**.

**Hygiene is already A** (zero F401/F811/F841, zero bare `except:`); **comments are A−**. So the deficit is purely **structure, enforcement, and typing**, which is the most mechanically tractable kind of debt to close.

---

## 2. What "A+" means for this dimension (authoritative, with sources)

### 2.1 Complexity & size thresholds
- **Cyclomatic complexity ≤ 10 per function.** McCabe's original 1976 paper set 10 as the practical upper bound; this remains the industry default. ([Wikipedia — Cyclomatic complexity](https://en.wikipedia.org/wiki/Cyclomatic_complexity), [Sourcegraph](https://sourcegraph.com/blog/cyclomatic-complexity-what-it-is-and-how-to-reduce-it))
- **Radon CC rank A = 1–5, B = 6–10, C = 11–20, D = 21–30, E = 31–40, F = 41+.** A+ target: every function ≥ rank B (CC ≤ 10), aspirationally rank A (≤ 5) for non-UI code. ([Radon — commandline docs](https://radon.readthedocs.io/en/latest/commandline.html), [Radon — intro](https://radon.readthedocs.io/en/latest/intro.html))
- **Radon Maintainability Index (MI):** rank **A = 100–20 (very high)**, B = 19–10 (medium), C = 9–0 (extremely low). A+ target: **every file rank A (MI ≥ 20)** with no exceptions. (Radon docs caveat: MI is experimental — we treat it as a directional gate, not a hard one.) ([Radon — commandline docs](https://radon.readthedocs.io/en/latest/commandline.html))
- **Cognitive complexity ≤ 15 per function** (SonarSource), the understandability-oriented companion to cyclomatic. Use as a secondary gate where cyclomatic is artificially inflated/deflated. ([Sonar — Cognitive Complexity](https://www.sonarsource.com/blog/cognitive-complexity-because-testability-understandability), [Sonar — Cyclomatic Complexity guide](https://www.sonarsource.com/resources/library/cyclomatic-complexity/))
- **Project-specific A+ bar (from the task brief, adopted):** **no file > 400 LOC; no function > 60 LOC; CC ≤ 10** (or an explicit, reviewed `# noqa: C901` justification with a comment).

### 2.2 Static typing
- **mypy `--strict` on non-UI layers, enforced in CI.** Strict mode turns on `disallow_untyped_defs`, `disallow_incomplete_defs`, `check_untyped_defs`, `warn_return_any`, `no_implicit_optional`, etc. ([mypy strict config — pydevtools](https://pydevtools.com/handbook/how-to/how-to-configure-mypy-strict-mode/), [mypy strict — Hrekov](https://hrekov.com/blog/mypy-configuration-for-strict-typing))
- **Why mypy for the gate, pyright as a dev aid:** pyright checks *everything* including unannotated defs by inference and is faster, but mypy is the stable CI gate of record and integrates cleanly with `uv run`. Best-practice guidance is "enable strict and selectively disable friction flags," and to be aware mypy skips unannotated defs unless `--strict`/`--check-untyped-defs` is set (else you get false "no errors"). We use **mypy --strict in CI** + recommend **pyright/basedpyright in the editor**. ([mypy vs pyright vs ty — danilchenko.dev](https://www.danilchenko.dev/posts/ty-vs-mypy-vs-pyright/), [basedpyright mypy-comparison](https://docs.basedpyright.com/v1.38.2/usage/mypy-comparison/), [pyright mypy-comparison](https://github.com/microsoft/pyright/blob/main/docs/mypy-comparison.md))
- **A+ target: 100% type coverage on `db/`, `services/`, `render/`, `report/`, `licensing/` (the ~5,282 LOC non-UI core) with `mypy --strict` at zero errors.** UI (`ui/`, `app.py`, `whatsapp.py`) starts at non-strict mypy (catch obvious errors) and graduates to strict last.

### 2.3 Lint, format, duplication, hooks
- **Ruff with an expanded ruleset at zero violations**, `line-length` set, `mccabe.max-complexity = 10`, per-file ignores for the few legitimate exceptions (Qt CamelCase in `ui/widgets.py`, crypto-spec names in `licensing/_ed25519.py`). ([Ruff tutorial](https://docs.astral.sh/ruff/tutorial/), [Scientific-Python style guide](https://learn.scientific-python.org/development/guides/style/))
- **Ruff formatter** as the single formatting authority (replaces Black); `ruff format --check` in CI. ([Ruff + pre-commit guide](https://medium.com/@kutayeroglu/automate-python-formatting-with-ruff-and-pre-commit-b6cd904b727e))
- **pre-commit enforced** with `ruff-check --fix` *before* `ruff-format`, plus mypy. ([astral-sh/ruff-pre-commit](https://github.com/astral-sh/ruff-pre-commit))
- **Duplication target: < 1% of src LOC** (down from ~3–4%), measured with a clone detector (`pylint --disable=all --enable=duplicate-code` or `jscpd`).
- **SOLID — Single Responsibility:** no class mixing UI construction + business logic + persistence; god-classes decomposed via **Extract Class / Extract Method**, and the gateway response ladder via **Replace Conditional with Polymorphism / Extract Function** (Fowler's *Refactoring*).

### 2.4 The A+ acceptance checklist (binary, CI-gated)
| Gate | A (table-stakes) | A+ (stretch) |
|------|------------------|--------------|
| Max file LOC | ≤ 400 (UI may carry ≤ 3 documented exceptions) | ≤ 400, zero exceptions |
| Max function LOC | ≤ 60 | ≤ 50 |
| Cyclomatic complexity | ≤ 10 (ruff `C901` clean) | ≤ 10, and ≤ 5 (Radon rank A) for non-UI |
| Cognitive complexity | ≤ 15 | ≤ 15 |
| Radon MI | ≥ 20 (rank A) every file | ≥ 20, with `wily` trend non-regressing in CI |
| mypy `--strict` | zero errors on non-UI core | zero errors repo-wide |
| Ruff (expanded set) | zero violations | zero, with `RUF`+`PERF`+`PL*` on |
| Duplication | < 2% | < 1% |
| pre-commit | configured | enforced + CI re-runs identical hooks |

---

## 3. Gap-closing plan (ordered, evidence-tied)

Ordering principle: **enforcement scaffolding first** (cheap, prevents regression while you refactor), **then mechanical lint cleanup**, **then the structural god-class splits** (highest risk, gated by the now-passing test suite + selftest in `ci.yml`).

> Effort: S ≤ ½ day · M ≈ 1–3 days · L > 3 days. Risk reflects blast radius on a HIGH-criticality medical write path.

### Phase 0 — Establish the gates (do first, low risk, high leverage)

**0.1 Add a real `[tool.ruff]` config** — *S / Low risk / High impact*
Files: `pyproject.toml`.
Add `line-length = 100`, `[tool.ruff.lint] select = ["E","F","W","I","C90","N","UP","B","SIM","PLR","PLW","PLC","RUF","ARG","PERF","C4"]`, `[tool.ruff.lint.mccabe] max-complexity = 10`, and `[tool.ruff.lint.per-file-ignores]` for `ui/widgets.py` (N802/N803/N812 — Qt API override) and `licensing/_ed25519.py` (N806 — crypto spec). Satisfies: §2.3 ruleset; addresses audit M1 ("linter effectively decorative"). Note: this initially surfaces ~777 findings — that is expected and drained in Phase 1.

**0.2 Add `mypy` (strict, scoped) + config** — *S / Low / High*
Files: `pyproject.toml` (add `mypy` to dev group; `[tool.mypy]` with `strict = true` and a `[[tool.mypy.overrides]]` block setting non-strict for `module = ["labdesk.ui.*","labdesk.app","labdesk.whatsapp"]` initially). Satisfies: §2.2. Recommend `pyright`/`basedpyright` as editor-only dev aid (not a CI gate) per source comparison.

**0.3 Add `.pre-commit-config.yaml`** — *S / Low / Med*
Files: new `.pre-commit-config.yaml`. Hooks in order: `ruff-check` (`args: [--fix]`) → `ruff-format` → `mypy` (local hook via `uv run mypy`). Pin `ruff-pre-commit` to the installed ruff rev. Satisfies: §2.3 pre-commit; uses the documented "lint before format" ordering.

**0.4 Wire lint + type + format gates into CI** — *S / Low / High*
Files: `.github/workflows/ci.yml`. Add steps before the pytest step: `uv run ruff format --check src tests`, `uv run ruff check src tests`, `uv run mypy src`. Satisfies: §2.4 (CI-gated). This converts every later phase into a non-regressing ratchet.

**0.5 (Stretch) Add complexity/MI trend reporting** — *S / Low / Med*
Files: `.github/workflows/ci.yml`, `pyproject.toml` (recommend `radon` + `wily` as dev deps — recommendation only, requires install approval). Add a non-blocking `radon cc src -nc` + `radon mi src -nb` report step, and a `wily` baseline so MI/CC regressions show in PRs. Satisfies: §2.1 MI gate, §2.4 A+ wily trend.

### Phase 1 — Drain the mechanical lint debt (medium, low risk)

**1.1 Auto-fixable sweep** — *S / Low / Med*
`ruff check --fix` + `ruff format` clears import sorting, many `SIM`/`UP`/`C4`/`PERF` (e.g. `SIM118` ×22, `UP031` ×6, `PERF401` ×2). Run as one reviewable formatting commit. Files: repo-wide. Satisfies: §2.3.

**1.2 Fix `E501` line-too-long (410)** — *M / Low / Med*
`ruff format` resolves most; remainder are long strings needing manual wrap. Files: across `src/` (386) + `tests/` (24). Satisfies: §2.3.

**1.3 Name magic numbers (47× PLR2004 / 42 in src)** — *S / Low / Med*
Extract module constants in hot spots: `render/image.py` (`8,16,40,235` pixel thresholds, `:26-:41`), `licensing/_ed25519.py` (`32,64`, `:105-148`), `report/formatting.py:171-178` (`20,100`), `ui/login.py:139` (`6` min password length). Satisfies: §2.1 readability, magic-value smell §5.

**1.4 Clean `import-outside-top-level` (96× PLC0415) + `E402` (16)** — *M / Med / Med*
Many are deliberate lazy imports (Qt/heavy modules). Hoist the safe ones; for genuine lazy-load cases add justified `# noqa: PLC0415` with a one-line reason. Files: `ui/*`, `app.py`. Risk Med because some lazy imports break import cycles / speed up startup — verify with the `LABDESK_SELFTEST` path in `ci.yml`. Satisfies: §2.3.

**1.5 Purge stale `noqa` (5× RUF100) + sort `__all__` (3× RUF022)** — *S / Low / Low*
Remove dead directives at `db/__init__.py:19-28`, `ui/receipts.py:412,465`, `ui/widgets.py:43-71`. Satisfies: audit M2.

**1.6 Tighten exception swallowing (14× SIM105 bare try/except/pass)** — *S / Med / Med*
Replace with `contextlib.suppress(SpecificError)` + debug log at `app.py:178`, `app.py:225`, `db/connection.py:393`, `ui/main_window.py:276`. Risk Med: in a medical system, silent broad swallows can mask failures — narrow the caught type, do not just silence the rule. Satisfies: §5 exception smell.

**1.7 Misc naming/format:** rename `l` (`report/content.py:177`, E741); fix 6× UP031 printf in `db/connection.py:93,224,257,284` + `ui/reception.py:474`; review 8× RUF001 unicode dashes. — *S / Low / Low*.

### Phase 2 — Type-coverage to 100% on the non-UI core (medium, low risk)

**2.1 Make `db/`, `services/`, `render/`, `report/`, `licensing/` pass `mypy --strict`** — *M / Low / High*
~5,282 LOC, already ~87% return-annotated, so this is closing the last mile: add parameter annotations, eliminate implicit `Optional`, type the `con` cursor/connection and row tuples. Files: all non-UI packages. Satisfies: §2.2 (100% non-UI type coverage), the A row of §2.4. This is the single biggest grade-mover for the "100% typing on non-UI layers" criterion and directly de-risks the untested trust code (`db/audit.py`, `report/verify.py`, `services/billing.py`).

**2.2 Introduce typed domain primitives** — *M / Med / High*
New `src/labdesk/session.py` (or in `db/`): frozen `@dataclass(frozen=True) class User(id: int, name: str, role: Role)` with a `Role` `StrEnum`, and an `AppContext`/`Session` bundling `(con, user)`. Then thread the type through. Files (consumers): `ui/dashboard.py:13`, `ui/doctors.py:73`, `ui/logs.py:86`, `ui/worklist.py:43`, `ui/accounts.py:30`, `ui/microbiology.py:30`, `ui/receipts.py:54`, `ui/main_window.py:68`, `ui/settings.py:63`, `ui/catalog.py:266`, `ui/reception.py`. Kills the **78× `self.user["…"]` / 35× `["role"]`** primitive obsession and the **11-class `(con, user)`** data clump — typos become mypy errors, not runtime faults. Risk Med (broad touch) but each call site is mechanical and test+selftest covered. Satisfies: §5 primitive obsession + data clump; enables strict typing of UI later.

### Phase 3 — Kill duplication & long parameter lists (medium, low–med risk)

**3.1 Extract `_interpret_gateway_reply(status, body, number) -> tuple[bool, str]`** — *M / Med / High*
Files: `whatsapp.py` (`send_pdf:294` + `send_text:451`, dup blocks `:322-365`/`:466-…`). Replaces the cloned 2xx/401/403 ladder and `not_linked`/`success` inference; this also drops `send_pdf` CC from 32 and `send_text` CC from 27. Consider **Replace Conditional with Polymorphism** (a small `GatewayReply` result type) for A+. Risk Med: gateway semantics are behavioural — guard with a focused unit test on the extracted function (also closes a coverage gap). Satisfies: §4 duplication #1 (shotgun-surgery risk), §2.1 complexity.

**3.2 Extract dialog button-row helper** — *S / Low / Med*
Add `OkCancelDialog` base / `_dialog_buttons()` in `ui/widgets.py`; adopt in `ui/doctors.py:53`, `ui/receipt_dialogs.py:153`, `ui/settings_dialogs.py:46`, `ui/catalog.py:72`. Satisfies: §4 duplication #2.

**3.3 Collapse long parameter lists (16× PLR0913)** — *M / Med / Med*
Introduce small geometry/style dataclasses for render primitives: `render/_shared.py:79` (**11 args**), `render/primitives.py:163` (9), `render/report_doc.py:409` (8), `whatsapp.py:246`/`ui/wa.py:18` (7). Satisfies: §5 long-parameter-list smell, §2.1.

### Phase 4 — God-class & god-method decomposition (large, the headline grade-mover)

This is where **D+ class-size / SRP** becomes A. Use Extract Class (split by responsibility) + Extract Method (split construction). All four pages are exercised by the `LABDESK_SELFTEST` headless build path in `ci.yml` plus the GUI tests — refactor under green.

**4.1 `ui/settings.py` — `SettingsPage` 927 LOC / 36 methods → tabbed sub-pages** — *L / Med / High*
Split the catch-all into one widget per concern, each owning its own state, composed by a thin `SettingsPage` shell:
- `settings_general.py` (general settings + theme; `SettingsPage.save:841`, CC 19, → `GeneralSettingsTab`)
- `settings_whatsapp.py` (WhatsApp config)
- `settings_backup.py` (DB backup/restore)
Target: shell ≤ 150 LOC, each tab ≤ 300 LOC, every method ≤ 60 LOC / CC ≤ 10. Satisfies: §3 god-class, SRP (§2.3), no-file-> 400 (§2.4).

**4.2 `ui/reception.py` — `ReceptionPage` 802 LOC** — *L / High / High*
Two distinct splits:
- **`ReceptionPage.__init__` (248 LOC, CC 2)** → Extract Method into `_build_patient_panel()`, `_build_tests_panel()`, `_build_totals_panel()`, `_build_actions()`. Pure construction, low risk.
- **`ReceptionPage.save` (206 LOC, CC 38)** → Extract a non-UI **`services/billing` orchestration** path: `validate()`, `resolve_patient_identity()`, `persist_bill()`, `print_outputs()`. *Note:* this overlaps the systemic security finding (bill creation runs inline in the widget with no `require()`/service boundary). Coordinate with the Security uplift; here, the maintainability win is the method split + CC reduction. **Risk High** — highest-stakes write path; gate with the GUI end-to-end tests already in `tests/`. Satisfies: §2 worst-offender #2, §3 god-class, SRP.

**4.3 `ui/receipts.py` — `ReceiptsPage` 684 LOC / 30 methods** — *L / Med / High*
Extract a `ReceiptsController`/service for `edit_receipt:584` (CC 21) persistence and split `__init__:54` (161 LOC) into `_build_*` helpers. Move receipt math/persistence behind `services/receipts.py` (already exists for lesser mutations). Satisfies: §3 god-class.

**4.4 `ui/worklist.py` — `WorklistPage` 526 LOC** — *M / High / High*
Decompose `save_results:425` (CC 20, clinical result release — security-sensitive) and `_build_test_block:327` (96 LOC, CC 20). Same coordination note as 4.2: route the release through a service with `require()`. Satisfies: §2 offenders #9/#10, §3.

**4.5 `app.run` — 195 LOC, CC 39 (worst in repo)** — *M / Med / High*
Files: `app.py:289`. Extract `_single_instance_guard()`, `_show_splash()`, `_check_license()`, `_apply_theme()`, `_unlock_db()` as standalone functions; `run` becomes a ~30-line orchestrator. Pure bootstrap, well-covered by the selftest. Satisfies: §2 worst-offender #1, §2.1 CC ≤ 10.

**4.6 `render/report_doc.py` (667 LOC) + `render/receipt.py build_receipt` (245 LOC, CC 26)** — *L / Med / Med*
Split `build_receipt:31` and `_draw_test_table:274` (133 LOC) into per-section draw helpers; consider a `ReceiptLayout` builder. `report_doc.py` exceeds 400 LOC — split into `report_doc/` package (header, test-table, footer). Satisfies: §2 offenders #6, no-file-> 400.

**4.7 `ui/catalog.py` (653 LOC) + `whatsapp.py` (512 LOC, post-3.1)** — *M / Med / Med*
`catalog.py` → split editor vs. list views. `whatsapp.py` shrinks materially after 3.1; split transport vs. message-construction if still > 400. Satisfies: no-file-> 400.

### Phase 5 — Lock the ratchet (small, low risk)

**5.1 Flip CI gates to hard-fail and remove the UI strict-mypy override** — *S / Low / High*
Once Phase 4 lands, promote `ui/`, `app.py`, `whatsapp.py` into `mypy --strict` (remove the §0.2 override), and make `radon cc src -nc B`/`radon mi src -nb A` (recommend) blocking. Files: `pyproject.toml`, `.github/workflows/ci.yml`. Satisfies: A+ column of §2.4 (repo-wide strict, MI rank A everywhere, wily non-regressing).

---

## 4. Effort & sequencing summary

| Phase | Theme | Effort | Risk | Grade contribution |
|-------|-------|--------|------|--------------------|
| 0 | Gates: ruff/mypy/pre-commit/CI config | S×5 | Low | Tooling C→A; prevents regression |
| 1 | Drain 777 lint findings | M | Low–Med | Lint config C→A, complexity surfacing |
| 2 | 100% strict typing on non-UI core + typed `User`/`Session` | M | Low–Med | **Typing 0→A**, kills primitive obsession/data clump |
| 3 | De-dup `whatsapp.py`, params | M | Med | Duplication B→A, complexity |
| 4 | God-class / god-method splits | L | Med–High | **Class-size D+→A** (headline) |
| 5 | Repo-wide strict + blocking MI/CC | S | Low | A→A+ |

Phases 0–3 alone (no high-risk write-path refactor) move Maintainability **C+ → A−**. Phase 4 is required for solid **A**; Phase 5 for **A+**. Phases 0–1 can land immediately and independently; Phase 4 items are independent of each other and each gated by the existing test + selftest suite.

---

## 5. Recommended tools (adopt; all require install approval)

| Tool | Purpose | Gate? | Source |
|------|---------|-------|--------|
| **ruff** (already a dep) | lint (expanded set) + format + `C901` complexity | CI hard-fail | [Ruff tutorial](https://docs.astral.sh/ruff/tutorial/) |
| **mypy** `--strict` | static type gate (CI of record) | CI hard-fail | [mypy strict config](https://pydevtools.com/handbook/how-to/how-to-configure-mypy-strict-mode/) |
| **pyright / basedpyright** | editor-time type aid (checks unannotated by inference, faster) | dev only | [pyright mypy-comparison](https://github.com/microsoft/pyright/blob/main/docs/mypy-comparison.md) |
| **pre-commit** | local hook enforcement (`ruff-check`→`ruff-format`→`mypy`) | local gate | [ruff-pre-commit](https://github.com/astral-sh/ruff-pre-commit) |
| **radon** | cyclomatic-complexity + maintainability-index reporting (CC rank B, MI rank A) | CI report→gate | [Radon docs](https://radon.readthedocs.io/en/latest/commandline.html) |
| **wily** | MI/CC trend across commits (non-regression in PRs) | CI report | [Radon intro](https://radon.readthedocs.io/en/latest/intro.html) |
| **jscpd** or `pylint --enable=duplicate-code` | duplication < 1% measurement | CI report | (clone detection; pairs with §2.3 dup target) |

---

## 6. Concrete A+ acceptance criteria (copy into the definition-of-done)

1. `uv run ruff format --check src tests` → clean; `uv run ruff check src tests` (expanded select, `max-complexity = 10`) → **0 findings** (down from 777).
2. `uv run mypy src` (`--strict`) → **0 errors**, with **0** `# type: ignore` outside a documented allowlist; non-UI core (`db/services/render/report/licensing`, ~5,282 LOC) at 100% annotation.
3. `radon cc src -nc` → no function ranked below **B** (CC ≤ 10); justified `# noqa: C901` only with a reviewed comment.
4. `radon mi src -nb` → every file rank **A** (MI ≥ 20).
5. **No file > 400 LOC** (today 8 files violate: settings 988, reception 857, receipts 736, report_doc 667, catalog 653, worklist 567, whatsapp 512, app 492); **no function > 60 LOC** (today 34 violate).
6. Duplication **< 1%** of src LOC (today ~3–4%); the `whatsapp.py` clone is gone.
7. `.pre-commit-config.yaml` present and identical hooks re-run in CI; CI **hard-fails** on lint/format/type/complexity.
8. No bare `dict`-keyed user access (`self.user["role"]`) remains — replaced by typed `User`/`Session`.

---

## 7. Sources

- McCabe cyclomatic complexity, "10" as the practical bound — [Wikipedia](https://en.wikipedia.org/wiki/Cyclomatic_complexity), [Sourcegraph](https://sourcegraph.com/blog/cyclomatic-complexity-what-it-is-and-how-to-reduce-it)
- Radon CC ranks (A 1–5 … F 41+) and MI ranks (A 100–20, B 19–10, C 9–0) — [Radon commandline](https://radon.readthedocs.io/en/latest/commandline.html), [Radon intro](https://radon.readthedocs.io/en/latest/intro.html)
- Cognitive complexity threshold (15) and rationale — [Sonar cognitive complexity](https://www.sonarsource.com/blog/cognitive-complexity-because-testability-understandability), [Sonar cyclomatic guide](https://www.sonarsource.com/resources/library/cyclomatic-complexity/)
- mypy strict mode config — [pydevtools](https://pydevtools.com/handbook/how-to/how-to-configure-mypy-strict-mode/), [Hrekov](https://hrekov.com/blog/mypy-configuration-for-strict-typing)
- mypy vs pyright vs ty (gate choice, coverage of unannotated defs) — [danilchenko.dev](https://www.danilchenko.dev/posts/ty-vs-mypy-vs-pyright/), [basedpyright](https://docs.basedpyright.com/v1.38.2/usage/mypy-comparison/), [pyright](https://github.com/microsoft/pyright/blob/main/docs/mypy-comparison.md)
- Ruff config, formatter, max-complexity, pre-commit ordering — [Ruff tutorial](https://docs.astral.sh/ruff/tutorial/), [ruff-pre-commit](https://github.com/astral-sh/ruff-pre-commit), [Ruff+pre-commit](https://medium.com/@kutayeroglu/automate-python-formatting-with-ruff-and-pre-commit-b6cd904b727e), [Scientific-Python style guide](https://learn.scientific-python.org/development/guides/style/)
