# 02 — Module Map (per-module purpose & public surface)

One row per module. "Public surface" lists the key classes/functions other code consumes (private `_helpers` omitted unless load-bearing). LOC from `wc -l`.

## Top-level (`src/labdesk/`)

| Module | LOC | Purpose | Public surface |
|--------|----:|---------|----------------|
| `__init__` | — | App identity / version-of-record fallback (kept in sync with pyproject via `scripts/check_version.py`) | `APP_NAME`, `APP_VERSION` |
| `__main__` | — | `python -m labdesk` entry | `main()` → delegates to `app.main` |
| `_resources` | 63 | Locate bundled `schema.sql` / `seed.sqlite` across dev tree vs Nuitka onefile | `package_root()`, `schema_file()`, `seed_db()` |
| `app` | 492 | Application bootstrap & lifecycle: single-instance lock, instance ping, crash logging, license gate, auto-backup, AppImage integration, DB-damaged notice, QApplication run | `run()`, `run_cli()`, `main` |
| `constants` | 54 | App constants + phone canonicalization | `normalize_phone(raw, cc="92")` |
| `roles` | 77 | RBAC authorization | `level()`, `role_label()`, `can_view_page()`, `can()`, `require()` |
| `whatsapp` | 512 | WhatsApp Cloud-API gateway with SSRF guards (loopback/local-URL rejection) | `send_report()`, `send_receipt()`, `send_text()`, `send_pdf()`, `check_status()`, `validate_url()`, `is_loopback_url()`, `is_local_url()`, `config_ready()`, `recipient_ready()`, `wa_number()` |

## `db/` — data & persistence (Qt-free)

| Module | LOC | Purpose | Public surface |
|--------|----:|---------|----------------|
| `db.__init__` | 189 | **Facade**: re-exports full DB API via large `__all__` | ~70 re-exported symbols (connect, init_db, unlock, lock, backup, audit, settings, queries, crypto, patient_id…) |
| `db._config` | 146 | App identity, `DEFAULT_SETTINGS`, schema/seed handles | `DEFAULT_SETTINGS`, `SCHEMA_FILE`, `SEED_DB`, app name/version |
| `db._driver` | — | SQLCipher driver shim (sole sqlcipher3 import point besides connection) | driver `connect`/module handle |
| `db.connection` | 396 | Connect/unlock/lock, key resolution, init_db, rekey, plaintext→encrypted migration, encryption enforcement | `connect()`, `init_db()`, `unlock()`, `lock()`, `is_unlocked()`, `verify_passphrase()`, `db_is_plaintext()`, `rekey_database()`, `migrate_plaintext_to_encrypted()`, `ENCRYPTION_AVAILABLE` |
| `db.crypto` | 62 | scrypt password hashing + constant-time verify + timing-attack dummy verify | `hash_password()`, `_verify_password()`, `_dummy_verify()` |
| `db.auth` | 73 | Login verification + failed-attempt lockout | `verify_user()`, `lock_remaining()` |
| `db.keyvault` | 172 | OS Secret Service (DBus/jeepney) DB-key storage | `available()`, `store_key()`, `load_key()`, `clear_key()` |
| `db.audit` | 111 | SHA256 hash-chained audit log + verification/rechain | `log_audit()`, `verify_audit_chain()`, `rechain_audit()` |
| `db.backup` | 212 | Encrypted backup/restore, fallback dirs, DB sniffing | `backup_db()`, `backup_to()`, `auto_backup()`, `restore_db()`, `fallback_backup_dir()` |
| `db.paths` | 90 | XDG data dirs, perm hardening, asset import, secret-file storage | `data_dir()`, `db_path()`, `import_asset()`, `get_secret()`, `set_secret()` |
| `db.patient_id` | 48 | Patient-ID format/validate w/ check letter | `format_patient_id()`, `validate_patient_id()` |
| `db.queries` | 187 | Catalog & worklist queries/mutations | `list_panels()`, `panel_tests()`, `save_panel()`, `delete_panel()`, `receive_due()`, `save_test_parameters()`, `ParameterInUseError` |
| `db.settings` | 39 | Settings get/set + currency | `get_setting()`, `set_setting()`, `set_settings()`, `currency()` |

## `licensing/` — Ed25519 license enforcement (Qt-free)

| Module | LOC | Purpose | Public surface |
|--------|----:|---------|----------------|
| `licensing.__init__` | 274 | License lifecycle: build request, evaluate signature/expiry/fingerprint, install, info | `configured()`, `enforced()`, `build_request()`, `current_code()`, `evaluate()`, `check()`, `install_license()`, `license_info()`, `verify_signature()`, `parse_license_text()` |
| `licensing._ed25519` | 188 | Vendored pure-python Ed25519 (no external crypto dep) | `sign()`, `verify()`, `secret_to_public()` |
| `licensing.fingerprint` | 107 | Machine fingerprint from machine-id/MAC/disk serial | `collect_signals()`, `fingerprint_code()` |

## `render/` — vector PDF/image rendering (QPainter → QPdfWriter)

| Module | LOC | Purpose | Public surface |
|--------|----:|---------|----------------|
| `render.__init__` | 126 | **Facade**; binds sibling `report` as `render.report` (cycle contract) | `build_report`, `build_receipt`, `build_test_page`, `render_pages`, `Doc`, `autocrop_image`, `preload`, geometry/color consts |
| `render.constants` | 43 | A4 geometry, colors, DPI, mm/px helpers | `A4_W_MM`, `A4_H_MM`, `DPI`, `mm()`, `px()`, color palette |
| `render.fonts` | 47 | Qt font app bootstrap + Inter loading | `preload()`, `_ensure_app()`, `_family()` |
| `render.image` | 73 | Logo whitespace autocrop | `autocrop_image()` |
| `render.primitives` | 226 | `Doc` QPainter drawing primitive (16 methods) | `Doc` |
| `render._shared` | 147 | Shared draw helpers | `centered_logo_left()`, `fit_lab_name_font()`, `_patient_card()`, `_wrap_value()` |
| `render.receipt` | 275 | Vector cash-receipt page | `build_receipt()` |
| `render.report_doc` | 667 | Vector lab-report incl. test tables & culture | `build_report()` |
| `render.preview` | 46 | On-screen page rasterization | `build_test_page()`, `render_pages()` |

## `report/` — HTML/PDF report generation & verification

| Module | LOC | Purpose | Public surface |
|--------|----:|---------|----------------|
| `report.__init__` | 164 | **Facade**; binds `db`/`render` (cycle contract); print/export surface | `build_report_html`, `build_receipt_html`, `build_report_bytes`, `build_receipt_bytes`, `export_report_pdf`, `export_receipt_pdf`, `print_report`, `print_receipt`, `print_test_page`, `save_report_pdf`, `report_fingerprint`, `verification_code`, `verify` |
| `report.constants` | — | Report colors, arrows, asset handles | color/arrow consts |
| `report.content` | 294 | HTML data assembly (patient pairs, history, report/culture sections) | `_report_section`, `_culture_section`, `_patient_card`, `_history_for_item`, `_value_cell`, `_signatures` (consumed by html.py) |
| `report.formatting` | 202 | Escaping, ref-range resolution, flags, amount-in-words | `_esc`, `_resolve_ref`, `_flag`, `_flag_arrow`, `_fmt_date`, `_amount_in_words` |
| `report.html` | 271 | HTML document builders | `build_report_html()`, `build_receipt_html()` |
| `report.export` | 122 | PDF bytes + printing | `build_report_bytes()`, `build_receipt_bytes()`, `build_test_page_bytes()`, `export_report_pdf()`, `export_receipt_pdf()`, `print_report()`, `print_receipt()`, `save_report_pdf()` |
| `report.verify` | 90 | Report fingerprint + verification code | `report_fingerprint()`, `verification_code()`, `verify()` |

## `services/` — pure business logic (Qt-free, testable)

| Module | LOC | Purpose | Public surface |
|--------|----:|---------|----------------|
| `services.billing` | 71 | Bill total computation + promo discounts | `compute_bill_totals()`, `get_active_promo_discount()` |
| `services.receipts` | 65 | Receipt void/deliver with role checks | `void_receipt()`, `mark_receipt_delivered()` |

## `ui/` — presentation (PySide6)

| Module | LOC | Purpose | Public surface (classes / funcs) |
|--------|----:|---------|----------------------------------|
| `ui.style` | 305 | QSS theme builder | `build_qss()`, `apply_theme()` |
| `ui.widgets` | 366 | Shared widgets & helpers | `FlowLayout`, `Toast`, `toast_info()`, `toast_warn()`, `money()`, `card()`, `stat_card()`, `page_header()`, `status_badge()`, `fit_to_screen()`, `selected_id()` |
| `ui.tasks` | 158 | Threadpool runner + PDF build + debounce | `run_in_background()`, `build_pdf()`, `debounce()` |
| `ui.wa` | 68 | Async WhatsApp send wrapper for views | `send_async()` |
| `ui.main_window` | 340 | App shell: nav, page registry, role gating | `MainWindow` |
| `ui.login` | 154 | Login dialog | `LoginDialog` |
| `ui.unlock` | 199 | Encryption key entry dialogs | `UnlockDialog`, `SetPasswordDialog`, `ChangePasswordDialog` |
| `ui.activation` | 148 | License activation dialog | `ActivationDialog` |
| `ui.setup_wizard` | 222 | First-run wizard | `SetupWizard` |
| `ui.dashboard` | 81 | Dashboard stats page | `DashboardPage` |
| `ui.reception` | 857 | Patient intake & billing | `ReceptionPage` |
| `ui.worklist` | 567 | Result entry | `WorklistPage`, `resolve_ref()` |
| `ui.microbiology` | 293 | Culture/sensitivity entry | `MicrobiologyPage` |
| `ui.receipts` | 736 | Receipt list/edit/print/void | `ReceiptsPage` |
| `ui.receipt_dialogs` | 298 | Preview & edit-receipt dialogs | `_PreviewDialog`, `_EditReceiptDialog` |
| `ui.catalog` | 653 | Test catalog management | `CatalogPage`, `TestDialog`, `ParametersDialog`, `PanelsDialog` |
| `ui.doctors` | 198 | Referring-doctor management | `DoctorsPage`, `DoctorDialog` |
| `ui.accounts` | 327 | User account management | `AccountsPage` |
| `ui.logs` | 226 | Audit-log viewer | `LogsPage` |
| `ui.settings` | 988 | Settings (config/backup/license/WA/security) | `SettingsPage` |
| `ui.settings_dialogs` | 110 | Settings sub-dialogs | `UserDialog`, `TempPasswordDialog` |
| `ui.settings_fields` | 58 | Settings form field descriptors | field-descriptor data |
