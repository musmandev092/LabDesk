# Developer onboarding

## Setup

- Python 3.13 (`.python-version`) + [`uv`](https://docs.astral.sh/uv/).
- Qt needs these system libs (also in CI): `libegl1 libgl1 libxkbcommon0 libdbus-1-3`.

```bash
uv sync --dev                       # .venv + locked runtime/dev deps
uv run python -m labdesk            # run the GUI (dev: licensing not enforced)
```

First run creates an encrypted DB under the data dir. Headless build-every-page
self-test (what CI runs):

```bash
QT_QPA_PLATFORM=offscreen LABDESK_SELFTEST=1 LABDESK_DB_KEY=dev-key \
LABDESK_DATA_DIR=/tmp/labdesk-dev uv run python -m labdesk
```

## Test

```bash
QT_QPA_PLATFORM=offscreen uv run pytest        # full suite + branch coverage
uv run pytest tests/test_billing.py -q         # one file
```

Tests use a **real encrypted SQLCipher DB** in a temp dir (no DB mocking) — see
`tests/conftest.py` (`con` fixture) and `tests/factories.py`.

## Quality gates (what CI enforces)

Blocking: `uv run lint-imports` (architecture), `uv run pip-audit` (CVEs),
`uv run bandit -r src/labdesk --severity-level high -q`,
`uv run ruff format --check src tests`, mypy on the security-critical surface, and
≥95% / ≥90% branch coverage on the trust-core / write-service sets.

Report-only (tracked debt — **a change may not raise the count**):
`uv run ruff check src tests` and full `uv run mypy`. Baselines in
[`../DEBT.md`](../DEBT.md). Mirror CI locally with `uv run pre-commit install`.

## Conventions

- **No mutation SQL in `presentation/`** — privileged writes go through an
  `application/` service that calls `require(...)` + `log_audit(...)` in one
  transaction (see [architecture.md](./architecture.md)).
- Run `uv run ruff format` on files you touch (CI blocks on format).
- Money uses integer paisa (`application/money.py`) — prefer it for new math.
- Match the surrounding code's style and comment density.
