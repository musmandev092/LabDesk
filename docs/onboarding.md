# Developer onboarding

## Prerequisites

- Python 3.13 (see `.python-version`)
- [`uv`](https://docs.astral.sh/uv/) for dependency + venv management
- Linux desktop libraries for Qt (the offscreen platform needs them in CI too):
  `libegl1 libgl1 libxkbcommon0 libdbus-1-3`

## Set up

```bash
uv sync --dev          # creates .venv and installs runtime + dev deps (locked)
```

## Run the app

```bash
uv run python -m labdesk           # launches the GUI
```

A first run creates an encrypted database under the app data dir. For a headless,
offscreen build-every-page self-test (what CI runs):

```bash
QT_QPA_PLATFORM=offscreen \
LABDESK_SELFTEST=1 LABDESK_DB_KEY=dev-key LABDESK_DATA_DIR=/tmp/labdesk-dev \
uv run python -m labdesk
```

## Test

```bash
QT_QPA_PLATFORM=offscreen uv run pytest          # full suite + branch coverage
uv run pytest tests/test_billing.py -q           # one file
```

Tests use a **real encrypted SQLCipher DB** in a throwaway temp dir (no DB mocking) —
see `tests/conftest.py` for the `con` fixture and `tests/factories.py` for building a
patient/receipt/result/culture graph.

## Quality gates (run what CI runs)

| Gate | Command | Must |
|------|---------|------|
| Architecture | `uv run lint-imports` | 0 broken contracts |
| Dependency CVEs | `uv run pip-audit` | 0 vulnerabilities |
| SAST (High) | `uv run bandit -r src/labdesk --severity-level high -q` | 0 high |
| Critical coverage | `uv run coverage report --include="*/db/audit.py,*/report/verify.py,*/services/billing.py,*/db/patient_id.py" --fail-under=95` | ≥95% branch |
| Lint (report) | `uv run ruff check src tests` | **do not raise** the count in `DEBT.md` |
| Types (report) | `uv run mypy` | do not raise |

`ruff` and `mypy` carry tracked baseline debt (see [`../DEBT.md`](../DEBT.md)); they run
in report mode until the Wave 8 ratchet. The rule: **a change may not increase any
tracked count.** Optional local hooks mirror CI: `uv run pre-commit install`.

## Conventions

- **No mutation SQL in `ui/`** — privileged writes go through a `services/` function
  that calls `require(...)` + `log_audit(...)` (see [architecture.md](./architecture.md)).
- Match the surrounding code's style; keep comments at the same density.
- Money is moving to integer paisa (`services/money.py`); prefer it for new math.
- Reflow long lines you touch (E501 is the largest debt category); don't bulk-autofix.
