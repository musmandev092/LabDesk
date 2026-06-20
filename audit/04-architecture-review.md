# LabDesk — Architecture Review (Agent_Architecture)

**Scope:** Separation of concerns, layer violations, coupling, cyclic dependencies,
dependency direction, and conformance to SOLID / Clean / Hexagonal / Vertical-Slice.
**Method:** Static import-graph extraction (AST), full read of the data/service/UI
mutation paths, and grep-based leakage census. Read-only; no files changed outside
`audit/`.

**Overall architecture grade: C-**

The codebase is *organized* — packages are split by technical role (`db`, `render`,
`report`, `services`, `ui`, `licensing`) and the internal `db` package has a clean,
documented layering. But the central architectural rule for a system handling money
and medical results — *keep domain/transaction logic out of the presentation layer* —
is broken pervasively. The two most critical write paths (receipt creation, lab-result
saving) live inside Qt widgets as raw multi-table SQL transactions. A half-built
"service layer" extracted only the *cheaper* mutations, leaving the dangerous ones
inline, which is worse than no service layer because it sets a false expectation of
where the rules live.

---

## 1. Current layout vs. target architecture

Target (stated): `domain / application / infrastructure / presentation / security / audit`.

| Target layer | What exists today | Gap |
|---|---|---|
| **domain** (entities, money rules, invariants) | Mostly absent as a layer. `services/billing.py:compute_bill_totals` is the only pure-domain function. Receipt/patient/result invariants live inline in `ui/`. | **Large.** No entity model; rules scattered across views. |
| **application** (use-cases / orchestration) | `services/` (only 3 files, 137 LOC) + parts of `db/queries.py`. Covers ~4 use-cases (void, due-payment, panel edit, parameter edit). | **Large.** ~6 critical use-cases (create receipt, edit receipt, save results, save cultures) never extracted. |
| **infrastructure** (DB, crypto, backup, WhatsApp, licensing) | Strong: `db/`, `licensing/`, `whatsapp.py`. Well-layered internally. | Small — but infra is imported *directly* by presentation (`from .. import db` in 13 UI files). |
| **presentation** (Qt) | `ui/` — but it also holds application + domain logic. | **Large.** UI is the fattest layer and does everyone's job. |
| **security** (authz) | `roles.py` exists and is enforced in `db/queries.py` + `services/`. | **Partial.** `require()` is NOT called on the inline UI write paths (reception.save, worklist.save_results, microbiology save). |
| **audit** (SHA256 chain) | `db/audit.py`, called from services/queries. | **Partial.** Inline UI mutations call `log_audit` ad-hoc; not guaranteed by the write boundary. |

**Net gap:** there is no *application boundary*. The system is effectively two layers
(`infrastructure` and a presentation layer that absorbed domain+application), with a
thin, inconsistent service shim bolted on.

---

## 2. Layer-violation census (concrete)

### 2.1 Raw SQL in the presentation layer — systemic
13 of 19 `ui/*.py` files contain raw SQL; **241** direct connection-call sites in `ui/`.
Two UI files import the driver type directly: `ui/reception.py:5` and `ui/receipts.py:5`
(`from ..db import sqlite3`).

Raw-SQL statement counts per UI file:
`reception.py`(19), `worklist.py`(17), `receipts.py`(16), `microbiology.py`(12),
`catalog.py`(12), `settings.py`(9), `accounts.py`(9), `doctors.py`(6),
`dashboard.py`(4), `receipt_dialogs.py`(3), `logs.py`(2), `setup_wizard.py`(1),
`login.py`(1).

### 2.2 Critical financial transaction inside a Qt widget — **Critical**
`ui/reception.py:627-784` (`ReceptionPage.save`) performs the entire bill-creation
transaction in the view: patient upsert (`INSERT/UPDATE patients`), `INSERT INTO
receipts`, the atomic lab-number allocation loop with `UNIQUE`-collision retry
(lines 747-767), `INSERT INTO receipt_items`, and the `INSERT INTO ledger` income
credit (lines 773-778) — all wrapped in one `try/commit/rollback`. This is the
single most important money path in the product and it lives in presentation, with
**no `require()` authorization call** and only ad-hoc validation.

### 2.3 Lab-result + culture saving inside views — **Critical**
- `ui/worklist.py:425-522` (`save_results`) deletes/inserts `results`, flips
  `receipts.status='reported'`, audits inline. No service, no `require()`.
- `ui/microbiology.py:237-270` deletes/inserts `cultures` + `culture_sensitivity`,
  marks `receipt_items.reported`, flips receipt status. No service, no `require()`.
These mutate **clinical** data; releasing a wrong result is a patient-safety event.

### 2.4 Bill-edit + ledger adjustment inside a view — **High**
`ui/receipts.py:600-668` (`_save`) deletes line items, re-inserts, rewrites
`receipts`, and posts ledger `adjustment`/refund entries — money mutation inline,
duplicating the pattern `services/receipts.py` was created to own.

### 2.5 Inconsistent service extraction — **High**
`services/receipts.py` extracted `void_receipt`, `mark_receipt_delivered`;
`db/queries.py` extracted `receive_due`, panel/parameter edits — each with `require()`
+ `log_audit` enforced *at the boundary*. The far larger create/edit/result paths were
left in the UI. The result: a reader cannot trust that "mutations go through services
and are authorized+audited there." The rule holds for the easy 30% and fails for the
critical 70%. (See `services/billing.py:1-5` docstring: logic was "extracted
verbatim from the views" — the extraction simply stopped early.)

### 2.6 Infrastructure depends on domain (`whatsapp.py` → `report`) — **Medium**
`whatsapp.py:390` `from . import report` (and `:401` calls `report.build_*`). The
WhatsApp gateway (pure infrastructure) reaches up into the report/domain package to
build PDFs. Direction is inverted; a port/callback should be injected instead.

### 2.7 `report` (domain-ish) depends on `db` (infra) — **Medium**
`report/__init__.py:26`, `report/content.py:9`, `report/export.py:12`,
`report/verify.py:22` all `from .. import db`. The report/rendering domain reads
settings and receipt rows straight from the DB facade rather than receiving a data
DTO. Domain is coupled to the persistence mechanism.

---

## 3. Cyclic dependencies

### 3.1 `render` ⇄ `report` — **true module-level cross-package cycle** (High)
- `render/__init__.py:20` `from .. import report as report`
- `report/__init__.py:26` `from .. import db, render`

Both import the other at module top-level. The code acknowledges and *deliberately
preserves* this ("the package preserves the import cycle", `report/__init__.py:24-25`),
relying on import-order luck and lazy `from . import report as R` inside render
submodules (`render/report_doc.py:97,211,412,500`, `render/receipt.py:34`). A
deliberate cycle between two packages is a design smell that makes either package
un-extractable and import order fragile.

### 3.2 `db.connection` ⇄ `db.backup` — masked 2-cycle (Low)
`db/connection.py:246` and `db/backup.py:181` each do a *local* import of the other to
dodge the cycle (both carry "avoids a cycle" comments). Tolerable and contained, but it
is still a circular responsibility split (connection lifecycle vs. backup) that a
cleaner boundary would remove. The same pattern appears `db.audit`/`db.backup`.

> Positive: aside from these, the intra-`db` graph is a clean DAG
> (`_config → paths/crypto → connection → settings/audit → backup/auth → queries`),
> exactly as documented in `db/__init__.py:11-12`, and intra-`ui` is acyclic.

---

## 4. Anti-pattern instances (file:line)

| Anti-pattern | Instance | Evidence |
|---|---|---|
| **God Object / Fat Dialog** | `ui/settings.py` — one `SettingsPage(QWidget)` class, **988 LOC, 42 methods**, owning licensing, WhatsApp config + test-send, backup/restore, **DB rekey/password change**, user CRUD, and general settings. | `ui/settings.py:62` (sole class); responsibilities at `:90,95,185,221,435,446,484-495,505,634,663,742`. |
| **Fat Controller / God View** | `ui/reception.py` — **857 LOC**, ~40 methods, does patient search, cart math, discount-approval workflow, promo logic, **and** the full create-bill DB transaction. | `ui/reception.py:57` (class), `:627-784` (transaction). |
| **Fat View (clinical)** | `ui/worklist.py` (567 LOC) saves results + flips status inline; `ui/receipts.py` (736 LOC) edits bills + ledger inline. | `ui/worklist.py:425`; `ui/receipts.py:600`. |
| **Hidden Dependency (module-as-service-locator)** | Ubiquitous `from .. import db` then `db.get_setting(...)`, `db.log_audit(...)`, `db.format_patient_id(...)` called against module globals across all UI/report/service files. The `db` package re-exports a 70-symbol flat API (`db/__init__.py:119-189`) used as an ambient global. | e.g. `ui/reception.py:31`, `report/content.py:9`, `services/billing.py:12`. |
| **Deliberate import cycle** | `render`⇄`report` (§3.1). | `render/__init__.py:20`, `report/__init__.py:24-26`. |
| **Inverted dependency (infra→domain)** | `whatsapp.py:390` imports `report`. | §2.6 |
| **Leaky abstraction (driver type in UI)** | `ui/reception.py:5`, `ui/receipts.py:5` import `sqlite3` to catch `sqlite3.IntegrityError`/`Error` — the view knows the persistence engine. | `ui/reception.py:764,780`; `ui/receipts.py:651`. |

**Not found / overstated risks:** No true *Service-Locator singleton* (connections are
constructor-injected — `ui/main_window.py:141` `PageCls(con, user)` — a genuine
positive). No "Utility Hell": `constants.py` is per-package and scoped;
`ui/widgets.py` (20 fns) and `ui/tasks.py` are cohesive shared-UI helpers, not dumping
grounds.

---

## 5. Paradigm grades

| Paradigm | Grade | Justification |
|---|---|---|
| **SOLID** | **D+** | **SRP** badly violated (`SettingsPage` 42 methods; `ReceptionPage` is view+controller+repository). **DIP** violated: high-level UI/domain depend directly on the concrete `db`/`sqlite3` infrastructure (no abstractions/ports); `whatsapp`→`report` inverts direction. **OCP**: adding a payment/result rule means editing a 857-line view. **ISP/LSP** largely N/A (few interfaces). The `roles.require()` gate (`roles.py:65`) and pure `compute_bill_totals` show SOLID *is* achievable here — it just isn't applied to the hot paths. |
| **Clean Architecture** | **D** | Dependency rule inverted: the would-be domain (`report`) imports infrastructure (`db`); presentation imports infrastructure directly and contains use-cases. No entities/use-case layer. No boundary interfaces. The `db` facade is the de-facto center that everything points at — the opposite of Clean's inward-pointing dependencies. |
| **Hexagonal (Ports & Adapters)** | **D** | No ports. `db`, `whatsapp`, `licensing` are adapters with no interface separating them from the core; views call adapters concretely. WhatsApp (a driven adapter) reaching into `report` shows ports are absent. The single bright spot: connections are injected, so a test seam exists at the constructor. |
| **Vertical-Slice** | **C** | Files *are* organized by technical layer (`ui`/`db`/`render`), not by feature, so it's not a slice architecture. However, because each page co-locates its UI+logic+SQL, you accidentally get slice-like cohesion per screen (`reception`, `worklist`, `microbiology` are each self-contained). This "works" operationally but is the wrong kind of cohesion — feature logic is welded to Qt and cannot be reused/tested headless. |

---

## 6. Per-dimension grade table

| Dimension | Grade | Note |
|---|---|---|
| Separation of concerns | **D** | Views own domain + persistence (§2.2–2.4). |
| Layer integrity (UI↔DB) | **D-** | 241 DB call-sites + raw SQL in 13 UI files (§2.1). |
| Domain/infra leakage | **D+** | `report`→`db`, `whatsapp`→`report` (§2.6–2.7). |
| Coupling | **C-** | Module-global `db` facade used as ambient service (§4). |
| Cyclic dependencies | **C** | One deliberate cross-pkg cycle + masked db 2-cycles (§3). |
| Dependency direction | **D** | Inverted vs. Clean/Hexagonal (§5). |
| Composition / DI | **B-** | Constructor-injected connection; clear bootstrap in `app.py` (positive). |
| Authorization placement | **C** | Enforced at service boundary where one exists, **absent on inline UI writes** (§2.2–2.4). |
| Internal `db` package design | **A-** | Documented, acyclic layering (`db/__init__.py:11-12`). |
| Internal `render` package design | **B** | Cohesive draw layer; dragged down only by the report cycle. |
| **Overall** | **C-** | Good packaging, broken layer discipline on critical paths. |

---

## 7. Highest-leverage remediations (architectural, not line-edits)

1. **Move the create-bill transaction out of `ui/reception.py:627-784`** into
   `services/receipts.py` as `create_receipt(con, dto, *, actor_role, username)`,
   with `require("...")` + `log_audit` at the boundary — mirroring the existing
   `void_receipt`. This closes the worst layer violation and the worst authz gap at once.
2. **Extract `save_results` (`ui/worklist.py:425`) and culture-save
   (`ui/microbiology.py:237`)** into a `services/results.py` with `require()` —
   clinical writes must pass a guarded boundary.
3. **Define a `Repository`/port for receipts & settings** so `report/` and `services/`
   depend on an interface, not the concrete `db` facade — removes the `report→db`
   coupling and enables headless testing.
4. **Break the `render⇄report` cycle**: have `report` depend on `render` one-way (or
   factor shared types into a third leaf module); delete the "preserve the cycle" code.
5. **Invert `whatsapp→report`**: pass a `build_pdf` callable into the gateway instead of
   importing `report` inside it (`whatsapp.py:390`).
6. **Split `SettingsPage` (`ui/settings.py`)** into per-card widgets (WhatsApp, Backup,
   Users, Licensing, Security) so no single class exceeds ~250 LOC.
