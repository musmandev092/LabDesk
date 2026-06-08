# LabDesk — Architecture

A native PySide6 (Qt6) + SQLite desktop app. No web stack, no ORM, no
WeasyPrint — documents are drawn natively with `QPainter → QPdfWriter`.

## Layers

```
  ui/ (Qt views)  ──calls──▶  services/  ──calls──▶  db/ , report/ , render/
  one module per screen       business logic         data + documents
```

- **`ui/`** — one module per screen (reception, receipts, worklist, catalog,
  settings, …) plus `setup_wizard`, `style`, `widgets`. Views build layouts,
  wire signals/slots, and call down into services and the data/document layers.
  These files are the largest in the tree; that size is Qt widget/layout
  assembly, not business logic, so they are intentionally not split further.
- **`services/`** — pure / DB-only business logic pulled out of the views so it
  is unit-testable in isolation (dependency-injected `con`):
  - `billing.py` — `compute_bill_totals(items, pct, paid, *, round_to_paisa)`,
    `get_active_promo_discount(con)`.
  - `receipts.py` — `void_receipt`, `mark_receipt_delivered` (DB write + audit).
- **`db/`** — the SQLite layer, a package with strict acyclic layering:
  `_config → paths/crypto → connection → settings/audit → backup/auth →
  patient_id → queries`. `__init__.py` re-exports the full public API, so
  callers still use `from . import db; db.foo()`.
- **`report/`** — receipt/lab-report data + HTML + the print/PDF API, as a
  package: `constants → formatting → content → html, export`.
- **`render/`** — native Qt PDF/image rendering, as a package:
  `constants → fonts/image → primitives (the `Doc` QPainter wrapper) → _shared
  → receipt/report_doc → preview`. `render` and `report` reference each other's
  helpers; the cycle is broken with lazy `from . import report as R` inside the
  drawing functions.

The three logic packages (`db`, `report`, `render`) each began as a single
800–1400-line module and were decomposed without changing their public import
surface — every `from ..db import X` etc. still resolves via the package
`__init__.py`.

## Data & security (see README for detail)
- Patient data lives in a single SQLite file in the XDG data dir (`0700`), the
  DB + WAL/SHM + secrets + backups are `0600`. Passwords use scrypt + per-user
  salt with exponential lockout. The audit log is a tamper-evident SHA-256 hash
  chain. The WhatsApp token lives only in `.secrets.json`, never in the DB.
- Schema is treated as immutable in production: post-v1 columns/indexes are
  added on launch via `db.connection` migration steps, never destructive.

## Testing & the refactor safety net
- **`tests/test_all.py`** — self-contained suite (~5.6k cases); what CI runs.
- **`tests/run_gen.py`** — generator suite discovering `tests/gen/test_*.py`
  (each exposes `register(t)`); ~140k cases. Network is monkeypatched and the
  data dir is a throwaway temp dir, so no message is ever sent and the live DB
  is never touched.
- **`scripts/golden_render.py`** — a same-machine baseline of the *actual*
  rendered output: pixel hashes of the receipt/report pages, the HTML, and the
  billing totals, for a fixed date-pinned dataset. `snapshot` captures it (to
  the gitignored `build/golden_baseline.json`); `compare` asserts every signal
  is byte-identical. Used as the merge gate for behaviour-preserving refactors —
  if a refactor changes a single pixel of a printed document, it fails.

## Tooling
`ruff` (lint + format) and `mypy` are configured in `pyproject.toml`, enforced
by `.pre-commit-config.yaml` and the CI `lint`/`types` jobs. Qt is treated as
untyped for now (`ignore_missing_imports`); the UI and logic layers are typed
and checked. Rules and conventions: `CODING_STANDARDS.md`.
