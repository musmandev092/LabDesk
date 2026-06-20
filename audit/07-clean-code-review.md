# LabDesk — Clean Code & Refactoring Review (Audit 07)

**Auditor:** Agent_CleanCode (Principal Refactoring Lead)
**Scope:** READ-ONLY static review of `src/labdesk/` (~13,859 LOC) and `tests/` (~778 LOC).
**Toolchain:** ruff 0.15.17, custom Python `ast` complexity analysis.
**Date:** 2026-06-16

## Headline grade: **C+**

The codebase is **clean where it counts on hygiene** — zero unused imports, zero unused
locals, zero bare `except:`, zero redefinitions (`ruff F401/F811/F841` = *all checks
passed*). Comments are unusually high-quality: dense, intent-revealing, and explaining
*why* (e.g. the defence-in-depth discount note at `ui/reception.py:635-637`). However the
**UI layer carries serious structural debt**: four "god" page classes (527–927 LOC),
several 100–248 LOC methods, and cyclomatic complexity up to 39. The mechanical lint
debt is also non-trivial (777 findings under an extended ruleset) and the project's own
`noqa` directives have drifted out of sync with its enabled rules. None of this is a
correctness or security defect, but it raises the cost of every future change in
`ui/settings.py`, `ui/reception.py`, `ui/receipts.py`, and `whatsapp.py`.

---

## 1. Ruff statistics (the real numbers)

### 1a. Default configuration (what the project actually enforces today)
The project ships **no `[tool.ruff]` config** in `pyproject.toml` and no `ruff.toml`, so
ruff runs on its tiny default rule set. Under defaults:

```
$ ruff check src/ tests/ --statistics
16  E402  module-import-not-at-top-of-file
 2  E731  lambda-assignment
 1  E741  ambiguous-variable-name
Found 19 errors.
```

Only **19 findings** are visible with defaults — this dramatically understates the actual
maintainability debt because complexity, magic-value, too-many-* and naming rules are all
off. **This is itself a finding (M1): the linter is effectively decorative.**

### 1b. Extended ruleset (`E,F,W,C90,N,UP,B,SIM,PLR,PLW,PLC,RUF,ARG,PERF,C4`)
```
$ ruff check src/ tests/ --select E,F,W,C90,N,UP,B,SIM,PLR,PLW,PLC,RUF,ARG,PERF,C4 --statistics
410  E501     line-too-long
 96  PLC0415  import-outside-top-level
 47  PLR2004  magic-value-comparison
 24  ARG001   unused-function-argument
 22  SIM118   in-dict-keys
 21  N806     non-lowercase-variable-in-function
 16  E402     module-import-not-at-top-of-file
 16  PLR0913  too-many-arguments
 15  PLR0915  too-many-statements
 14  SIM105   suppressible-exception
 11  ARG005   unused-lambda-argument
 11  C901     complex-structure
  8  RUF001   ambiguous-unicode-character-string
  6  N802     invalid-function-name
  6  N803     invalid-argument-name
  6  PLR0911  too-many-return-statements
  6  UP031    printf-string-formatting
  5  N812     lowercase-imported-as-non-lowercase
  5  PLR0912  too-many-branches
  5  RUF100   unused-noqa
  4  SIM102   collapsible-if
  3  B007     unused-loop-control-variable
  3  PLW0603  global-statement
  3  RUF022   unsorted-dunder-all
  2  ARG002   unused-method-argument
  2  E731     lambda-assignment
  2  PERF401  manual-list-comprehension
  2  PLW0108  unnecessary-lambda
  1  C416 / E741 / PLW1510 / RUF005 / SIM103 / SIM115   (1 each)
Found 777 errors.
```
Split: `E501` line-too-long = **386 in src + 24 in tests**. Magic values = **42 in src**.

---

## 2. Worst offenders (complexity & length)

Cyclomatic complexity (CC) measured via `ast` (decision points + boolean operands +
comprehension clauses + 1). LOC = source span of the function/method.

| # | Function | Location (file:line) | LOC | CC | Notes |
|---|----------|----------------------|----:|---:|-------|
| 1 | `run` | `app.py:289` | 195 | **39** | App bootstrap: single-instance, splash, license, theme, DB unlock all inlined. ruff: C901 32, PLR0915 104 stmts, PLR0912 33 branches. |
| 2 | `ReceptionPage.save` | `ui/reception.py:627` | 206 | **38** | Validation + patient-identity resolution + persistence + printing in one method. ruff: C901 20, PLR0915 87. |
| 3 | `send_pdf` | `whatsapp.py:294` | 88 | **32** | HTTP + JSON + status interpretation. ruff: C901 24, PLR0912 24. |
| 4 | `autocrop_image` | `render/image.py:8` | 66 | **27** | Pixel-threshold loop, 10+ magic numbers (8/16/40/235). |
| 5 | `send_text` | `whatsapp.py:451` | 62 | **27** | ~Duplicate of `send_pdf` response handling (see §4). |
| 6 | `build_receipt` | `render/receipt.py:31` | 245 | **26** | Largest non-`__init__` render routine; PLR0915 116 stmts. |
| 7 | `ReceiptsPage.edit_receipt` | `ui/receipts.py:584` | 85 | **21** | C901 14, PLR0912 14. |
| 8 | `save_test_parameters` | `db/queries.py:124` | 64 | **21** | Branch-heavy persistence. |
| 9 | `WorklistPage.save_results` | `ui/worklist.py:425` | 115 | **20** | C901 12. |
| 10 | `WorklistPage._build_test_block` | `ui/worklist.py:327` | 96 | **20** | |
| 11 | `SettingsPage.save` | `ui/settings.py:841` | 78 | **19** | C901 13. |
| 12 | `_ref_lines` | `render/report_doc.py:189` | 17 | **19** | Very high CC/LOC ratio — dense branching in 17 lines. |

**Longest methods (> 60 LOC threshold; 34 functions exceed it):**

| Function | Location | LOC | CC |
|----------|----------|----:|---:|
| `ReceptionPage.__init__` | `ui/reception.py:57` | **248** | 2 |
| `build_receipt` | `render/receipt.py:31` | 245 | 26 |
| `ReceptionPage.save` | `ui/reception.py:627` | 206 | 38 |
| `run` | `app.py:289` | 195 | 39 |
| `ReceiptsPage.__init__` | `ui/receipts.py:54` | 161 | 6 |
| `build_qss` | `ui/style.py:98` | 160 | 2 |
| `SetupWizard.__init__` | `ui/setup_wizard.py:30` | 144 | 2 |
| `MainWindow.__init__` | `ui/main_window.py:68` | 139 | 12 |
| `_draw_test_table` | `render/report_doc.py:274` | 133 | 13 |

The `__init__` methods with low CC but 130–248 LOC are **UI-construction god-methods**:
straight-line widget assembly that should be decomposed into `_build_<section>()` helpers
for readability and testability.

---

## 3. Long classes (god objects) — `> 300 LOC`

| Class | Location | LOC | Methods | Severity |
|-------|----------|----:|--------:|----------|
| `SettingsPage` | `ui/settings.py:62` | **927** | 36 | High |
| `ReceptionPage` | `ui/reception.py:56` | **802** | 23 | High |
| `ReceiptsPage` | `ui/receipts.py:53` | **684** | 30 | High |
| `WorklistPage` | `ui/worklist.py:42` | **526** | 16 | Medium |

These four classes mix UI construction, input validation, business rules, DB access, and
print/export orchestration. `SettingsPage` (927 LOC / 36 methods) in particular is a
catch-all (general settings, WhatsApp config, DB backup/restore, theme) and is the prime
candidate for splitting into tabbed sub-pages each owning its own state.

---

## 4. Duplication

A 6-line sliding-window hash over `src/` found **74 distinct duplicated blocks**. The two
that matter:

1. **WhatsApp send response-handling (HIGH).** `send_pdf` (`whatsapp.py:294`) and
   `send_text` (`whatsapp.py:451`) share a near-identical ~40-line block: JSON parse
   (`j = None; try: parsed = json.loads(body)…`), `not_linked` detection, `success`
   inference from `success`/`error`/`code`, and the 2xx/401/403 message ladder
   (`whatsapp.py:322-365` vs `whatsapp.py:466-...`). This is **shotgun surgery risk**: any
   change to gateway response semantics must be made in two places and they will drift.
   Extract a shared `_interpret_gateway_reply(status, body, number) -> (bool, str)`.

2. **Dialog button-row boilerplate (MEDIUM).** The
   `ok = QPushButton("OK") / cancel = QPushButton("Cancel") / cancel.setObjectName("ghost")
   / ok.clicked.connect(self.accept) / cancel.clicked.connect(self.reject)` pattern is
   copy-pasted in `ui/doctors.py:53`, `ui/receipt_dialogs.py:153`,
   `ui/settings_dialogs.py:46`, and `ui/catalog.py:72`. Extract a `_dialog_buttons(self)`
   helper or a shared `OkCancelDialog` base.

Duplicate Qt import blocks across `ui/worklist.py`, `ui/microbiology.py`, `ui/catalog.py`
(`QSizePolicy, QSplitter, …`) are cosmetic and acceptable for Qt.

Estimated duplication: **~3–4% of src LOC** — low overall, concentrated in `whatsapp.py`.

---

## 5. Code smells (with locations)

- **Primitive obsession — `user` as a dict (HIGH-ish, pervasive).** The current user is
  passed everywhere as a bare `dict` and indexed by string keys: **78** occurrences of
  `self.user["…"]` and **35** of `["role"]` across the UI. There is no `User`/`Session`
  type, so a typo'd key fails at runtime, not at lint time, and `role` capability checks
  are stringly-typed. Recommend a frozen `dataclass User(id, name, role)`.
- **Data clump — `(con, user)` (MEDIUM).** Eleven UI classes take exactly `(con, user)`
  together: `ui/dashboard.py:13`, `doctors.py:73`, `logs.py:86`, `worklist.py:43`,
  `accounts.py:30`, `microbiology.py:30`, `receipts.py:54`, `main_window.py:68`,
  `settings.py:63`, `catalog.py:266`, … This recurring pair is a textbook data clump that
  should become a single `AppContext`/`Session` object.
- **Magic numbers (MEDIUM).** 42 in src. Hot spots: `render/image.py` (`8, 16, 40, 235` —
  pixel thresholds, `:26-:41`), `licensing/_ed25519.py` (`32, 64` key/sig sizes,
  `:105-:148`), `report/formatting.py:171-178` (`20, 100`), `ui/login.py:139` (`6` —
  likely min password length). Name these as module constants.
- **Long parameter lists (MEDIUM).** 16 × PLR0913. Worst: `render/_shared.py:79` (**11
  args**), `render/primitives.py:163` (9), `render/report_doc.py:409` (8),
  `whatsapp.py:246`/`ui/wa.py:18` (7). Render primitives should take a small geometry/style
  struct.
- **Exception swallowing (MEDIUM).** 37 `except Exception` blocks; 14 are bare
  `try/except/pass` (SIM105), e.g. `app.py:178`, `app.py:225`, `db/connection.py:393`,
  `ui/main_window.py:276`. None are bare `except:` (good), but silent broad swallows can
  mask failures in a medical system — prefer `contextlib.suppress(SpecificError)` with the
  narrowest type, and log at debug.
- **`global` mutable state (LOW).** `db/connection.py:69,74` (`_SESSION_KEY`) and
  `render/fonts.py:24` (`_FAMILY`) use `global` to mutate module singletons — acceptable
  but worth wrapping in a small holder object for testability.
- **Lambdas as functions / unnecessary lambdas (LOW).** `render/image.py:51-52` (E731),
  `PLW0108` ×2 (`lambda x: f(x)` wrappers).
- **printf `%` formatting (LOW).** 6 × UP031 in `db/connection.py:93,224,257,284` and
  `ui/reception.py:474` — modernize to f-strings/`.format`.

---

## 6. Naming quality

Mostly good and descriptive (`_promo_pct`, `validate_patient_id`, `_discount_approved_by`).
Exceptions:
- **21 × N806** non-lowercase locals — mostly *legitimate* in `licensing/_ed25519.py`
  (`A,B,C,D,E,F`, `:43-47`) where they mirror the crypto reference spec; acceptable but
  should be `# noqa`-justified rather than left to a disabled rule.
- **6 × N802 / 6 × N803 / 5 × N812** — `widgets.py` uses Qt-style CamelCase method names
  (overriding Qt API) which is intentional.
- **1 × E741** ambiguous name `l` at `report/content.py:177:55` — rename.
- **8 × RUF001** ambiguous unicode (e.g. non-ASCII chars in strings) — review for `–`/`—`
  vs `-` in user-facing text.

---

## 7. Comments & documentation

**Strong.** ~689 comment lines over 13,859 LOC (~5%), but quality is high: comments
explain rationale and security intent, not the obvious (e.g. `ui/reception.py:635-637`
on discount defence-in-depth; `app.py:309-310` on why fonts load on the main thread;
`whatsapp.py:343-347` on why an opaque 2xx is treated as UNCONFIRMED). Only **8**
TODO/FIXME-style markers and most of those are false positives (the literal `XXXXXXXXX`
phone placeholder). No stale `# TODO` debt of concern.

---

## 8. Config hygiene findings

- **M1 — Linter not configured (MEDIUM).** No `[tool.ruff]` section; only 19 default
  findings surface. Add an opinionated `select` (at minimum `E,F,W,C90,B,SIM,PLR,N,UP`)
  with `line-length` and per-file ignores for `ui/widgets.py` (Qt naming) and `_ed25519.py`.
- **M2 — `noqa` drift (LOW, 5 × RUF100).** Source carries `# noqa: F401`, `# noqa: BLE001`,
  `# noqa: N802` for rules that aren't even enabled — e.g. `db/__init__.py:19-28`,
  `ui/receipts.py:412,465`, `ui/widgets.py:43-71`. These are dead directives that mislead
  readers into thinking a rule is active.
- **3 × RUF022** unsorted `__all__` (e.g. re-export modules).

---

## 9. Maintainability summary

| Dimension | Assessment |
|-----------|------------|
| Hygiene (unused/dead code) | **A** — ruff F-rules all pass; no unused imports/vars |
| Comments | **A−** — dense, intent-revealing |
| Naming | **B** — good, minor Qt/crypto exceptions, one `l` |
| Duplication | **B** — ~3–4%, concentrated in `whatsapp.py` |
| Complexity | **C−** — CC up to 39; 11 C901, 34 funcs > 60 LOC |
| Class size / SRP | **D+** — four 500–927 LOC god-pages in `ui/` |
| Lint config / tooling | **C** — linter effectively off by default |
| **Overall** | **C+** |

The fastest high-leverage wins, in order: (1) extract `_interpret_gateway_reply` in
`whatsapp.py`; (2) decompose `app.run` and `ReceptionPage.save`; (3) introduce a typed
`User`/`Session` to kill the `dict["role"]` primitive obsession and `(con, user)` clump;
(4) enable a real ruff config and clean the stale `noqa`s.
