# LabDesk — Coding Standards

These are the governing rules for all code in this repository. They are enforced
by tooling (`ruff`, `mypy`, `pre-commit`, CI) where possible, and by review where
not. The full test suite (`python tests/test_all.py`) is the hard merge gate.

## 1. Naming & consistency (ubiquitous language)
- Use exact domain terminology in variables, classes, and schema
  (e.g. `Patient`, `Receipt`, `Test`, `Parameter`, `ReferenceRange`, `Doctor`).
- Prefix functions with strong descriptive verbs (`calculate_total`,
  `fetch_active_users`, `render_receipt`).
- No magic numbers or hardcoded strings in logic — extract to named constants
  (`constants.py` / module-level constants).

## 2. Function & class design
- **Single Responsibility.** One function/class orchestrates one behavior.
- **Short functions.** Logic should fit on one screen; split when it doesn't.
- **Guard clauses / fail fast.** Validate and return early at the top; avoid
  deeply nested `if/else` for core logic.

## 3. Architecture & decoupling
- **Separate UI from business logic.** Domain logic (`db`, `report`, `render`)
  stays agnostic of the Qt views. Pull logic *out* of the big UI files.
- **Dependency injection.** Pass DB connections, repositories, and network
  clients in, rather than instantiating them internally — for testability.

## 4. Database & state
- Treat production schema as immutable; change it only via version-controlled
  migration steps.
- Default to normalized structures for data integrity.
- Wrap multi-table updates (e.g. deduct stock + log transaction) in a single SQL
  transaction so failures roll back cleanly.

## 5. Quality assurance
- All code must pass `ruff check`, `ruff format --check`, and `mypy`.
- Catch specific exceptions — never a bare `except:`. Use logging, not `print()`.
- Design for testability: pure logic isolatable for unit tests; infrastructure
  interfaces mockable for integration tests.

## Local commands
```bash
uvx ruff format .            # auto-format
uvx ruff check . --fix       # lint + autofix
uvx mypy src/labdesk         # type check
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/test_all.py   # full suite
```
See `CLEAN_CODE_PLAN.md` for the phased rollout plan.
