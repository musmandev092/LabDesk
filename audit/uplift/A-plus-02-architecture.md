# A+ Uplift Plan — ARCHITECTURE

**Dimension:** Architecture
**Current grade:** C (audit `04-architecture-review.md` overall **C-**; system-map `01` structural **B**)
**Target:** **A / A+**
**Scope:** Planning only. The only file written by this task is this report.
**Grounding:** `audit/01-system-map.md`, `audit/03-dependency-graph.md`, `audit/04-architecture-review.md`, `audit/12-refactor-roadmap.md`, plus direct reads of `src/labdesk/ui/reception.py`, `services/receipts.py`, `roles.py`, `ui/main_window.py`.

---

## 1. Why the current grade is C (the load-bearing facts)

From `04-architecture-review.md` and confirmed in source:

1. **No application boundary.** The two highest-stakes write paths run as raw multi-table SQL transactions *inside Qt widgets* with **no `require()`** and **no service**:
   - Bill creation: `ui/reception.py:627-784` (`ReceptionPage.save`) — patient upsert, `INSERT receipts`, lab-no allocation loop with `UNIQUE` retry (`:747-767`), `INSERT receipt_items`, `INSERT ledger` income credit (`:773-778`), one inline `try/commit/rollback`. Confirmed by read: the view even imports `sqlite3` (`reception.py:5`) to catch `sqlite3.IntegrityError` at `:764`/`:780`. It calls `roles.can(...)` for UX (`:639`) but never `require()`.
   - Result release: `ui/worklist.py:425-522` (`save_results`) and culture release `ui/microbiology.py:237-270`.
2. **Half-built service layer.** `services/` (137 LOC, 3 files) extracted only the *cheap* mutations (`void_receipt`, `mark_receipt_delivered` in `services/receipts.py` — both correctly gated with `require()` + `log_audit` at the boundary, confirmed at `receipts.py:27,45,57`). The critical 70% stayed inline. This is *worse* than no service layer: it implies a boundary that does not actually hold.
3. **God-objects.** `ui/settings.py` (988 LOC, 1 class, 42 methods) and `ui/reception.py` (857 LOC) are view + controller + repository in one class (`01-system-map.md §3.2`).
4. **Inverted dependencies vs Clean/Hexagonal.** Would-be domain `report/` imports infrastructure `db` (`report/__init__.py:26`, `content.py:9`, `export.py:12`, `verify.py:22`); infrastructure `whatsapp.py:390` imports domain `report`. No ports/interfaces anywhere; the `db` 70-symbol facade is used as an ambient service-locator (`from .. import db` in 13 UI files; 241 DB call-sites in `ui/`).
5. **A managed cross-package cycle** `render ⇄ report` (`render/__init__.py:20`, `report/__init__.py:24-26`), deliberately preserved.

Paradigm grades today (`04 §5`): SOLID **D+**, Clean **D**, Hexagonal **D**, Vertical-Slice **C**.

**The good bones to keep:** strict Qt isolation outside `ui/`+`render/`+`report/export` (`01 §2`), constructor-injected connection (`ui/main_window.py:141` `PageCls(con, user)` — a real test seam), clean acyclic intra-`db` DAG (`db/__init__.py:11-12`), pure `services/billing.compute_bill_totals`. These prove the target is achievable; it is simply not applied to the hot paths.

---

## 2. What "A+" means for architecture (authoritative definition)

### 2.1 The Dependency Rule (Clean Architecture)
Robert C. Martin: *"Source code dependencies can only point inwards … nothing in an inner circle can know anything at all about something in an outer circle."* Layers, innermost-out: **Entities → Use Cases → Interface Adapters → Frameworks & Drivers**, where *"the database is a detail"* and *"the web [UI] is a detail"* in the outermost ring. Crossing a boundary outward (a use case needing a presenter/DB) is done via the **Dependency Inversion Principle**: the inner layer defines an interface, the outer layer implements it — control flows out, code dependencies still point in. ([Uncle Bob — The Clean Architecture](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html); [InformIT — The Clean Architecture Dependency Rule](https://www.informit.com/articles/article.aspx?p=2832399))

### 2.2 Ports & Adapters (Hexagonal)
Alistair Cockburn's intent: *"allow an application to equally be driven by users, programs, automated tests or batch scripts, and to be developed and tested in isolation from its eventual run-time devices and databases."* **Driving (primary) adapters** call inbound ports to initiate use cases (here: Qt views, tests, scripts). **Driven (secondary) adapters** implement outbound ports the core defines (here: SQLCipher repository, WhatsApp gateway, PDF builder, keyvault). The core defines the port interfaces; adapters live outside it. ([Hexagonal architecture — Wikipedia](https://en.wikipedia.org/wiki/Hexagonal_architecture_(software)); [AWS Prescriptive Guidance — Hexagonal architecture](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/hexagonal-architecture.html))

### 2.3 Service layer + Repository in Python
The service layer holds **use-case functions** that orchestrate domain objects and depend on **repository abstractions / a unit of work**, taking primitives/DTOs and returning primitives — keeping web/UI entrypoints thin and the core headless-testable. The repository *"separates data-access logic from business logic"* so the service depends on the abstract interface, not a concrete engine; ports/abstractions are expressed in Python as **`typing.Protocol`** or **ABC**. ([Architecture Patterns with Python — Repository Pattern (O'Reilly)](https://www.oreilly.com/library/view/architecture-patterns-with/9781492052197/ch02.html); [cosmicpython — Repository Pattern](https://www.cosmicpython.com/book/chapter_02_repository); [Dependency inversion principle — Wikipedia](https://en.wikipedia.org/wiki/Dependency_inversion_principle))

### 2.4 Qt presentation must be a thin view (MVVM/MVP for PySide6)
The recognized pattern for a maintainable, testable Qt desktop app puts a **ViewModel/Presenter** between the Qt widgets and the application core: *"the ViewModel acts as an intermediary … providing an abstraction of the View that reduces the complexity of the UI logic,"* enabling a *"clean separation between the GUI and the underlying business logic"* that is unit-testable without Qt. ([A Clean Architecture for a PyQt GUI Using the MVVM Pattern — M. Huber](https://medium.com/@mark_huber/a-clean-architecture-for-a-pyqt-gui-using-the-mvvm-pattern-b8e5d9ae833d); [pyside6-mvvm-example](https://github.com/ericjameszimmerman/pyside6-mvvm-example))

### 2.5 The rule must be *machine-enforced* (this is the A+ gate)
A claimed architecture that nothing verifies decays. **Import Linter** lets you declare the layered architecture as **`layers`** contracts (higher may import lower, never the reverse), **`forbidden`** contracts (set A may not import set B, descendants included), and **`independence`** contracts, optionally **`exhaustive`** so a newly added module that fits no layer fails the build. It runs as `lint-imports`, returning a non-zero exit code on any violation — suitable as a CI gate that blocks merges. ([Import Linter — Layers contract](https://import-linter.readthedocs.io/en/v2.9/contract_types/layers/); [Import Linter — Contract types](https://import-linter.readthedocs.io/en/latest/contract_types.html); [Roman Imankulov — Linter for Python Architecture](https://roman.pt/posts/python-architecture-linter/))

### 2.6 The A+ bar, made concrete for LabDesk

| # | A+ acceptance criterion | Measurable test |
|---|---|---|
| A1 | Target layer tree exists: `domain / application / infrastructure / presentation / security / audit` (or equivalent named packages) with the dependency rule pointing inward. | Directory layout present; imports conform. |
| A2 | **Zero layer violations**, enforced in CI. | An Import-Linter config with `layers` + `forbidden` contracts; `lint-imports` exits 0; CI job fails the build on any violation. |
| A3 | **Every mutation** (bill create/edit, result/culture release, user mgmt, void, deliver, due-payment, catalog edit) goes through an **application service** that calls `require()` + `log_audit` **at the boundary**. | No `INSERT/UPDATE/DELETE` SQL literal in any `ui/*.py`; grep returns 0. Each mutation use-case has a test asserting `PermissionError` for an unprivileged role. |
| A4 | **Presentation is thin**: no `ui/*.py` imports the `sqlite3` driver type; no money math, no multi-table transaction, no `require()` decision logic in a widget. Views call a ViewModel/service and render the result. | grep: `from ..db import sqlite3` → 0 hits; per-file raw-SQL count → 0. |
| A5 | Infrastructure is reached only through **ports** (Protocols/ABCs) owned by the core. `report/` no longer imports `db`; `whatsapp` no longer imports `report` (callable injected). | Import-Linter `forbidden`: `report` ⇏ `db`, `whatsapp` ⇏ `report`. |
| A6 | **No God-object**: no class > ~250 LOC, no module > ~400 LOC in `ui/`; `SettingsPage`/`ReceptionPage` decomposed. | LOC/method count per class; lint check. |
| A7 | **No deliberate cross-package cycle**: `render ⇄ report` broken to one-way (or shared leaf). | Import-Linter `independence`/`layers` on `render`,`report`; `import_cycles` clean. |
| A8 | A **composition root** wires concrete adapters to ports once at startup; the core never names a concrete adapter. | `app.py` / a `bootstrap` module constructs adapters; services receive ports via constructor/params. |
| A9 | SOLID/Clean/Hexagonal re-graded **A-/A** by re-running report 04's method. | Re-audit. |

A1–A5 + A8 are **table-stakes for A**. A6 (god-class split), A7 (cycle), and the full ViewModel layer are **A→A+ stretch**.

---

## 3. Target architecture for LabDesk

Keep the codebase a single installable package but reorganize by **dependency role**, with import-linter enforcing the inward rule. Innermost → outermost:

```
labdesk/
  domain/          # Entities + pure rules. NO Qt, NO db, NO I/O.
    money.py            # Money value-object (minor-units) + rounding (absorbs services/billing math)
    patient.py          # patient-id format/validate/check-letter (from db/patient_id.py)
    refrange.py         # the ONE reference-range resolver (kills the triple-impl, audit 03 §6.1)
    billing.py          # compute_bill_totals, promo clamp (from services/billing.py)
    entities.py         # Receipt, ReceiptItem, Result, Culture, User dataclasses (frozen)
    ports.py            # Protocols: ReceiptRepo, ResultRepo, SettingsRepo, AuditSink,
                        #            Clock, PdfBuilder, MessageGateway, Authorizer
  application/     # Use-case services. Depend ONLY on domain (incl. ports). NO Qt, NO sqlite3.
    receipts.py         # create_receipt, edit_receipt, void_receipt(moved), deliver
    results.py          # save_results, save_cultures, finalize
    users.py            # create_user, set_role, reset_password, enable/disable
    catalog.py          # panel/test/parameter edits (from db/queries.py mutators)
  security/        # roles.require()/can() — imported by application as the Authorizer port impl
    roles.py            # (moved from top-level; pure, no deps)
  audit/           # SHA-256 chain — exposes an AuditSink adapter implementing the port
    chain.py            # (from db/audit.py)
  infrastructure/  # Driven adapters. Implement domain ports. May import domain, never application.
    db/                 # SQLCipher repos implementing *Repo ports (from today's db/)
    whatsapp.py         # MessageGateway adapter (build_pdf injected, no report import)
    licensing/          # (unchanged; already leaf-clean)
    render/, report/    # PdfBuilder adapter; render→report made one-way
  presentation/    # Driving adapter. Qt only. Imports application + a ViewModel; NO db, NO sqlite3.
    ui/                 # thin views + per-page ViewModel
  app.py / bootstrap.py # Composition root: build concrete adapters, inject into services, hand to UI
```

**Dependency rule (Import-Linter `layers`, top=outer):**
`presentation → application → domain`, with `security`, `audit` as inner siblings depended on by `application`, and `infrastructure` allowed to import `domain` only. The composition root (`app.py`) is the one place permitted to import everything.

This satisfies §2.1–2.4: `db` and Qt become *details* in outer rings; services are the use-case layer; ports invert the `report→db` and `whatsapp→report` arrows.

---

## 4. Gap-closing plan (ordered, incremental, behavior-preserving except where a fix is explicit)

Sequencing mirrors `12-refactor-roadmap.md` Waves 0/3/4 but is framed around the **architecture** deliverable. Each step ships green tests (`pytest -q`). Effort: S ≤0.5d, M 1–3d, L ≥1wk.

> **Pre-req (from roadmap, not re-listed as architecture steps):** characterization tests P3.3 (billing math) and P3.1 (audit verifier) must exist before the extractions touch money/audit. Cited where relevant.

### Phase 0 — Make the rule enforceable & stop the bleeding (do first; cheap)

**A0.1 — Add Import-Linter config + CI gate against the *current* tree.** *(satisfies A2)*
Add an `[tool.importlinter]` block to `pyproject.toml` (or `.importlinter`) encoding *today's* known-good layering (`presentation=ui → services → report/render → db → roles/constants`) plus two `forbidden` contracts that are already (mostly) true and a few `allow`/ignore entries for the known violations, so the baseline is green and **new** violations fail CI. Add a `lint-imports` step to `.github/workflows/ci.yml`.
- Files: `pyproject.toml`, `.github/workflows/ci.yml`.
- Effort S · Risk Low · Impact High. Satisfies: A2 (CI enforcement of the dependency rule).
- *Recommended tool:* **import-linter** (`lint-imports`). Rationale + source §2.5. Requires install permission — flag to owner.

**A0.2 — Document the trust/architecture boundary** (= roadmap P2.5). *(satisfies A3 culturally)*
Add `docs/ARCHITECTURE.md` stating "all mutations go through `application/` services with `require()`+audit; views never write SQL," and a header note in `roles.py`. Stops new code copying the inline pattern while the migration lands.
- Files: `docs/ARCHITECTURE.md` (new), `roles.py` header.
- Effort S · Risk Low · Impact Med. Satisfies: A3, A9 (governance).

### Phase 1 — Create the application boundary for the critical writes (the core of the uplift)

**A1.1 — Extract `create_receipt` into the service layer** (= roadmap P2.1, absorbs P1.4). *(satisfies A3, A4)*
Move the entire transaction from `ui/reception.py:627-784` into `application/receipts.py: create_receipt(repo, dto, *, actor)` mirroring the existing `void_receipt` shape (`services/receipts.py:16-50`): `require(actor.role, "create_receipt")` at the top, patient upsert + receipt insert + lab-no allocation + items + ledger credit, `log_audit` at the boundary. Add cap `create_receipt` to `roles.CAP_MIN_LEVEL`. Wrap the lab-no allocation in `BEGIN IMMEDIATE` (absorbs P1.4) so the transaction owns the write lock. The view shrinks to: validate inputs → build a `ReceiptDTO` → call service → toast/print.
- Files: `ui/reception.py:627-784` → `application/receipts.py` (new), `roles.py:33-44`.
- Effort L · Risk **High** (the money path) · Impact High. Satisfies: A3 (authz+audit at boundary), A4 (thin view). **Pre-req: P3.3 billing-math + characterization test of current bill output.**

**A1.2 — Extract result + culture release into `application/results.py`** (= roadmap P2.2). *(satisfies A3, A4)*
Move `ui/worklist.py:425-522` (`save_results`) and `ui/microbiology.py:237-270` into `save_results(...)` / `save_cultures(...)` use-cases, each `require("enter_results"/"finalize_results")` + `log_audit`, including the `receipts.status='reported'` transition. New caps in `roles.py`. Clinical write-safety: releasing a wrong result is a patient-safety event and must cross a guarded boundary.
- Files: `ui/worklist.py:425-522`, `ui/microbiology.py:237-270` → `application/results.py` (new), `roles.py`.
- Effort L · Risk High · Impact High. Satisfies: A3, A4. Pre-req: A1.1 (reuse the pattern) + P1.1 ref-range consolidation.

**A1.3 — Extract bill-edit + ledger adjustment into `edit_receipt`** (closes `receipts.py:600-668`). *(satisfies A3, A4)*
Move `ui/receipts.py:_save` (delete/re-insert line items, rewrite `receipts`, post ledger `adjustment`/refund) into `application/receipts.py: edit_receipt(...)` with `require()`+audit. This path currently duplicates exactly what `services/receipts.py` was created to own.
- Files: `ui/receipts.py:600-668` → `application/receipts.py`.
- Effort M · Risk High · Impact High. Satisfies: A3, A4. After A1.1.

**A1.4 — Move user-management mutations behind `require("manage_users")`** (= roadmap P2.3). *(satisfies A3)*
Extract create-user / role-assign / password-reset / enable-disable from `ui/settings.py:448,473,777` and `ui/worklist.py:308` into `application/users.py`. Currently gated only by Qt `can()` — any holder of the shared DB key path can self-promote.
- Files: `ui/settings.py`, `ui/worklist.py:308` → `application/users.py` (new), `roles.py`.
- Effort M · Risk Med · Impact High. Satisfies: A3. After A1.1/A1.2 establish the idiom.

### Phase 2 — Invert the dependencies (ports & adapters)

**A2.1 — Define `domain/ports.py` Protocols and a Repository for receipts/results/settings.** *(satisfies A5, A8)*
Introduce `typing.Protocol` interfaces — `ReceiptRepo`, `ResultRepo`, `SettingsRepo`, `AuditSink`, `Authorizer`, `Clock` — and concrete adapters in `infrastructure/db/` implementing them (thin wrappers over today's `db/queries.py`). Application services accept a port, not `from .. import db`. This removes the ambient `db`-as-service-locator usage in services and is the seam that makes them headless-testable with fakes.
- Files: `domain/ports.py` (new), `infrastructure/db/repos.py` (new, wraps `db/queries.py`), `application/*` constructors.
- Effort L · Risk Med · Impact High. Satisfies: A5 (DIP), A8 (composition). Source: §2.3.

**A2.2 — Break `report → db`: feed report a DTO instead of letting it read the DB.** *(satisfies A5)*
`report/content.py:9`, `export.py:12`, `verify.py:22`, `__init__.py:26` import `db`. Introduce a `ReportData`/`SettingsView` DTO assembled by the application layer (or a `SettingsRepo` port) and passed into `report.build_*`. `report/` becomes a pure domain-ish renderer.
- Files: `report/content.py`, `report/export.py`, `report/verify.py`, `report/__init__.py`; caller in `application/`.
- Effort M · Risk Med · Impact Med. Satisfies: A5. Import-Linter `forbidden: report ⇏ db`.

**A2.3 — Invert `whatsapp → report`: inject a `build_pdf` callable** (= roadmap P4.7 part). *(satisfies A5)*
`whatsapp.py:390` `from . import report` (calls `report.build_*` at `:401`). Pass a `PdfBuilder` callable/port into the gateway from the composition root instead. WhatsApp becomes a pure driven adapter.
- Files: `whatsapp.py:390,401`, composition root `app.py`.
- Effort S · Risk Low · Impact Med. Satisfies: A5. Import-Linter `forbidden: whatsapp ⇏ report`.

**A2.4 — Build the composition root.** *(satisfies A8)*
Make `app.py` (or new `bootstrap.py`) the single place that constructs `db`-backed repos, the WhatsApp gateway with `build_pdf` injected, the `Authorizer`, and hands them to `MainWindow`/pages. Pages stop importing `db`; they receive services. Leverages the existing `PageCls(con, user)` seam (`main_window.py:141`) — replace `con` with a `Services`/`AppContext` bundle (pairs with roadmap P4.5).
- Files: `app.py`, `ui/main_window.py:135-146`, every `ui/*` page constructor.
- Effort L · Risk Med · Impact High. Satisfies: A8. Source §2.2.

### Phase 3 — Drain remaining SQL out of presentation, re-fold the package tree

**A3.1 — Route all UI *reads* through repository/query functions** (= roadmap P2.4). *(satisfies A4)*
Remove the remaining raw SQL strings and the `sqlite3` driver import from the 13 UI files (241 call-sites), one file at a time, behind the repos from A2.1. Behavior-preserving; lowest-risk slice.
- Files: `ui/reception.py:5`, `ui/receipts.py:5`, `ui/doctors.py`, `ui/dashboard.py`, `ui/logs.py`, `ui/catalog.py`, `ui/accounts.py`, … (per `04 §2.1`).
- Effort L · Risk Med · Impact Med. Satisfies: A4. One file per PR.

**A3.2 — Physically move modules into the target tree and flip Import-Linter to strict.** *(satisfies A1, A2)*
Relocate files into `domain/ application/ infrastructure/ presentation/ security/ audit/`, update the Import-Linter contracts from "baseline with allowances" to **exhaustive `layers`** (every module must fit a layer; `exhaustive = true`). At this point A2 is fully met: zero violations, build-enforced.
- Files: package-wide moves (mechanical, import paths only), `pyproject.toml` import-linter block.
- Effort M · Risk Med · Impact High. Satisfies: A1, A2. After A1.*/A2.* so the moves don't re-introduce violations.

### Phase 4 — Kill the God-objects and the cycle (A→A+ stretch)

**A4.1 — Split `SettingsPage` (988 LOC/42m) into per-card widgets.** (= roadmap P4.2) *(satisfies A6)*
General / WhatsApp / Backup / Theme / Users / Licensing / Security tabs, none > ~250 LOC. Safe *after* A1.4 moved the user-mutation logic into `application/users.py`, so this is pure view decomposition.
- Files: `ui/settings.py:62` → `ui/settings/*` widgets.
- Effort L · Risk Med · Impact High. Satisfies: A6. Needs GUI regression net (P3.8).

**A4.2 — Decompose `ReceptionPage`/`ReceiptsPage`/`WorklistPage`.** *(satisfies A6)*
After A1.1–A1.3 emptied their `save` methods into services, split the remaining view into `_build_<section>` + a per-page ViewModel that holds cart/discount state and calls the service. Realizes the §2.4 MVVM seam.
- Files: `ui/reception.py:57`, `ui/receipts.py:53`, `ui/worklist.py:42`.
- Effort L · Risk Med · Impact High. Satisfies: A6, A4 (MVVM). After Phase 1.

**A4.3 — Break the `render ⇄ report` cycle** (= roadmap P4.7). *(satisfies A7)*
Make `report → render` one-way (or factor the shared draw helpers into a leaf `render/_shared` consumed by both), delete the "preserve the cycle" contract in `render/__init__.py:20` and `report/__init__.py:24-26`. Add an Import-Linter `independence` check so it can't recur.
- Files: `render/__init__.py:20`, `report/__init__.py:24-26`, lazy imports at `render/report_doc.py:97,211,412,500`, `render/receipt.py:34`.
- Effort M · Risk Med · Impact Med. Satisfies: A7. Late; pairs with the P1.1 ref-range merge that already touches both.

**A4.4 — Resolve the `db.connection ⇄ db.backup` local-import dodge.** *(satisfies A7 internal)*
Factor `_resolve_key`/`_apply_key` into a leaf so neither does an in-function import (`connection.py:246`, `backup.py:181`).
- Files: `db/connection.py:246`, `db/backup.py:181`.
- Effort S · Risk Low · Impact Low. Satisfies: A7.

---

## 5. Recommended tooling (with rationale; install requires owner OK)

| Tool | Purpose | Rationale / Source |
|---|---|---|
| **import-linter** (`lint-imports`) | Declare & CI-enforce the layered dependency rule (`layers`, `forbidden`, `independence`, `exhaustive`). **The single most important A+ gate** — turns "we have an architecture" into a build failure on violation. | §2.5 — [Import Linter docs](https://import-linter.readthedocs.io/en/latest/contract_types.html) |
| **pydeps** / **grimp** | Visualize the import graph before/after each phase to confirm arrows point inward; grimp is import-linter's own graph engine. | [Import Linter — Layers](https://import-linter.readthedocs.io/en/v2.9/contract_types/layers/) |
| **ruff** (already a dev dep) | Add a real config (`C90` complexity, `PLR` size limits, `N`, `B`, `SIM`) to mechanically catch God-method/God-class regressions (A6). | roadmap P4.6; `pyproject.toml` |
| **typing.Protocol** (stdlib) | Define ports without a runtime DI framework — keeps dependency-minimization (the project already vendors Ed25519 to avoid deps). | §2.3 — [DIP / repository pattern](https://www.cosmicpython.com/book/chapter_02_repository) |

No third-party DI container is recommended: a hand-wired composition root in `app.py` is sufficient and keeps the dependency surface minimal (consistent with the project's existing vendoring philosophy, `03 §5`).

---

## 6. Table-stakes-for-A vs stretch-for-A+

- **Table-stakes for A:** A0.1 (import-linter CI), A1.1–A1.4 (every mutation behind an audited service boundary), A2.1–A2.4 (ports + composition root), A3.1 (no SQL in views). This alone moves SOLID/Clean/Hexagonal from D/D+ to roughly **B+/A-** and earns A2/A3/A4/A5/A8.
- **Stretch for A+:** A3.2 (exhaustive layer tree, zero-tolerance gate), A4.1–A4.2 (God-class split + per-page ViewModel = true MVVM), A4.3–A4.4 (cycle elimination). These earn A1/A6/A7 and the headless-testable presentation that distinguishes A+ from A.

---

## 7. Risk notes specific to LabDesk

- The money path (A1.1/A1.3) is the **highest-risk** change in the program. It must be preceded by characterization tests (roadmap P3.3) and pair with the integer-money migration sequencing (P1.2) so the extraction and the type change are not entangled in one PR.
- DB/license/**audit compatibility** must hold: `log_audit` calls move *location* (into services) but the SHA-256 chain semantics must not change; verify with the P3.1 verifier tests after each extraction.
- The package re-fold (A3.2) is mechanical but touches import paths repo-wide; gate it behind a green `lint-imports` + full `pytest -q`, and do it as one atomic PR after Phases 1–2 so reviewers see only path changes.

---

## 8. Key sources

- [Uncle Bob — The Clean Architecture (Dependency Rule, layers, "database/web are details")](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [InformIT — The Clean Architecture Dependency Rule](https://www.informit.com/articles/article.aspx?p=2832399)
- [Hexagonal architecture — Wikipedia (ports, driving/driven adapters)](https://en.wikipedia.org/wiki/Hexagonal_architecture_(software))
- [AWS Prescriptive Guidance — Hexagonal architecture pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/hexagonal-architecture.html)
- [Architecture Patterns with Python — Repository Pattern (O'Reilly)](https://www.oreilly.com/library/view/architecture-patterns-with/9781492052197/ch02.html)
- [cosmicpython — Repository Pattern (service depends on abstraction)](https://www.cosmicpython.com/book/chapter_02_repository)
- [Dependency inversion principle — Wikipedia](https://en.wikipedia.org/wiki/Dependency_inversion_principle)
- [Import Linter — Layers contract (ordered layers, containers, exhaustive, CI exit code)](https://import-linter.readthedocs.io/en/v2.9/contract_types/layers/)
- [Import Linter — Contract types (layers / forbidden / independence)](https://import-linter.readthedocs.io/en/latest/contract_types.html)
- [Roman Imankulov — A Linter for Python Architecture](https://roman.pt/posts/python-architecture-linter/)
- [A Clean Architecture for a PyQt GUI Using the MVVM Pattern](https://medium.com/@mark_huber/a-clean-architecture-for-a-pyqt-gui-using-the-mvvm-pattern-b8e5d9ae833d)
- [pyside6-mvvm-example (thin View / ViewModel separation in PySide6)](https://github.com/ericjameszimmerman/pyside6-mvvm-example)
