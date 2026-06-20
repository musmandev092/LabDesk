# LabDesk — UX Review (Agent_UX)

**Scope:** Static review of `src/labdesk/ui/` (all screens + dialogs) and `render/` output, plus best-effort screenshots.
**Method:** Read every UI module; grepped for accessibility / theming / dialog patterns; generated full light+dark screenshot set.
**Screenshots:** CAPTURED. 46 PNGs (every page + dialog, light and dark) under `/tmp/qa_shots/{light,dark}/`. Required `LABDESK_ALLOW_PLAINTEXT=1` (the seed DB refuses to create unencrypted without it); the script otherwise ran clean to completion.

**Headline grade: B**

The visual design is genuinely strong: one centralised theme (`style.py`), a consistent card/header/toast system (`widgets.py`), a real dark theme that holds up across every screen, thoughtful responsive handling (FlowLayout toolbar, scroll-area shells, screen-size clamping), and a well-considered core lab flow with sensible keyboard shortcuts and non-blocking toasts. What holds it back from an A is a near-total absence of programmatic **accessibility** (no accessible names, no field buddies, no explicit tab order, emoji-only icon buttons), a few **dark-mode contrast leaks** from inline hex, and some **discoverability/keyboard** gaps in the core flow.

---

## Strengths (what's working well)

- **Single source of truth for theming.** `style.py` builds the full QSS from a palette dict per theme and applies a matching `QPalette`; `apply_theme()` even re-polishes already-realised widgets so a *live* dark↔light switch repaints correctly (`style.py:296-301`). Verified in screenshots — dark mode is clean on every page, including tables, menus, checkboxes and inputs.
- **Non-blocking feedback.** `Toast` (`widgets.py:97-178`) replaces modal info/warning popups with a self-clearing top-right pill (red lingers longer for errors). Saves feel instant; the app never blocks on an "OK" click. Modal `QMessageBox` is correctly retained only for genuine yes/no confirmations (void, delete, restore).
- **Responsive / multi-DPI care.** `FlowLayout` wraps the 12-button Receipts toolbar instead of forcing a ~1870px minimum (`receipts.py:102-105`); `fit_to_screen()` clamps dialog open-size to `availableGeometry()` for 1366×768 laptops (`widgets.py:181-197`); `max_width_center()` caps forms on ultrawide; the sidebar auto-collapses below 1180px (`main_window.py:316-322`). Screenshots confirm the toolbar wraps to two tidy rows.
- **Consistent page chrome.** Every page uses `page_header()` (title + subtitle + right-aligned actions) and `card()`, giving strong visual rhythm. Status colour-coding is centralised (`STATUS_COLORS`, `status_badge`).
- **Sensible workflow shortcuts in Reception.** Ctrl+S = Save & Print, Ctrl+Enter = Save (no print), Enter in test search adds top match, Enter in name → password on login. Alt+1..9 jumps between pages (`main_window.py:195-196`). Debounced search (`tasks.debounce`) keeps typing smooth.
- **Background work off the UI thread.** `tasks.run_in_background` / `build_pdf` keep PDF export, WhatsApp send and settings-save from freezing the GUI, with busy-text on the clicked button and liveness guards.
- **Good guard-rail UX.** Worklist locks results by status+role with an inline 🔒 reason banner (`worklist.py:301-310`); live out-of-range colouring as you type results (`worklist.py:385-394`); discount approval flow for cashiers; "report not ready" tooltips on disabled buttons (`receipts.py:333-334`).

---

## Per-screen notes

### Login (`login.py`)
- Clean, centred auth card; brand mark derived from lab name; version/credit footer wraps. Enter-key flow is correct and the double-fire guard (`setAutoDefault(False)`) is a nice touch (`login.py:66-71`).
- **Gaps:** No "show password" toggle. No Caps-Lock warning. Username/password `QLineEdit`s have placeholders but **no visible labels and no accessible names** — a screen reader announces only "edit". The forced-password-change path uses a chain of `QInputDialog` modals rather than an inline form (`login.py:127-154`), which is clunky for a first-login.

### Unlock / Set / Change DB password (`unlock.py`)
- Strong, clear data-loss warning copy (amber). Remember-on-this-computer checkbox is gated on wallet availability with a helpful tooltip.
- **Gaps:** No password-strength meter or "show password"; the only rule is length ≥ 6. The amber warning colour is **hardcoded `#b9770e`** inline (`unlock.py:107,177`) — fixed, but it does at least read on both themes.

### Activation (`activation.py`)
- Good step-by-step copy, selectable machine code, copy/save request buttons, file-load or paste. Quit/Activate are the only exits (no close bypass).
- **Gaps:** `steps.setStyleSheet("color:#555;")` (`activation.py:66`) is a **dark-mode contrast leak** — dark-grey text on a dark background. The error message uses hardcoded `#c0392b` (`:57`).

### Setup Wizard (`setup_wizard.py`)
- Scrollable single-card form, sensible defaults (currency "Rs.", prefix "LAB", username "admin"), required-field asterisks, logo/backup pickers.
- **Gaps:** It's one long scroll with ~16 fields and no step grouping/progress — a multi-step wizard or visual section dividers would reduce intimidation. Validation is **all-or-nothing toasts on Finish**; no inline per-field error state, and the toast doesn't move focus to the offending field. No confirm-password "match" live indicator.

### Main Window / navigation (`main_window.py`)
- Sidebar IA is clear and role-filtered; idle auto-lock hides content behind a re-auth modal (good privacy). Alt+1..9 navigation.
- **Gaps:** The sidebar nav buttons are plain text — **no icons**, so scanning is slower than it could be. There is **no global search / command palette** and **no breadcrumb**; a busy lab jumps between Reception ↔ Worklist ↔ Receipts constantly and must hit the sidebar or remember Alt-numbers (which aren't shown anywhere in the UI). "Sign out" has no confirmation — a misclick ends the session (it does auto-backup, so low-stakes, but still surprising).

### Dashboard (`dashboard.py`)
- Four clickable stat cards (with hover border + "Open →" hint + pointing cursor) and a "Getting started" steps card. Good.
- **Gaps:** The clickable cards are `QFrame`s with a `mousePressEvent` lambda (`widgets.py:314`) — **not keyboard-focusable and not Enter-activatable**; keyboard-only users can't trigger them.

### Reception / Billing (`reception.py`) — core flow
- The busiest screen and mostly well done: returning-patient lookup, live cart, totals, discount-approval, change-to-return row, promo auto-apply, WhatsApp consent default-on. Screenshots look balanced in both themes.
- **Gaps:**
  - The `×` remove-cart button is a **bare glyph with hardcoded inline colours** and only a tooltip (`reception.py:593-602`) — not theme-aware, small (28×26) hit target, no accessible name.
  - "Net payable", "Due", "Change" labels are **hardcoded hex** (`#0a5f67`, `#c0392b`, `#1f9d55` at `reception.py:244-253`) — these are brand colours and do read on dark, but the teal "Net payable" is the lowest-contrast of them on the dark card.
  - The **test-results list has no result if you press Enter on an empty search** but the placeholder ("type, then double-click") implies mouse; keyboard add-top-match exists but isn't signposted.
  - Tab order is left-to-right grid default; **no explicit `setTabOrder`**, so tabbing weaves between the two columns in DOM-creation order rather than a logical billing sequence.

### Worklist / Results (`worklist.py`) — core flow
- Split view (receipts | result entry), per-parameter show/hide checkboxes, per-test remarks, live high/low colouring, status+role lock banner, ESC-to-clear. Strong.
- **Gaps:**
  - **Status filter defaults to "Pending"** in code (`worklist.py:77`) which is the right default, but there's no count badge so a tech can't tell how many pending exist without scanning.
  - The result `QLineEdit`s carry **no accessible label tying them to the parameter name** — the name is a separate `QLabel` in an adjacent grid cell with no `setBuddy`/`setLabelFor`.
  - High/low colour cue is **colour-only** (red/amber text, `worklist.py:388-390`) — colour-blind users get no secondary signal (no ▲/▼ arrow or "H"/"L" tag). This is a clinical correctness concern, not just cosmetics.
  - "Save results" is the only action; the report-output hint correctly points to Receipts, but it means the core flow is a **two-screen round trip** (enter results here → switch to Receipts to print) with no "save & go to print" affordance.

### Receipts / Reports (`receipts.py`)
- Rich action bar (wraps), right-click row menu mirroring the toolbar, status filters, date range, dues-only, CSV export with formula-injection neutralisation. Well-engineered.
- **Gaps:**
  - **12 ghost buttons in one bar** is a lot to parse; even with "Receipt:" / "Report:" labels and separators, first-time users face a wall of similar buttons. Icons or a split "actions ▾" menu would lighten it.
  - Disabled-but-relevant buttons rely on a tooltip ("Report not ready yet") that only appears on hover — discoverability is poor for why an action is greyed.
  - No empty-state message in the table when zero receipts match (just a blank grid + "0 receipt(s)" subtitle).

### Microbiology (`microbiology.py`)
- Clean form + dynamic sensitivity rows. ESC clears. Consistent with Worklist.
- **Gaps:** Same accessible-label gap (form rows use string labels via `QFormLayout`, which is actually *better* here — `QFormLayout` associates labels — but the `+ Add antibiotic` rows are dynamic combos with no labels). No way to reorder/delete a single sensitivity row once added (only grows).

### Catalog / Doctors / Accounts / Logs / Settings
- Consistent dialog pattern (`QFormLayout`, Save/Cancel, ghost cancel). `QFormLayout` rows give these the **best label association in the app** (labels are programmatically tied to fields).
- **Gaps:** Settings is a 988-line single scroll; theme change is save-gated (clearly explained) which is fine. `settings.py:576` `color:#666` is another **dark-mode grey-on-dark leak** for the backup status line. Logs/colours are all hardcoded hex (acceptable — they're semantic status colours that read on both themes).

---

## Cross-cutting findings

### Accessibility (largest gap)
- **Zero** `setAccessibleName` / `setAccessibleDescription` / `setBuddy` / `setLabelFor` across the entire UI (grep: 0 hits). Screen-reader users get "edit", "button", "check box" with no context on most screens. Forms built with `QFormLayout` (dialogs) are the exception and do associate labels.
- **Zero** `setTabOrder` calls — tab order is creation-order only. On grid-based screens (Reception, Worklist entry) this weaves unpredictably across columns.
- Several actionable controls are **icon/glyph-only** (`×` remove, `🔒 Approve`, `+ Add antibiotic`, `👤` user) with at best a tooltip — no text alternative for AT.
- **Colour-only signalling** for out-of-range results and for status (mitigated for status by also using a text badge; NOT mitigated for the live high/low result cue).
- Clickable stat cards and the logout/×-buttons are not keyboard-operable.

### Dark-mode contrast leaks (inline hex)
13 inline-hex stylesheets exist. Most are intentional brand/semantic colours that read on both themes (documented in `style.py`). The genuine leaks are dark-grey-on-dark:
- `activation.py:66` — `color:#555`
- `settings.py:576` — `color:#666`

### Keyboard / efficiency
- No global search / command palette; no breadcrumb; Alt+1..9 shortcuts are undocumented in-app.
- No "show password" anywhere; no Caps-Lock indication on login/unlock.
- Core flow is a deliberate two-screen split (Worklist → Receipts) with no fast bridge.

---

## Prioritised UX issues

| # | Severity | Area | Issue | Recommendation |
|---|----------|------|-------|----------------|
| 1 | High | A11y (global) | No accessible names/descriptions and icon/glyph-only buttons → unusable with a screen reader; placeholder-only fields announce as bare "edit". | Add `setAccessibleName`/`setAccessibleDescription` to all inputs and icon buttons; give Reception/Worklist fields real labels or `setBuddy`. |
| 2 | High | A11y / clinical | Live high/low result flag (`worklist.py:385-394`) is **colour-only** (red/amber). | Add a non-colour cue (▲/▼ or H/L suffix) so colour-blind techs see out-of-range. |
| 3 | Medium | A11y | No `setTabOrder` anywhere; grid screens tab across columns illogically; clickable stat cards & ×/logout not keyboard-operable. | Set explicit tab order on Reception/Worklist; make stat cards focusable buttons; ensure all actions reachable by keyboard. |
| 4 | Medium | Dark mode | `activation.py:66` `color:#555` and `settings.py:576` `color:#666` are grey-on-dark contrast leaks. | Replace with the theme `muted` token / `QLabel#muted` object name instead of inline hex. |
| 5 | Medium | Discoverability | Receipts shows 12 similar ghost buttons; reasons for disabled actions hidden in hover tooltips; Alt+1..9 nav undocumented. | Group actions under split menus or add icons; show inline "why disabled" hints; surface shortcuts (status bar / Help). |
| 6 | Medium | Core flow | Worklist→Receipts is a two-screen round trip to print a report with no bridge. | Add a "Save & print report" (or "…go to report") action on Worklist once results save. |
| 7 | Low | Login/Unlock | No show-password toggle, no Caps-Lock warning; forced first-login change is a chain of modal `QInputDialog`s. | Add a reveal toggle + Caps-Lock hint; replace the forced-change modals with an inline form. |
| 8 | Low | Setup wizard | One long ~16-field scroll; validation is all-or-nothing toasts that don't focus the bad field. | Group into steps/sections; on validation failure, focus + highlight the offending field. |
| 9 | Low | Empty states | Receipts/Worklist tables show a blank grid when nothing matches. | Add an in-table empty-state message ("No receipts match your filters"). |
| 10 | Info | Navigation | No global search/command palette or breadcrumb; sidebar is text-only. | Consider sidebar icons and a Ctrl+K quick-jump for high-throughput labs. |
