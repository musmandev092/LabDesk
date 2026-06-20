# LabDesk — Performance Review

**Auditor role:** Principal Performance Engineer (Agent_Performance)
**Scope:** Static + lightweight-dynamic analysis (import-time measurement, profile-by-inspection).
**Date:** 2026-06-16
**Codebase:** ~13.9k LOC across `src/labdesk/`, Python 3.13 / PySide6 / SQLCipher.

**Headline grade: B**

LabDesk is, for a desktop single-site LIS, generally well-engineered for performance: the DB layer is correctly tuned (WAL + `synchronous=NORMAL` + `temp_store=MEMORY` + hot-path indexes), all list/search queries are `LIMIT`-bounded, search boxes are debounced, the report font is loaded once, and PDF generation runs off the UI thread. The grade is held back from an A by three concrete, fixable patterns: (1) the **report/receipt rendering hot path re-queries every lab setting on every page and re-decodes the logo image on every page**, plus a nested **N+1 over cumulative patient history**; (2) **all ~10 main-window pages are constructed eagerly at login** instead of lazily; and (3) **`whatsapp.py` drags `urllib.request`/`http.client`/`ssl` into cold-start import** (~30 ms) even though WhatsApp is rarely used at launch. None of these will be felt on a tiny demo DB, but they scale poorly as a real lab accumulates receipts, history, and multi-page reports.

---

## Measurements

### Import / cold-start cost

Measured with `python -X importtime` and a direct timed import (venv interpreter, `QT_QPA_PLATFORM=offscreen`):

| Metric | Value |
|---|---|
| `import labdesk.app` (cumulative, importtime) | ~231 ms |
| `import labdesk.app` (wall, warm FS) | ~211 ms |
| `PySide6.QtGui` (unavoidable, Qt binding) | ~70 ms |
| `labdesk.ui.main_window` subtree | ~62 ms |
| `importlib.metadata` (pulled by `labdesk/__init__`) | ~31 ms |
| `labdesk.ui.wa → labdesk.whatsapp → urllib.request` chain | ~20–30 ms |
| `urllib.request` alone (http.client ~18 ms, +ssl/email) | ~30 ms |

The dominant cost (PySide6 / shiboken6 ~48 ms, QtGui ~70 ms) is inherent to Qt and not actionable. The two actionable cold-start items are the `urllib`/`ssl` chain and `importlib.metadata`.

---

## Hotspots

| # | Area | Issue | Est. impact | Fix |
|---|---|---|---|---|
| H1 | `render/report_doc.py` `_report_letterhead` / `_report_footer` (lines 36–93, 95–110, called from `build_report` per page, line 532/546) | **16 distinct `g(...)` calls = 16 single-row `SELECT value FROM settings` queries per page.** Header+footer rerun on every page → ~16 × N_pages redundant queries for one report. `g = _g(con)` (`report/content.py:21`) is just `lambda k,d: db.get_setting(con,k,d)` with no caching. | Med–High on multi-page reports / batch printing. 5-page report ≈ 80 redundant point queries; a day's batch multiplies it. | Load all settings once per report build into a dict (`SELECT key,value FROM settings`) and pass that map down, or memoize `_g` with a per-build cache. One query replaces 16×N. |
| H2 | `render/primitives.py` `Doc.image()` (lines 204–217) called from `_report_letterhead` (lines 62, 72) | **The lab logo (and accreditation logo) is re-read from disk with `QImage(path)` and re-run through `autocrop_image()` on every page.** `image()` decodes + autocrops + smooth-scales each call; the header draws it once per page. | Med on multi-page reports (PNG decode + autocrop + smooth scale × N pages). | Decode+autocrop+scale the logo once at the start of `build_report` (keyed by path+target height) and reuse the cached `QImage`/scaled pixmap for every page. |
| H3 | `report/content.py` `_history_for_item` (lines 100–148) → called per test item from `report_doc._measure_test` (line 223) and `content._report_section` | **Nested N+1.** Per test item: 1 query for up to 8 prior visits, then **one `SELECT … FROM results` per prior visit** (line 135, loop 134–145). For a receipt with M tests this is up to M × (1 + 8) queries just to assemble the cumulative-history columns. | High for returning patients with many tests; grows with patient visit history. | Fetch all prior-visit result rows in a single query (`WHERE receipt_item_id IN (…)`) and bucket them in Python; or join results in the prior-visit query. Collapses M×9 → ~M (or fewer). |
| H4 | `render/report_doc.py` `build_report` (lines 519–524) | Per-item probe `SELECT is_culture FROM tests WHERE id=?` in the layout loop, then `_measure_test`/`_draw_culture` **re-query the same `tests` row** (`report_doc.py:220`, `:555`) for `report_head`/`method_note`. The test row is fetched 2–3× per item. | Low–Med (point queries, but redundant per item). | Select `is_culture, report_head, method_note` once per item (or join into the `receipt_items` fetch at line 504) and pass the row down. |
| H5 | `ui/main_window.py` `MainWindow.__init__` (lines 135–146) | **All visible pages are constructed eagerly at login** (`page = PageCls(con, user)` for every NAV entry), building ~10 page widget trees (Reception 857 LOC, Receipts 736, Catalog 653, Settings 988, …) before the user sees the dashboard. `go(0)` then runs only the dashboard's `on_show`. | Med on login latency, esp. on slower hardware; also retains all pages' QObjects/connections for the whole session (memory). | Lazy-construct pages on first navigation (build in `go()`/`navigate_to` and cache). Keeps login snappy and lets `on_show` already do the data load. Saves both startup time and idle memory. |
| H6 | `labdesk/whatsapp.py` (lines 23–24) imported via `ui.main_window → ui.receipts → ui.wa → whatsapp` | **`import urllib.request` at module top** pulls `http.client` (~18 ms), `ssl`, `email.*` into cold start (~30 ms cumulative) even though no network call happens at launch and WhatsApp is optional. | Med on cold-start time only. | Move `import urllib.request`/`urllib.error` inside the functions that actually send (`_cfg`/send paths). `whatsapp.py` already advertises "uses only stdlib so the AppImage stays lean" — deferring the import keeps that promise off the startup path. |
| H7 | `ui/catalog.py` `_refresh_panels` (lines 352–360) | N+1: for each panel, `db.panel_tests(con, p["id"])` is called **only to `len()` the result** (line 356) — a query per panel just to show a count. | Low (panels are few), but unbounded as panels grow. | Replace with one `SELECT panel_id, COUNT(*) … GROUP BY panel_id` and look up counts; or a `COUNT(*)` subquery in the panel list query. |
| H8 | `ui/logs.py` `refresh` (lines 142–156) | Audit-log search uses `username/action/detail LIKE '%…%'` (leading wildcard ⇒ **full table scan**, the `ix_audit_at` index can't help the filter) plus `date(at)=date('now')` (non-sargable). Bounded by `LIMIT 1000` but the scan cost grows linearly with total audit rows, which only ever grows. | Low–Med, **grows unboundedly over the product's life** (audit log never shrinks). | Acceptable short-term given LIMIT + debounce; long-term add an FTS index for detail search, or filter by `at >=` a date range (sargable, uses `ix_audit_at`) before the LIKE. |
| H9 | `ui/worklist.py` `_build_test_block` (lines 327–335) | Per test block in a loaded receipt: 1 query for `test_parameters` + 1 query for `results`. For a receipt with many tests this is 2×M queries on `load_receipt`. | Low–Med (only on opening a results screen, off the print path). | Batch: one `test_parameters … WHERE test_id IN (…)` and one `results … WHERE receipt_item_id IN (…)`, bucketed in Python. |
| H10 | `ui/tasks.py` `_Runnable.run` (line 54) | Every background task opens a **fresh `db.connect()`**, which re-runs all connection PRAGMAs (`foreign_keys`, `journal_mode=WAL`, `synchronous`, `busy_timeout`, `temp_store`, `_harden_perms` ⇒ a `chmod`). Correct (handles can't cross threads) but each WhatsApp send / PDF build pays the full open cost. | Low (per-action, off UI thread). | Acceptable as-is. If background tasks become frequent, a small per-thread connection cache would amortize the PRAGMA/chmod cost. |

---

## What is already done well (no action needed)

- **DB connection tuning** — `db/connection.py:144–152`: WAL journal, `synchronous=NORMAL`, `busy_timeout=8000`, `temp_store=MEMORY`. Exactly the right pragmas for a desktop SQLite app.
- **Hot-path indexes** — `db/connection.py:381–392`: indexes on `patients(telephone)`, `patients(mr_no)`, `receipt_items(test_id)`, `results(parameter_id)`, `expenses(date)`, `ledger(date)`, `audit_log(at)`, plus the unique `lab_no` guard.
- **All list/search queries are bounded** — `LIMIT 40` (reception test search), `LIMIT 8` (patient lookup, history), `LIMIT 500` (worklist), `LIMIT 1000` (receipts, logs). No unbounded `fetchall()` over a growing table in the UI.
- **Debounced search** — `ui/tasks.py:146` `debounce()` is wired on every search box (reception, receipts, worklist, catalog, logs, microbiology), so typing hits the DB once after a quiet period, not per keystroke.
- **Off-thread heavy work** — `ui/tasks.py` runs PDF builds and WhatsApp sends on `QThreadPool` with per-thread connections, `_alive()` (shiboken validity) guards against touching destroyed widgets, and `_active` retention prevents premature GC. This is a clean, leak-resistant pattern.
- **Font loaded once** — `render/fonts.py:24–30` caches `_FAMILY`; `app.run` calls `render.preload()` on the main thread (`app.py:313`) so `QFontDatabase` is never touched off-thread.
- **Desktop-integration cache refresh is daemon-threaded** — `app.py:170–183` runs the 1–3 s `update-desktop-database`/`kbuildsycoca` refreshers in a daemon thread so they never delay the first window.

---

## Memory / leak inspection

- **No obvious leaks.** `ui/tasks.py` correctly retains in-flight runnables (`_active`) and discards on completion; the activation `QSocketNotifier` and idle `QTimer` are parented (`win._activation_notifier`, `QTimer(self)`) so they're GC-tied to their window. `debounce()` parents its timer to the owner widget.
- **Retained page trees (H5):** because all pages are built at login and kept in the `QStackedWidget` for the whole session, every page's widgets, signals, and cached lists (`_all_tests`, `_doctors`, `_ids`) stay resident even if never viewed. Not a leak, but a steady-state memory floor that lazy construction (H5) would lower.
- **`_ids` / `self.cart` lists** are reset on each refresh (`setRowCount(0)` + `self._ids = []`), so table-backed lists don't grow unbounded.
- No module-level DB connections, no module-level pixmap/image decoding at import (path constants are cheap `Path` joins).

---

## Recommended priority order

1. **H1 + H2 (report hot path):** batch settings into one query and cache the decoded logo per build. Biggest win for the core print workflow; both are localized changes in `report_doc.py` / `primitives.py`.
2. **H3 (history N+1):** single-query the prior-visit results. Matters most for the labs that print cumulative-history reports for returning patients.
3. **H5 (lazy pages):** improves login latency and idle memory; touches only `main_window.py`.
4. **H6 (defer `urllib`):** one-line-class change in `whatsapp.py` for ~30 ms off cold start.
5. **H4, H7, H9 (smaller N+1s):** opportunistic cleanups.
6. **H8 (audit-log scan):** revisit when the audit log gets large in the field.
