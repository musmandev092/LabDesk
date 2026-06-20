# LabDesk — Documentation Review & Generated Documentation (Agent_Docs)

**Scope:** Audit the accuracy & coverage of existing docs (`README.md`,
`WHATSAPP_SETUP.md`, in-code docstrings/comments) and then *generate* authoritative
reference documentation: architecture, per-package module reference, database schema,
deployment/build/licensing, and developer onboarding.
**Method:** Read-only. Every claim below was checked against the actual source
(`src/labdesk/`), `schema.sql`, build/install scripts, `pyproject.toml`, and the
seeded catalog DB. Counts (706 tests / 742 parameters, 9 test modules, 20 tables)
were verified by querying `seed.sqlite` and grepping the schema directly.

**Headline documentation grade: B+**

LabDesk is *unusually well-documented for its size*. The README is a genuine
operator + vendor manual (install, security model, distro support matrix, build,
licensing, project layout), `WHATSAPP_SETUP.md` is a step-by-step runbook, and
nearly every module carries a precise, current docstring that explains *why* it
exists and how it layers. The gap is the **inverse of most codebases**: there is
strong prose for operators/vendors and excellent module-level docstrings, but **no
consolidated developer/architecture/schema reference** — that knowledge is correct
but scattered across 82 file headers, and a new engineer must reconstruct it. There
is also no `CONTRIBUTING`/onboarding doc, no API/function-level reference, and a few
stale spots (notably `src/labdesk/__init__.py` references a non-existent `APP_NAME`
constant via the module map, and the seed catalog now diverges from the legacy
"no branding" description). This report supplies the missing consolidated docs.

---

## 1. Existing documentation — accuracy & coverage audit

| Doc | Coverage | Accuracy | Notes |
|---|---|---|---|
| `README.md` (16.5 KB) | Excellent for **install / security / build / licensing / layout** | **Verified accurate** | 706-test catalog, `~/.local/share/LabDesk/`, `LABDESK_DATA_DIR`, glibc-2.34 floor, Nuitka non-bundling, Ed25519 node-lock — all match code. Project-layout tree matches the actual package split. |
| `WHATSAPP_SETUP.md` (7.4 KB) | Excellent operator runbook | **Verified accurate** | `/chat/send/document` endpoint, `token` header, `.secrets.json` 0600, plain-`http` warning, per-patient consent toggle — all confirmed in `whatsapp.py`. |
| Module docstrings | Strong | Accurate | `db/__init__.py` documents the exact layering chain; `report/__init__.py` and `render/__init__.py` document the re-export + import-cycle contract; `licensing/__init__.py` explains the gated `enforced()` design. |
| `audit/02-module-map.md` | Good | **Two stale entries** — see §6 | Labels `whatsapp.py` as "WhatsApp **Cloud-API** gateway" — it is a self-hosted **wuzapi (whatsmeow)** gateway, not Meta Cloud API. Lists `__init__` public surface as `APP_NAME`/`APP_VERSION`; the actual module only exports `__version__`. |
| **Missing** | Architecture diagram, consolidated schema doc, function-level API ref, developer onboarding / `CONTRIBUTING.md`, ADRs | — | Supplied below (§2–§5). |

---

## 2. Architecture overview (generated)

LabDesk is a **single-process, single-site desktop LIS**. There is no server, no
network service it hosts, and no multi-user concurrency beyond Qt threads in one
process. All state lives in **one SQLCipher-encrypted SQLite file**
(`~/.local/share/LabDesk/labdesk.sqlite`).

### 2.1 Layering (as built)

```
                         ┌─────────────────────────────────────────────┐
  presentation  (Qt)     │  ui/  — one module per screen + wizard,      │
                         │        unlock, login, activation, widgets    │
                         └───────────────┬─────────────────────────────┘
                                         │ direct calls (from .. import db)
        ┌────────────────────────────────┼───────────────────────────────┐
        │                                │                                │
  ┌─────▼─────┐   ┌──────────────┐  ┌────▼─────────┐  ┌───────────────┐  ┌────────────┐
  │ services/ │   │  report/     │  │   db/        │  │  render/      │  │ licensing/ │
  │ billing,  │   │ content,html │  │ connection,  │  │ QPainter →    │  │ Ed25519,   │
  │ receipts  │   │ verify,export│  │ queries,...  │  │ QPdfWriter    │  │ fingerprint│
  │ (Qt-free) │   │ (data+verify)│  │ (Qt-free)    │  │ (Qt paint)    │  │ (offline)  │
  └───────────┘   └──────┬───────┘  └──────────────┘  └───────┬───────┘  └────────────┘
                         │  ◄── lazy import cycle ──►          │
                         └────────────────────────────────────┘
                                         │
                              ┌──────────▼───────────┐
                              │ SQLCipher SQLite file │  (AES page-level + WAL encrypted)
                              └───────────────────────┘
```

**Key architectural facts (verified):**

- **`db/` internal layering is strict and documented** (`db/__init__.py`):
  `_config → paths/crypto → connection → settings/audit → backup/auth → patient_id → queries`.
  Each module only imports from those above it.
- **`report/` ↔ `render/` is a deliberate import cycle**: `report` imports `render`
  at module level; `render` lazily imports `report` back. Both packages' `__init__`
  re-export the former single-file public API so `report.X(...)` / `render.X(...)`
  keep working after the split.
- **`db`, `services`, `report`, `whatsapp`, `licensing` are Qt-free** (unit-testable
  without a display). `render/` and `ui/` require Qt.
- **The application/domain boundary is incomplete** — only billing math and 4
  mutations are extracted into `services/`; the two hottest write paths (receipt
  creation, result saving) remain inline in Qt widgets. This is correctly flagged in
  `audit/04-architecture-review.md` (grade C-) and is the single biggest structural
  debt; it is documented here so onboarding engineers know *where the rules actually
  live* (in `ui/reception.py`, `ui/worklist.py`, not in `services/`).

### 2.2 Resource / build model

`schema.sql`, `seed.sqlite`, and `assets/` are **baked into the Nuitka binary** at
build time (`scripts/gen_embedded.py` → `_embedded_data.py`, base64). At runtime
`src/labdesk/_resources.py` materialises them to a private `0700` auto-deleted temp
dir (SQLite/Qt open by path) and `package_root()` points there. In **source/dev
runs** no `_embedded_data` exists, so resources are read directly from the package —
this is what makes `uv run python -m labdesk` work with no build step.

### 2.3 Cross-cutting concerns

- **Encryption-at-rest:** SQLCipher; session passphrase held in memory only
  (`db/connection.py`), never written; optional persist to OS wallet via
  `db/keyvault.py` (jeepney/DBus Secret Service).
- **Audit:** SHA256 hash-chained `audit_log` (`db/audit.py`),
  `verify_audit_chain()`/`rechain_audit()`.
- **Authz:** `roles.py` (receptionist=2 / technician=3 / admin=5),
  `require()`/`can()`/`can_view_page()`.
- **Licensing:** offline Ed25519 node-lock (`licensing/`), enforced only when the
  installed launcher sets `LABDESK_ENFORCE_LICENSE` (never in dev/CI/self-test).

---

## 3. Module reference (generated, per package)

### `src/labdesk/` (top level)

| Module | Role | Notable public surface |
|---|---|---|
| `app.py` | Bootstrap & lifecycle: single-instance lock + window-raise, crash logging, license gate, DB unlock, auto-backup, desktop integration | `run()`, `run_cli()`, `main` |
| `__init__.py` | Single source of `__version__` (importlib.metadata with a `1.0.0` fallback for the vendored layout) | `__version__` |
| `__main__.py` | `python -m labdesk` entry | `main()` |
| `_resources.py` | Locate baked-vs-source resources | `package_root()`, `schema_file()`, `seed_db()` |
| `constants.py` | Pick-lists + phone canonicalisation | `normalize_phone(raw, cc="92")` |
| `roles.py` | RBAC | `level()`, `role_label()`, `can_view_page()`, `can()`, `require()` |
| `whatsapp.py` | **wuzapi (whatsmeow)** self-hosted gateway client, stdlib-only, with SSRF/cross-host guards | `send_report()`, `send_receipt()`, `send_text()`, `send_pdf()`, `check_status()`, `validate_url()`, `is_loopback_url()`, `is_local_url()`, `config_ready()`, `recipient_ready()`, `wa_number()` |

### `db/` — persistence (Qt-free)

| Module | Role | Public surface |
|---|---|---|
| `__init__` | Facade; re-exports ~70 symbols | `connect`, `init_db`, `unlock`, `lock`, settings/audit/backup/auth/queries/crypto/patient_id |
| `_config` | App identity, `DEFAULT_SETTINGS`, `_EXTRA_COLUMNS`, schema/seed handles | `DEFAULT_SETTINGS`, `SCHEMA_FILE`, `SEED_DB` |
| `_driver` | SQLCipher driver shim (sole sqlcipher3 import besides connection) | `sqlite3`, `ENCRYPTION_AVAILABLE` |
| `connection` | Connect/unlock/lock, key resolution, `init_db`, additive migration, rekey, plaintext→encrypted migration, encryption enforcement | `connect()`, `init_db()`, `unlock()`, `lock()`, `is_unlocked()`, `verify_passphrase()`, `db_is_plaintext()`, `rekey_database()`, `migrate_plaintext_to_encrypted()` |
| `crypto` | scrypt hashing + constant-time verify + timing dummy | `hash_password()`, `_verify_password()`, `_dummy_verify()` |
| `auth` | Login verify + exponential lockout | `verify_user()`, `lock_remaining()` |
| `keyvault` | OS Secret Service (DBus/jeepney) DB-key storage | `available()`, `store_key()`, `load_key()`, `clear_key()` |
| `audit` | SHA256 hash-chained audit log | `log_audit()`, `verify_audit_chain()`, `rechain_audit()` |
| `backup` | Encrypted backup/restore, fallback dirs, DB sniffing | `backup_db()`, `backup_to()`, `auto_backup()`, `restore_db()`, `fallback_backup_dir()` |
| `paths` | XDG dirs, perm hardening, asset import, secret-file store | `data_dir()`, `db_path()`, `import_asset()`, `get_secret()`, `set_secret()` |
| `patient_id` | Typo-checked patient-ID generation/validation | patient-id helpers |
| `queries` | Read/mutation helpers + audited write boundary | `*` (the largest read/write surface) |
| `settings` | KV settings get/set | `get_setting()`, `set_setting()` |

### `report/` — data, verification, export (Qt-free)

| Module | Role |
|---|---|
| `content.py` | Builds report/receipt data (patient card, cumulative history, ref-range resolution) |
| `formatting.py` | Date/amount/flag formatting, amount-in-words |
| `html.py` | HTML builders — **retained for content tests only, not used for rendering** |
| `verify.py` | Keyed-HMAC report verification code (per-lab key, survives backup/restore) |
| `export.py` | Print / save-as-PDF API |
| `constants.py` | Report constants |

### `render/` — native Qt PDF/preview (needs Qt)

| Module | Role |
|---|---|
| `report_doc.py` (667 LOC) | The lab-report painter (letterhead, cumulative results table, flags) |
| `receipt.py` | Cash-receipt painter |
| `primitives.py` / `_shared.py` | mm/px coordinate model, patient card, value wrapping |
| `fonts.py` / `image.py` | Inter font embedding, logo handling |
| `preview.py` | Image-page preview (no QtPdf viewer) |

### `services/` — Qt-free application logic (partial)

| Module | Role |
|---|---|
| `billing.py` | `compute_bill_totals()` — the only pure-domain money function |
| `receipts.py` | Void, due-payment receipt mutations (audited) |

### `licensing/` — offline node-lock

| Module | Role |
|---|---|
| `__init__.py` | Build activation request, verify Ed25519 license, machine-binding (1-change tolerance), expiry + clock-rollback high-water-mark, gated `enforced()` |
| `fingerprint.py` | Hashed machine signals |
| `_ed25519.py` | Pure-Python Ed25519 verify |

### `ui/` — one module per screen (needs Qt)

`accounts`, `activation`, `catalog`, `dashboard`, `doctors`, `login`, `logs`,
`main_window`, `microbiology`, `receipt_dialogs`, `receipts`, `reception`,
`settings`, `settings_dialogs`, `settings_fields`, `setup_wizard`, `style`,
`tasks`, `unlock`, `wa`, `widgets`, `worklist`.
Largest: `settings.py` (988), `reception.py` (857), `receipts.py` (736),
`catalog.py` (653), `worklist.py` (567).

---

## 4. Database schema reference (generated)

SQLCipher SQLite, `PRAGMA foreign_keys = ON`, WAL, `schema_version = 1`. Money is
`REAL` (PKR); dates are ISO-8601 `TEXT` (`datetime('now','localtime')`). **20 tables**
(verified against `schema.sql`). Post-v1 columns are added additively at startup via
`db/_config.py::_EXTRA_COLUMNS` (`patients`, `receipts`, `receipt_items`, `results`,
`users`, `audit_log`) — the shipped `schema.sql` is the v1 baseline, not the live
shape; **read `_EXTRA_COLUMNS` together with `schema.sql` to see the true columns.**

| Table | Purpose | Key columns / notes |
|---|---|---|
| `settings` | KV branding/config | `key` PK; holds `schema_version` |
| `users` | Login accounts | scrypt `pass_hash`, `role`, lockout (`failed_attempts`, `locked_until`), `must_change_password` |
| `doctors` | Referring doctors | `code` (legacy DrID) |
| `report_heads` | Report section titles | `name` UNIQUE |
| `tests` | Test catalog (706 rows) | `charges`, `category`, `report_type`/`report_head` drive the template, `is_culture` |
| `test_parameters` | Report lines (742 rows) | `part_type` (N/L/H/Y/T), `ref_male`/`ref_female`, `seq` preserves legacy order |
| `result_templates` | Reusable result pick-lists | combo name → option |
| `patients` | Patients | created on first receipt; `age_desc` Years/Months/Days |
| `receipts` | One visit/invoice | **patient snapshot columns** (`patient_name`, `age`, …) so edits never rewrite history; `status` pending→in_progress→reported→delivered; `subtotal/discount_pct/net_amount/paid/due`; `reported_at` stable across reprints |
| `receipt_items` | Line items | snapshot `test_name`/`charge`; `remarks`; `reported` |
| `results` | One row per parameter per item | **snapshots** the parameter line + resolved `ref_text` for reproducible reports; `value`, `flag` (H/L/A), `hidden`; `UNIQUE(receipt_item_id, parameter_id)` |
| `cultures` | Microbiology | specimen/growth/organism/gram_stain/zn_stain |
| `culture_sensitivity` | Antibiotic S/I/R | FK→`cultures` CASCADE |
| `micro_lists` | Micro dropdown lists | `kind` (specimen/organism/antibiotic/…) |
| `medicines` | Inventory | legacy Medicines/Stocks |
| `expenses` | Expense entries | `head`, `amount`, `created_by` |
| `ledger` | Accounting | `kind` income/expense/due_recovery; `debit`/`credit` |
| `audit_log` | Tamper-evident log | `hash` = rolling SHA256 chain |
| `wa_messages` | WhatsApp delivery log | `kind` report/receipt/text, `ok`, gateway `message` |
| `panels` / `panel_items` | Reusable test bundles ("Fever Profile") | `panel_items` FK→`panels` CASCADE |

**Schema notes carried from `audit/06`:** declarative FKs are largely **un-indexed**
(JOINs and `ON DELETE CASCADE` full-scan children); money is stored as `REAL`;
lab-number allocation is not race-safe across processes. New schema work should add
the missing FK indexes and an `ANALYZE` step.

---

## 5. Deployment, build & developer onboarding (generated)

### 5.1 Build (vendor)

```bash
uv sync                       # dev env: PySide6 + sqlcipher3-binary + nuitka + ruff + pytest
bash scripts/build_release.sh # PORTABLE: compiles inside manylinux_2_34 (Docker) → dist/labdesk-<ver>.tar.gz  ← ship this
bash scripts/build_app.sh     # FAST host build — inherits host glibc, NOT portable, dev/QA only
```

`build_release.sh` requires Docker (daemon up, user in `docker` group). Both run
`scripts/gen_embedded.py` (bake schema/seed/assets), then Nuitka in **non-bundling**
mode (Qt + Python deliberately excluded → ~2-3 MB tarball). Internal helpers:
`scripts/_build_in_container.sh`, `scripts/nuitka_entry.py`. Version sync between
`pyproject.toml` and `src/labdesk/__init__.py` is enforced by
`scripts/check_version.py`.

### 5.2 Install (per lab PC)

```bash
./install.sh      # installs uv if absent → Python 3.13 + PySide6 + SQLCipher + jeepney runtime → drops binary → menu entry
./uninstall.sh    # removes app/ + runtime/, KEEPS patient data
```

`install.sh` pins `--python 3.13` (the binary is ABI-matched to CPython 3.13).
Everything lives under `~/.local/share/LabDesk/`: program in `app/` + `runtime/`,
data (`labdesk.sqlite`, license, branding) at the top level. First launch →
activate → set DB password → setup wizard → login as `admin`.

### 5.3 Licensing (vendor, offline Ed25519)

```bash
uv run python scripts/licensing/generate_keys.py            # once: keypair → ~/Documents/LabDesk-signing-key/, embeds public key; then rebuild
uv run python scripts/licensing/issue_license.py \
    --request "<token-from-lab>" --lab "City Pathology" --out CPHC-Lab.lic --days 90
```

Tampering breaks the signature; clock-rollback is blocked by a high-water-mark.
Enforced only for the installed launcher (`LABDESK_ENFORCE_LICENSE`).

### 5.4 Developer onboarding (generated — the missing doc)

```bash
git clone … && cd LabDesk
uv sync                              # create .venv with dev deps
uv run python -m labdesk             # run from source (NO build step; licensing NOT enforced)
.venv/bin/pytest                     # 9 test modules; use temp/encrypted DBs
.venv/bin/ruff check src tests       # lint
LABDESK_DATA_DIR=/tmp/ld uv run python -m labdesk   # isolated data dir for experiments
```

**Conventions (observed in the codebase):**
- `from __future__ import annotations` at the top of every module; type hints throughout.
- **Layering discipline:** a module imports only from layers above it (see
  `db/__init__` docstring). Keep `db`/`services`/`report`/`whatsapp`/`licensing` Qt-free.
- Package `__init__` files **re-export** the former single-file API — add new public
  symbols to `__all__` so the facade stays complete.
- All mutations should go through the **audited write boundary** (`db.queries` /
  `services`) and call `roles.require(...)`; note the known gap that inline UI write
  paths (`ui/reception.py`, `ui/worklist.py`) bypass this — do not copy that pattern.
- Money math lives in `services/billing.py`; do not re-implement totals in UI.
- Env overrides for dev/test: `LABDESK_DATA_DIR`, `LABDESK_DB_KEY`, `LABDESK_SELFTEST=1`.

**Test suite (9 modules, `tests/`):** `test_auth`, `test_backup_restore`,
`test_catalog_mutations`, `test_connection_encryption`, `test_gui_e2e`,
`test_licensing`, `test_receipts_service`, `test_roles`, `test_single_instance`
(+ `conftest.py`).

---

## 6. Documentation gap analysis

| # | Gap / stale doc | Location / evidence | Severity | Recommendation |
|---|---|---|---|---|
| 1 | **No consolidated developer onboarding / `CONTRIBUTING.md`.** Setup, run-from-source, test, layering conventions exist only as scattered file headers. | repo root (no such file); knowledge spread across `db/__init__.py`, `report/__init__.py`, `pyproject.toml` | High | Adopt §5.4 above as `docs/DEVELOPING.md` or `CONTRIBUTING.md`. |
| 2 | **No consolidated architecture & schema reference.** README's "Project layout" is a one-line-per-file tree; there is no layer diagram and no schema doc — 20 tables + the `_EXTRA_COLUMNS` migration must be reconstructed from `schema.sql` + `_config.py`. | `src/labdesk/schema.sql` (v1 only) vs `db/_config.py::_EXTRA_COLUMNS` (live columns) | High | Adopt §2 and §4; **prominently note that `schema.sql` alone is incomplete** — the live shape = `schema.sql` + `_EXTRA_COLUMNS`. |
| 3 | **`audit/02-module-map.md` mislabels `whatsapp.py` as "WhatsApp Cloud-API gateway."** It is a **self-hosted wuzapi (whatsmeow) REST gateway**, not Meta's Cloud API. | `audit/02-module-map.md` whatsapp row vs `src/labdesk/whatsapp.py:1-13` docstring + `WHATSAPP_SETUP.md` | Medium | Correct the label to "self-hosted wuzapi gateway." Misleads on the trust/cost model (self-hosted vs paid Meta API). |
| 4 | **`audit/02-module-map.md` lists `__init__` public surface as `APP_NAME`/`APP_VERSION`.** The actual module exports only `__version__`. | `audit/02-module-map.md` vs `src/labdesk/__init__.py` (exports `__version__` only) | Low | Fix the module-map row to `__version__`. |
| 5 | **Stale catalog description.** README §"Licensing" says the seed is "706 tests, **no branding**", and `report.py` header still references **WeasyPrint** as the prior design — accurate as history but a new reader may search for WeasyPrint that no longer exists as a dependency. | `README.md` "seed.sqlite (catalog the app ships with, no branding)"; `report/__init__.py` docstring mentions WeasyPrint | Low | Keep the historical note but mark WeasyPrint as *removed* to avoid dependency confusion. |
| 6 | **No function/API-level reference (docstrings are good but not surfaced).** `db.queries`, `report`, `render` have rich but undocumented public surfaces; no generated API docs. | `db/queries.py` (187 LOC, large surface), `render/report_doc.py` (667) | Low | Optional: run a docstring extractor (pdoc/Sphinx) in CI to publish an HTML API reference. |
| 7 | **Architectural debt is documented as a *review finding* but not in onboarding.** New engineers won't know receipt/result rules live in UI widgets, not `services/`. | `audit/04-architecture-review.md`; `ui/reception.py`, `ui/worklist.py` | Medium | Add the "where the rules actually live" warning (in §2.1/§5.4 above) to the contributor doc until the service layer is completed. |

---

## 7. What the existing docs get *right* (keep)

- README's **security model** section is accurate, candid, and operator-appropriate
  (irrecoverable DB password warning, trust-boundary caveats, plain-`http` warning).
- README's **distro support matrix** (glibc-2.34 floor) matches the build target.
- `WHATSAPP_SETUP.md` is a complete, correct runbook including troubleshooting and the
  `.secrets.json` 0600 / cross-host-redirect-refusal details — all verified in code.
- **Module docstrings are the strongest asset**: they explain *why* (the import cycle,
  the layering chain, the gated licensing) — preserve and extend this discipline.
