# LabDesk — Clean Code & Professionalization Plan

> **Status:** Report / proposal. Nothing in this document has been applied yet.
> Implementation begins only on your go-ahead.
> **Author:** automated codebase scan + 2025/2026 best-practice research.
> **Date:** 2026-06-08

---

## 1. Executive summary

LabDesk is **already a working, mature, well-documented application** — this is a
*polish-and-harden* job, not a rewrite. The code has good docstrings, a real
~2,000-case test suite, CI, and the modern `src/` + `pyproject.toml` layout that
2025 guides recommend.

The gap between "works" and "professional software-house grade" is almost
entirely **consistency, tooling enforcement, and the largest files**, not logic.
A graded snapshot:

| Area | Grade | Note |
|---|---|---|
| Architecture / layout | **A−** | clean `src/` layout, one module per screen, DB/report/render separated |
| Tests | **A−** | ~2000 cases, offline, network mocked, isolated temp DB |
| CI | **B** | runs tests, but **no lint/type gate** |
| Documentation | **B+** | strong README + docstrings; no per-module API docs |
| Type coverage | **B−** | `db`/`report` typed; **UI layer barely typed** |
| Formatting consistency | **C** | 363–508 semicolon one-liners, 412 long lines, unsorted imports |
| Error handling | **C+** | 40 broad/bare `except` |
| File size / complexity | **C+** | 5 files >700 lines, 8 functions flagged "too complex" |
| Tooling enforcement | **D** | no `ruff`/`mypy` config committed, no pre-commit, no lint in CI |

**Overall: B−.** Reachable target with this plan: **A**.

---

## 2. Scan results (measured, not estimated)

```
Source:        27 Python modules, 8,736 lines (excludes .venv/build/seed)
Largest files: render.py 986 · db.py 824 · report.py 788 · receipts.py 784 · reception.py 717

mypy (default):           2 errors / 27 files          ← excellent
ruff (default ruleset):   546 findings
ruff (E,F,W,I,UP,B,SIM,C901): 877 findings, of which:
    412  line-too-long (E501)
    363  multiple-statements-on-one-line / semicolons (E702)
     22  unsorted-imports (I001)
     21  suppressible-exception (SIM105)
     21  in-dict-keys (SIM118)
      8  complex-structure (C901)        ← the 8 functions to simplify
      5  unused-import / unused-variable

Type-hint coverage (return types):
    db.py        31/38 funcs   report.py 30/39
    render.py     7/44 funcs   receipts.py 0/44   ← UI layer is the gap

Code smells:  40 broad/bare except · 8 TODO/FIXME · 5 stray print()
Infra gaps:   no [tool.ruff] / [tool.mypy] in pyproject · no pre-commit · no CI lint gate
```

**Read this way:** the code is *correct and documented*; it is *not uniformly
formatted or mechanically enforced*. That is the cheapest, highest-leverage thing
to fix.

---

## 3. What "professional clean code" means in 2025/2026 (researched)

Synthesized from current Python and PySide6 best-practice sources (linked below):

1. **One toolchain, enforced automatically.** `uv` + **Ruff** (lint *and* format,
   replaces black/isort/flake8) + **mypy** (or pyright). Ruff is now the default
   for most teams. Config lives in `pyproject.toml`; it runs in pre-commit *and*
   CI — so style is never argued about in review again.
2. **Type hints are not optional.** Modern Python uses native generics
   (`list[str]`, `X | None`), typed function signatures everywhere, and a static
   checker in CI. UI event handlers can stay loosely typed, but data/logic must
   be fully typed.
3. **Small, single-responsibility units.** Functions short enough to read without
   scrolling; files split by responsibility, not by 800-line accretion.
4. **Explicit, narrow error handling.** Catch specific exceptions; never a bare
   `except:`; log instead of `print`.
5. **MVC / layered separation for Qt.** Views render, controllers wire
   signals/slots, models/services hold logic and stay unit-testable. LabDesk
   already half-does this (`db`/`report`/`render` are the model/service layer) —
   the win is pulling business logic *out* of the big UI files.
6. **Start tooling at inception; for existing code, fix gradually** behind `# noqa`
   where needed — never a risky big-bang reformat without tests as a guardrail.

Sources:
- [Modern Python Code Quality Setup: uv, ruff, and mypy](https://simone-carolini.medium.com/modern-python-code-quality-setup-uv-ruff-and-mypy-8038c6549dcc)
- [Python Linters: A Guide for Clean Code (2025)](https://www.glukhov.org/post/2025/11/linters-for-python/)
- [Clean Code in Python: 10 Rules to Follow in 2025](https://medium.com/the-pythonworld/clean-code-in-python-10-rules-to-follow-in-2025-a256dac3434d)
- [Python Best Practices: The 2025 Guide](https://nerdleveltech.com/python-best-practices-the-2025-guide-for-clean-fast-and-secure-code)
- [Python Typing in 2025: A Comprehensive Guide](https://khaled-jallouli.medium.com/python-typing-in-2025-a-comprehensive-guide-d61b4f562b99)
- [PySide6 ModelView / MVC architecture](https://www.pythonguis.com/tutorials/pyside6-modelview-architecture/)
- [15 Essential Ways to Write Better Python Code in 2026](https://wittycoder.in/blog/15-essential-ways-to-write-better-python-code-in-2026)

---

## 4. The plan — phased, test-guarded, reversible

**Golden rule:** the ~2,000-case suite is the safety net. *Every phase ends with
the full suite green.* No phase is "done" until `python tests/test_all.py` passes.
Each phase is a separate commit (and ideally a separate PR) so anything can be
reverted cleanly.

### Phase 0 — Tooling & guardrails (foundation, low risk)
- Add `[tool.ruff]` and `[tool.mypy]` to `pyproject.toml` (agreed rule set, line
  length, target 3.12).
- Add a `pre-commit` config (ruff lint + ruff format + mypy).
- Add a **lint+type gate** to the CI workflow alongside the existing test job.
- **No code behaviour changes.** This just makes the bar enforceable.

### Phase 1 — Mechanical safe cleanup (low risk, fully auto-verified)
- `ruff format` + `ruff check --fix`: kills the 363 semicolon one-liners, sorts
  imports, fixes 412 long lines, removes unused imports/vars.
- Replace 5 stray `print()` with proper logging.
- **Guardrail:** these are mechanical; the test suite + mypy prove behaviour is
  unchanged. This single phase erases the majority of the 877 findings.

### Phase 2 — Type coverage (medium risk)
- Add return types + parameter types across the UI layer (`receipts`, `reception`,
  `settings`, `catalog`, `worklist`, etc.) and `render.py`.
- Fix the 2 real mypy errors (`roles.py:43`, `db.py:732`).
- Goal: mypy clean on a stricter profile.

### Phase 3 — Error handling & robustness (medium risk)
- Narrow the 40 broad `except` to specific exceptions; collapse the 21
  `SIM105` suppressible blocks into `contextlib.suppress`.
- Resolve or ticket the 8 TODO/FIXME markers.

### Phase 4 — Decomposition of the 5 big files (higher risk, biggest payoff)
- Split by responsibility, keeping the public import surface stable:
  - `render.py` (986) → primitives / layout / report-render / receipt-render.
  - `db.py` (824) → connection+schema / settings / auth / domain queries.
  - `report.py` (788) → receipt model vs lab-report model vs print/PDF API.
  - `receipts.py` (784) & `reception.py` (717) → pull business logic into
    services; leave thin view classes.
- Simplify the 8 `C901` complex functions.
- **Guardrail:** behaviour-preserving refactor; tests must stay green at every step.

### Phase 5 — Docs & final polish
- Per-module docstrings, a short `ARCHITECTURE.md`, update README/CHANGELOG.
- Final full-suite + lint + mypy run; tag a clean release.

---

## 5. The "50-agent software house" execution model

This is how the implementation phase runs as an orchestrated multi-agent
**workflow** (your "50 agents like a pro software house"). Agents are organized
into squads, exactly like real teams, and **every change is verified before it is
accepted** — find → change → adversarially review → run tests.

```
                    ┌─────────────────────────┐
                    │  Orchestrator (lead)     │  decides phase order, gates merges
                    └────────────┬────────────┘
        ┌────────────────┬───────┴────────┬──────────────────┬───────────────┐
   Tooling squad    Cleanup squad    Typing squad     Refactor squad    QA / Review squad
   (Phase 0)        (Phase 1)        (Phase 2-3)      (Phase 4)         (every phase)
   1-2 agents       fan-out per      one agent per    one agent per     reviewers +
                    file             module           big file (in      test-runners,
                                                       isolated         adversarial
                                                       worktrees)       "try to break it"
```

- **Fan-out by file:** mechanical cleanup and typing parallelize cleanly — one
  agent per module, dozens at once.
- **Worktree isolation for refactors:** the big-file splits each run in their own
  git worktree so parallel agents never collide, then merge one at a time behind
  a green test run.
- **Adversarial QA gate:** each finding/change is checked by an independent
  reviewer agent whose job is to *refute* it (does it break a test? change a
  rendered PDF? alter a money calculation?). Only survivors merge.
- **Hard guardrail:** the full test suite is the merge gate for every phase.

This maps onto a `Workflow` run with `pipeline()`/`parallel()` stages and
`isolation: 'worktree'` for the refactor squad. Scale (how many agents) is set by
how wide each phase fans out — Phases 1–2 naturally use the most.

---

## 6. Risk, safety, and what will NOT change

- **Behaviour is preserved.** This is refactoring + tooling, not feature work. No
  schema changes, no UI redesign, no dependency churn beyond dev tools.
- **Patient data / money / PDF output are sacred.** Billing math, reference-range
  flagging, and rendered receipt/report output must be byte-stable. The QA squad
  specifically guards these.
- **Reversible.** One commit per phase; anything can be reverted.
- **Tests first, always.** A phase that can't keep the suite green is rolled back,
  not forced.

---

## 7. Definition of done (acceptance criteria)

- [ ] `ruff check` → **0 findings** (or every remaining one explicitly `# noqa`'d with reason)
- [ ] `ruff format --check` → clean
- [ ] `mypy` → **0 errors** on the agreed profile
- [ ] `python tests/test_all.py` → **100% pass** (unchanged count or higher)
- [ ] No file > ~500 lines without a documented reason
- [ ] No bare `except:`; no stray `print()` in `src/`
- [ ] CI enforces lint + types + tests on every push/PR
- [ ] `pre-commit` installed; README/CHANGELOG/ARCHITECTURE updated

---

## 8. Recommendation

Approve **Phases 0–1 first** (tooling + mechanical cleanup). They are low-risk,
fully test-verified, and remove ~80% of all findings in a single pass — you'll
*see* the codebase get clean immediately with near-zero chance of regression.
Then greenlight Phases 2–4 squad by squad.

**Next step:** say the word and I'll launch Phase 0–1 as the multi-agent
workflow described in §5.
```
