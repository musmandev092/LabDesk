# 01 — System Map

**Project:** LabDesk — Linux desktop Laboratory Information System (LIS)
**Stack:** Python 3.13 · PySide6 (Qt) · SQLCipher SQLite · Nuitka build · DBus/XDG portals (jeepney) · WhatsApp gateway · Ed25519 licensing · SHA256 audit chain
**Repo root:** `/home/mosman092/Projects/LabDesk`
**Size:** 13,859 LOC of Python under `src/labdesk/` across 60 `.py` files (82 files total incl. tests/scripts).

---

## 1. Project Tree (annotated)

```
src/labdesk/
├── __init__.py              App identity: APP_NAME, APP_VERSION (version-of-record fallback)
├── __main__.py              `python -m labdesk` entry → labdesk.app.main
├── _resources.py            Locates bundled schema.sql / seed.sqlite (dev tree vs Nuitka onefile)
├── app.py            (492)  Application bootstrap: single-instance lock, crash logging, license
│                            gating, auto-backup, AppImage integration, QApplication run loop
├── constants.py      (54)   App-wide constants + normalize_phone() (E.164-ish phone canonicalizer)
├── roles.py          (77)   RBAC: role levels, can_view_page(), can(), require() authorization
├── whatsapp.py       (512)  WhatsApp Cloud-API gateway: SSRF-guarded HTTP, send report/receipt/text
├── schema.sql               DDL — canonical DB schema (data asset, not Python)
├── seed.sqlite              Seed catalog DB (binary data asset)
├── assets/                  Fonts (Inter.ttf), app icons, checkmark (binary assets)
│
├── db/                      ── DATA + PERSISTENCE LAYER (no Qt) ──
│   ├── __init__.py   (189)  Package FACADE: re-exports the whole db public API (huge __all__)
│   ├── _config.py    (146)  App identity, DEFAULT_SETTINGS, schema/seed file handles
│   ├── _driver.py    (—)    SQLCipher driver shim (the only place sqlcipher3 is imported besides connection)
│   ├── connection.py (396)  Connect/unlock/lock, key resolution, init_db, rekey, plaintext→encrypted migration
│   ├── crypto.py     (62)   scrypt password hashing + constant-time verify (+ dummy-verify timing guard)
│   ├── auth.py       (73)   User verification + login lockout (lock_remaining, verify_user)
│   ├── keyvault.py   (172)  OS Secret Service (DBus/jeepney) key storage: store/load/clear DB key
│   ├── audit.py      (111)  SHA256 hash-chained audit log: log_audit, verify_audit_chain, rechain
│   ├── backup.py     (212)  Encrypted backup/restore, fallback dirs, labdesk-DB sniffing
│   ├── paths.py      (90)   XDG data dirs, permission hardening, asset import, secret file storage
│   ├── patient_id.py (48)   Patient-ID format/validate with check-letter
│   ├── queries.py    (187)  Catalog & worklist queries/mutations (panels, tests, receive_due)
│   └── settings.py   (39)   Settings get/set + currency helper
│
├── licensing/               ── LICENSE ENFORCEMENT (no Qt) ──
│   ├── __init__.py   (274)  License lifecycle: build_request, evaluate, check, install_license, info
│   ├── _ed25519.py   (188)  Pure-python Ed25519 sign/verify (vendored, no external crypto dep)
│   └── fingerprint.py(107)  Machine fingerprint: machine-id, MAC, disk serial → signals/code
│
├── render/                  ── PDF/IMAGE RENDERING (QPainter → QPdfWriter) ──
│   ├── __init__.py   (126)  Package FACADE; binds sibling `report` as render.report (cycle contract)
│   ├── constants.py  (43)   Page geometry (A4), colors, DPI, mm/px helpers, asset paths
│   ├── fonts.py      (47)   Qt font app bootstrap + Inter font loading
│   ├── image.py      (73)   autocrop_image (logo whitespace trim)
│   ├── primitives.py (226)  Doc drawing primitive (16-method QPainter wrapper)
│   ├── _shared.py    (147)  Shared draw helpers: patient card, value wrapping, logo fit
│   ├── receipt.py    (275)  build_receipt — vector cash-receipt page
│   ├── report_doc.py (667)  build_report — vector lab-report incl. test tables & culture blocks
│   └── preview.py    (46)   On-screen page rasterization (build_test_page, render_pages)
│
├── report/                  ── HTML/PDF REPORT GENERATION + VERIFICATION ──
│   ├── __init__.py   (164)  Package FACADE; binds db & render (cycle contract); print/export surface
│   ├── constants.py  (—)    Report colors, arrows, asset handles
│   ├── content.py    (294)  Data assembly: patient pairs, history, report/culture sections (HTML)
│   ├── formatting.py (202)  Formatting: escape, ref-range resolve, flags, amount-in-words
│   ├── html.py       (271)  HTML document builders (build_report_html / build_receipt_html)
│   ├── export.py     (122)  PDF bytes/printing: build_*_bytes, print_*, save_report_pdf
│   └── verify.py     (90)   Report fingerprint + verification-code + verify()
│
├── services/                ── PURE BUSINESS LOGIC (testable, no Qt) ──
│   ├── __init__.py          Marker docstring only
│   ├── billing.py    (71)   compute_bill_totals, get_active_promo_discount
│   └── receipts.py   (65)   void_receipt, mark_receipt_delivered (with role checks)
│
└── ui/                      ── PRESENTATION LAYER (PySide6 views/dialogs) ──
    ├── __init__.py          Marker docstring only
    ├── style.py      (305)  QSS theme builder + apply_theme
    ├── widgets.py    (366)  Shared widgets/helpers: FlowLayout, Toast, toast_info/warn, money, cards
    ├── tasks.py      (158)  Threadpool runner (run_in_background), build_pdf, debounce
    ├── wa.py         (68)   send_async — async WhatsApp send wrapper for views
    ├── main_window.py(340)  MainWindow shell: nav, page registry, role gating
    ├── login.py      (154)  LoginDialog
    ├── unlock.py     (199)  Unlock/Set/Change password dialogs (encryption key entry)
    ├── activation.py (148)  License ActivationDialog
    ├── setup_wizard.py(222) First-run SetupWizard
    ├── dashboard.py  (81)   DashboardPage (stats)
    ├── reception.py  (857)  ReceptionPage — patient intake & billing (largest UI file)
    ├── worklist.py   (567)  WorklistPage — result entry
    ├── microbiology.py(293) MicrobiologyPage — culture/sensitivity entry
    ├── receipts.py   (736)  ReceiptsPage — receipt list/edit/print/void
    ├── receipt_dialogs.py(298) Preview & edit-receipt dialogs
    ├── catalog.py    (653)  CatalogPage + Test/Parameters/Panels dialogs
    ├── doctors.py    (198)  DoctorsPage + DoctorDialog
    ├── accounts.py   (327)  AccountsPage (user management)
    ├── logs.py       (226)  LogsPage (audit viewer)
    ├── settings.py   (988)  SettingsPage — largest file in repo (config, backup, license, WA, security)
    ├── settings_dialogs.py(110) UserDialog, TempPasswordDialog
    └── settings_fields.py(58) Field descriptors for settings form
```

Top-level supporting trees: `tests/` (10 test modules + conftest), `scripts/` (build, install, licensing key/issue tools, QA screenshot harnesses), `.github/workflows/ci.yml`.

---

## 2. Layered Architecture & Ownership Boundaries (layer seams)

The codebase has **clean, conventional layering** with one process boundary (WhatsApp) and one OS boundary (keyvault/portals).

```
            ┌──────────────────────────────────────────────┐
   L5  UI   │ ui/* (PySide6) — 23 modules, ~6,500 LOC       │  Qt lives ONLY here (+render/report Qt paint)
            └───────────────┬──────────────────────────────┘
                            │ depends on ↓ (never imported back)
   L4 Svc   ┌───────────────┴──────────────────────────────┐
            │ services/* (billing, receipts) — pure logic   │
            └───────────────┬──────────────────────────────┘
   L3 Doc   ┌───────────────┴──────────────────────────────┐
            │ report/* (HTML+PDF)  ⇄  render/* (QPainter)   │  ← intentional managed cycle
            └───────────────┬──────────────────────────────┘
   L2 Data  ┌───────────────┴──────────────────────────────┐
            │ db/*  ·  licensing/*  ·  whatsapp.py          │
            └───────────────┬──────────────────────────────┘
   L1 Base  ┌───────────────┴──────────────────────────────┐
            │ constants.py · roles.py · _resources.py       │
            └──────────────────────────────────────────────┘
            OS edges:  db.keyvault → DBus Secret Service (jeepney)
                       whatsapp.py → WhatsApp Cloud API (HTTP)
                       licensing.fingerprint → machine-id / MAC / disk
```

**Seam quality:**
- **Qt isolation is well respected.** PySide6 is imported in 29 files; outside `ui/`, only `render/*` and `report/export.py` touch Qt (legitimately, for QPainter/QPrinter). `db/`, `services/`, `licensing/`, `whatsapp.py`, `constants.py`, `roles.py` are Qt-free → unit-testable headless. Confirmed by `tests/` running on temp DBs.
- **`services/` is a young, half-populated seam.** Only 2 modules (`billing`, `receipts`) have been extracted as "pure/testable business-logic helpers extracted from the Qt views" (per its docstring). The vast majority of business logic still lives inside the giant UI page classes (e.g. `ReceptionPage.save` = 206 LOC, `WorklistPage.save_results` = 115 LOC). This is the most important architectural fault line — see hotspots below.
- **`db/`, `render/`, `report/` are facade packages**: their `__init__.py` re-export a flat public API (`db` has a ~70-symbol `__all__`). Consumers import `from ..db import X` rather than reaching into submodules. Good encapsulation; the cost is two intentional, documented import cycles (see report 03).

---

## 3. Size Hotspots

### 3.1 Large files (>400 LOC) — 8 files
| LOC | File | Concern |
|----:|------|---------|
| 988 | `ui/settings.py` | **God-file.** 1 class `SettingsPage` with 36 methods (927 LOC). Mixes config, backup/restore, license, WhatsApp, security, theme. Imports 14 internal modules — highest fan-out in the repo. |
| 857 | `ui/reception.py` | `ReceptionPage` 23 methods (802 LOC); `__init__`=248 LOC, `save`=206 LOC. Intake + billing + WhatsApp + report in one widget. |
| 736 | `ui/receipts.py` | `ReceiptsPage` **30 methods** (684 LOC); `__init__`=161 LOC. Most-methods class in the repo. |
| 667 | `render/report_doc.py` | `_draw_test_table`=133 LOC, `_draw_culture`=114 LOC. Dense QPainter layout code. |
| 653 | `ui/catalog.py` | 4 classes (TestDialog/ParametersDialog/PanelsDialog/CatalogPage). Reasonable split but big dialogs. |
| 567 | `ui/worklist.py` | `WorklistPage` 16 methods; `save_results`=115, `__init__`=113, `_build_test_block`=96. |
| 512 | `whatsapp.py` | Network gateway; `send_pdf`=88. Cohesive but large for a single module. |
| 492 | `app.py` | `run`=195 LOC bootstrap sequence — long but linear startup orchestration. |

### 3.2 Large classes (>150 LOC or >15 methods)
| Class | File | LOC / methods |
|-------|------|---------------|
| `SettingsPage` | ui/settings.py | 927 / 36 |
| `ReceptionPage` | ui/reception.py | 802 / 23 |
| `ReceiptsPage` | ui/receipts.py | 684 / 30 |
| `WorklistPage` | ui/worklist.py | 526 / 16 |
| `AccountsPage` | ui/accounts.py | 299 / 11 |
| `MainWindow` | ui/main_window.py | 274 / 9 |
| `MicrobiologyPage` | ui/microbiology.py | 265 / 10 |
| `_EditReceiptDialog` | ui/receipt_dialogs.py | 239 / 11 |
| `CatalogPage` | ui/catalog.py | 229 / 10 |
| `Doc` | render/primitives.py | 200 / 16 |
| `SetupWizard` | ui/setup_wizard.py | 194 / 4 |

### 3.3 Large functions (>60 LOC) — 25 found; worst offenders
| LOC | Function | File |
|----:|----------|------|
| 248 | `ReceptionPage.__init__` | ui/reception.py |
| 245 | `build_receipt` | render/receipt.py |
| 206 | `ReceptionPage.save` | ui/reception.py |
| 195 | `run` | app.py |
| 161 | `ReceiptsPage.__init__` | ui/receipts.py |
| 160 | `build_qss` | ui/style.py |
| 144 | `SetupWizard.__init__` | ui/setup_wizard.py |
| 139 | `MainWindow.__init__` | ui/main_window.py |
| 133 | `_draw_test_table` | render/report_doc.py |
| 115 | `WorklistPage.save_results` | ui/worklist.py |
| 114 | `_draw_culture` | render/report_doc.py |
| 113 | `WorklistPage.__init__` | ui/worklist.py |
| 98 | `_EditReceiptDialog.__init__` | ui/receipt_dialogs.py |
| 96 | `WorklistPage._build_test_block` | ui/worklist.py |
| 88 | `whatsapp.send_pdf` | whatsapp.py |
| 87 | `SettingsPage._restore_db`, `MicrobiologyPage.__init__` | ui/* |
| 85 | `ReceiptsPage.edit_receipt` | ui/receipts.py |

Most >60-LOC functions are either (a) Qt widget `__init__` builders (verbose-by-nature layout code) or (b) the two large `save` methods that embed business + persistence + side-effect logic that belongs in `services/`.

---

## 4. Structural Health Summary

**Strengths:** clean layered seams, strict Qt isolation enabling headless tests, facade packages that hide submodule churn, no accidental import cycles (the two cycles are deliberate and contained), all declared dependencies used, zero genuinely dead modules.

**Weaknesses:** business logic concentrated in a handful of >700-LOC UI god-classes (`SettingsPage`, `ReceptionPage`, `ReceiptsPage`), the half-built `services/` seam leaving `save`/`save_results` methods overloaded, and three parallel reference-range resolution implementations (see report 03).

**Overall structural grade: B.** Sound bones; the debt is concentrated in UI page size and incomplete logic extraction, not in module coupling or architecture.
