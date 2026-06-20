# A+ Uplift Plan — Dimension 06: Documentation

**Current grade:** B+ (per `audit/11-documentation-review.md`)
**Target:** Solid A / A+
**Author:** Docs-uplift agent · **Date:** 2026-06-16
**Scope:** Planning only. The only file written by this task is this report.

---

## 0. Why B+ today (grounded in the existing audit)

`audit/11-documentation-review.md` is candid and correct: LabDesk is *unusually
well-documented for its size*, but its documentation is **lopsided**.

What it has (keep):
- `README.md` (16.5 KB) — a genuine operator + vendor manual: install, security
  model, distro/glibc matrix, build, licensing, layout. Verified accurate.
- `WHATSAPP_SETUP.md` (7.4 KB) — a correct step-by-step operator runbook.
- Strong, current module-level docstrings that explain **why** (`db/__init__.py`
  layering chain, `report/__init__.py` ↔ `render/__init__.py` import cycle,
  `licensing/__init__.py` gated `enforced()`).

What it lacks (the gap to A):
1. **No information architecture.** Two long Markdown files + 82 file headers. No
   Diátaxis split, no `docs/` tree, no entry point for a new reader to navigate by
   *need* (learn / do / look-up / understand).
2. **No architecture diagrams.** §2.1 of the audit is a hand-drawn ASCII layer
   sketch; there is no C4 Context/Container/Component model and nothing
   version-controlled or regenerable.
3. **No ADR log.** Major decisions (single shared SQLCipher passphrase; money as
   `REAL`; deliberate `report`↔`render` import cycle; Nuitka non-bundling; inline
   write paths vs a service layer; offline Ed25519 licensing) live as folklore in
   docstrings and review prose — never as decisions with context + consequences.
4. **No generated API reference.** Docstrings are rich (`db/queries.py`,
   `render/report_doc.py:667`, `report/verify.py`) but never surfaced as browsable
   HTML, and nothing in CI keeps them honest.
5. **No `CONTRIBUTING`/onboarding doc.** Setup/run/test/layering conventions exist
   only in scattered headers (audit gap #1, severity High).
6. **No consolidated schema reference** and an active trap: the live schema =
   `schema.sql` (v1 baseline) **+** `db/_config.py::_EXTRA_COLUMNS` additive
   columns. A reader of `schema.sql` alone sees the wrong shape (audit gap #2, High).
7. **No operations runbook beyond WhatsApp** (DB unlock-failure, key loss, backup/
   restore, audit-chain break, license expiry, plaintext→encrypted migration).
8. **No requirements→code→tests traceability** — and for a HIGH-criticality medical
   LIS this is the single most consequential omission (IEC 62304 territory).
9. **Stale entries** the audit already flagged: `audit/02-module-map.md` mislabels
   `whatsapp.py` as "WhatsApp **Cloud-API**" (it is a self-hosted **wuzapi /
   whatsmeow** gateway) and lists `APP_NAME`/`APP_VERSION` where the module exports
   only `__version__`; README "no branding" seed note and a `report/__init__.py`
   WeasyPrint reference are stale-as-history.

The throughline: **content quality is already A-grade; what's missing is
*structure, diagrams, decisions, generation, and traceability* — i.e. the
docs-as-code discipline.** That is exactly what the requested frameworks supply.

---

## 1. What "A+" means for documentation (researched, with citations)

I anchor the bar on five authoritative bodies of practice.

### 1.1 Diátaxis — information architecture by user need
Diátaxis splits docs into four modes on two axes (action↔cognition,
acquisition↔application): **Tutorials** (learning-oriented), **How-to guides**
(task-oriented), **Reference** (information-oriented), **Explanation**
(understanding-oriented). It explicitly "solves problems related to documentation
content (what to write), style (how to write it) and architecture (how to organise
it)." A+ docs are navigable by *need*, not by file.
Source: <https://diataxis.fr/>

### 1.2 C4 model — architecture diagrams that scale by zoom
C4 describes architecture at four levels — **System Context**, **Container**,
**Component**, **Code** — plus supplementary **System Landscape / Dynamic /
Deployment** diagrams. It is notation- and tooling-independent; for many systems a
**Context + Container** pair is sufficient, with Component diagrams for the parts
that matter. A+ architecture docs include at least Context + Container + one or two
Component views, version-controlled.
Sources: <https://c4model.com/> · <https://miro.com/diagramming/c4-model-for-software-architecture/>

### 1.3 ADRs / MADR — decisions captured as records
An Architectural Decision Record documents a single significant decision with its
**Context and Problem Statement, Decision Drivers, Considered Options, Decision
Outcome, Consequences (+ Confirmation)**. MADR recommends storing them as
`docs/decisions/NNNN-title-with-dashes.md`, consecutively numbered, version
controlled. The Nygard form (Status / Context / Decision / Consequences) is the
minimal acceptable variant. A+ = a living ADR log covering the load-bearing
decisions.
Sources: <https://adr.github.io/madr/> · <https://github.com/adr/madr> · <https://adr.github.io/adr-templates/>

### 1.4 Docs-as-code + generated API reference in CI
Docs live in the repo, are reviewed in PRs, and are **built/validated in CI** so
they "always reflect the current state of your codebase." For a Python-only,
prose-first project, **MkDocs + Material + mkdocstrings** is the pragmatic stack
(Markdown, autodoc from docstrings); **Sphinx + autodoc** is the heavier
reference-first alternative used by NumPy/Django. A+ = API reference auto-generated
from docstrings and a CI gate that fails on broken builds/links.
Sources: <https://pydevtools.com/handbook/how-to/how-to-set-up-documentation-for-a-python-package/> · <https://oneuptime.com/blog/post/2026-01-27-generate-documentation-github-actions/view>

### 1.5 Runbooks (SRE) — operations that survive the author leaving
A trustworthy runbook is **Actionable, Accessible, Accurate, Authoritative,
Adaptable**, stored centrally, and covers detection → triage → investigation →
resolution → postmortem for the most common failure modes; the goal is to "reduce
reliance on individual expertise and avoid human error" and to lower MTTR.
Sources: <https://blog.incidenthub.cloud/The-No-Nonsense-Guide-to-Runbook-Best-Practices> · <https://rootly.com/incident-response/runbooks>

### 1.6 IEC 62304 — traceability for medical-device software (the differentiator)
LabDesk is a HIGH-criticality medical/clinical LIS. IEC 62304 expects **end-to-end
traceability across requirements → architecture → implementation → tests → risk
controls**, maintained via a traceability matrix, plus controlled records of
development decisions and verification. We are **not** claiming certification here;
we adopt 62304's *documentation posture* — a software requirements list, a design
description, and a requirements→code→tests matrix — because it is the right A+ bar
for software that releases clinical results. (Note: a true 62304 program also needs
a risk-management file per ISO 14971 and a QMS; out of scope for a docs uplift, but
named so the boundary is explicit.)
Sources: <https://www.dqsglobal.com/en/explore/blog/iec62304-traceability-framework> · <https://www.jamasoftware.com/requirements-management-guide/medical-devices/iec-62304/>

---

## 2. Concrete A+ acceptance criteria for LabDesk

A reviewer should be able to check every box:

| # | Criterion | Measurable bar | Standard |
|---|---|---|---|
| AC1 | Diátaxis IA exists | `docs/` tree with `tutorials/`, `how-to/`, `reference/`, `explanation/` + an index that routes by need | Diátaxis |
| AC2 | C4 diagrams | Context + Container + ≥1 Component (e.g. the `db/` write boundary) committed as source (Mermaid/`.dsl`) and rendered in docs | C4 |
| AC3 | ADR log | ≥10 ADRs in `docs/decisions/NNNN-*.md` (MADR), covering every load-bearing decision in §3.3; an ADR index/README | MADR |
| AC4 | Generated API reference | `db`, `services`, `report`, `licensing`, `whatsapp` public surfaces auto-rendered from docstrings; published artifact | docs-as-code |
| AC5 | Docs build in CI | A `docs` CI job: build is `--strict` (fails on warnings/dead links), runs on every PR | docs-in-CI |
| AC6 | Docstring lint gate | `ruff` pydocstyle rules (`D`) enabled for public API packages; missing/broken docstrings fail CI | docs-as-code |
| AC7 | CONTRIBUTING / onboarding | `CONTRIBUTING.md` + `docs/explanation/developing.md` from audit §5.4 | Diátaxis (how-to/explanation) |
| AC8 | Schema reference | `docs/reference/schema.md` documenting all 20 tables **and** the `_EXTRA_COLUMNS` overlay, with the explicit "schema.sql alone is incomplete" warning | reference |
| AC9 | Operations runbook | `docs/how-to/operations-runbook.md` covering ≥6 failure modes (key loss, unlock failure, audit-chain break, backup/restore, license expiry, plaintext→encrypted migration) | SRE runbook |
| AC10 | Traceability matrix | `docs/reference/requirements.md` (SRS-lite) + `docs/reference/traceability.md` mapping requirement → module:line → test, focused on the trust-critical paths | IEC 62304 |
| AC11 | No stale docs | audit gaps #3–#5 fixed; a doc-link/anchor check passes; docs versioned to `__version__` | accuracy |
| AC12 | Diagrams + matrix regenerate, not rot | C4 source and the traceability matrix are buildable; CI rebuilds them | docs-as-code |

**Table-stakes for A:** AC1, AC2 (Context+Container), AC3 (Nygard-min ADRs for the
top ~8 decisions), AC4, AC5, AC7, AC8, AC9, AC11.
**Stretch for A+:** AC2 Component-level + Deployment, AC3 full MADR with
Confirmation, AC6 docstring lint gate, AC10 traceability matrix, AC12 regeneration.

The traceability matrix (AC10) and the docstring lint gate (AC6) are what separate
a *good* B+/A docs set from an **A+ for a regulated medical LIS**.

---

## 3. Target documentation tree (what to author, and where)

```
README.md                         # stays: landing + 30-second orientation, links into docs/
CONTRIBUTING.md                   # NEW: how to contribute, run, test, lint, layering rules
docs/
  index.md                        # NEW: Diátaxis compass — routes reader by need
  tutorials/
    01-run-from-source.md         # NEW: clone → uv sync → run → first login (learning path)
    02-first-report-walkthrough.md# NEW: create a bill → enter result → release → print
  how-to/
    build-and-release.md          # NEW: from README §build (manylinux_2_34, gen_embedded)
    install-on-a-lab-pc.md        # NEW: from README §install
    issue-a-license.md            # NEW: from README §licensing (Ed25519 flow)
    configure-whatsapp.md         # MOVE: WHATSAPP_SETUP.md, lightly re-headed
    operations-runbook.md         # NEW: failure-mode runbook (AC9)
  reference/
    architecture.md               # NEW: C4 Context+Container+Component (AC2)
    schema.md                     # NEW: 20 tables + _EXTRA_COLUMNS overlay (AC8)
    modules.md                    # NEW: per-package module map (port audit §3, de-staled)
    api/                          # GENERATED: mkdocstrings/autodoc output (AC4)
    requirements.md               # NEW: SRS-lite, numbered REQ-### (AC10)
    traceability.md               # NEW: REQ → module:line → test matrix (AC10)
    config-and-env.md             # NEW: LABDESK_DATA_DIR, LABDESK_DB_KEY, _SELFTEST, _ENFORCE_LICENSE
  explanation/
    architecture-overview.md      # NEW: port audit §2, the "why" of layering/cycle
    security-model.md             # NEW: extract README security section as explanation
    where-the-rules-live.md       # NEW: the inline-write-path caveat (audit gap #7)
    developing.md                 # NEW: layering discipline + conventions (audit §5.4)
  decisions/
    README.md                     # NEW: ADR index + how-to-write-an-ADR
    0000-use-madr.md              # NEW: meta-ADR adopting the format
    0001..00NN-*.md               # NEW: the ADRs in §3.3
  diagrams/
    c4-context.mmd                # NEW: Mermaid (or workspace.dsl for Structurizr)
    c4-container.mmd              # NEW
    c4-component-db-write.mmd     # NEW: db write boundary / audit chain
mkdocs.yml                        # NEW: MkDocs Material + mkdocstrings config
```

> **Single-source rule:** README and `WHATSAPP_SETUP.md` should **shrink to
> pointers** once content moves into `docs/` — keep README as the landing page, but
> the authoritative copy lives in one place. Avoid forking content into two files.

### 3.1 Map: existing content → Diátaxis bucket
- README install/build/license/layout → `how-to/*` + `reference/architecture.md`.
- README security model → `explanation/security-model.md`.
- `WHATSAPP_SETUP.md` → `how-to/configure-whatsapp.md`.
- Module docstrings → surfaced via `reference/api/` (generated) + `reference/modules.md`.
- Audit §2 (architecture), §4 (schema), §5.4 (onboarding) → seed the new reference/
  explanation pages (they are already written and verified — port, don't rewrite).

### 3.2 The Diátaxis discipline to enforce (so it stays A+)
Each page is **one mode only**: a tutorial never becomes reference; a reference page
never tells a story. The audit's §5 mixes build + install + license + onboarding in
one section — split along the four modes per <https://diataxis.fr/>.

### 3.3 ADRs to author (the load-bearing decisions — AC3)
Each as `docs/decisions/NNNN-title.md` in MADR/Nygard form. These are the real
decisions encoded in the codebase and the audit:

1. `0001-single-sqlcipher-passphrase-for-data-rbac-audit.md` — context, the
   conflated trust boundary, alternatives (split keys / off-DB audit anchor),
   consequences. (Ties to `db/connection.py`, security audit B.)
2. `0002-store-money-as-real-float.md` — the `REAL` PKR decision and its risks;
   alternative integer-minor-units. (`schema.sql`, `services/billing.py:15`.)
3. `0003-report-render-deliberate-import-cycle.md` — why `report`↔`render` lazy
   cycle exists. (`report/__init__.py`, `render/__init__.py`.)
4. `0004-nuitka-non-bundling-build.md` — Qt/Python excluded, ~2-3 MB tarball,
   glibc-2.34 floor. (`scripts/build_release.sh`.)
5. `0005-baked-resources-via-gen-embedded.md` — schema/seed/assets base64 into the
   binary, runtime materialise to 0700 temp. (`scripts/gen_embedded.py`,
   `_resources.py`.)
6. `0006-offline-ed25519-node-lock-licensing.md` — offline node-lock, gated
   enforcement, clock-rollback high-water-mark. (`licensing/`.)
7. `0007-sha256-hash-chained-audit-log.md` — chain design + the open issue that the
   head is not anchored off-DB. (`db/audit.py:61`.)
8. `0008-self-hosted-wuzapi-whatsmeow-gateway.md` — *not* Meta Cloud API; SSRF/
   cross-host guards. (`whatsapp.py`; also fixes audit stale #3.)
9. `0009-additive-extra-columns-migration.md` — `_EXTRA_COLUMNS` overlay vs editing
   `schema.sql`. (`db/_config.py`.)
10. `0010-inline-write-paths-pending-service-layer.md` — **status: accepted-with-
    debt**; documents that bill creation (`ui/reception.py:627`) and result release
    (`ui/worklist.py:425`, `ui/microbiology.py:237`) run multi-table transactions
    inline with no `require()`/service boundary; links to the architecture-uplift
    plan. This is the most important ADR — it converts a hidden trap into a recorded,
    owned decision.

ADR `0000-use-madr.md` records adopting the format itself.

---

## 4. Tooling recommendations (recommendations only — nothing installed)

> Per repo memory rule, these are **recommendations requiring explicit OK before
> install**. None are added in this task.

| Tool | Purpose | Why this one | Source |
|---|---|---|---|
| **MkDocs + Material** | Site generator + nav (Diátaxis tabs) | Markdown-first, matches the existing Markdown corpus; minimal ramp; great nav for a prose+API hybrid | <https://pydevtools.com/handbook/how-to/how-to-set-up-documentation-for-a-python-package/> |
| **mkdocstrings[python]** | API reference from docstrings (AC4) | Autodoc for Python-only projects; renders the rich `db`/`report`/`licensing` docstrings with zero rewriting | <https://pydevtools.com/handbook/how-to/how-to-set-up-documentation-for-a-python-package/> |
| **Mermaid** (built into Material) **or Structurizr DSL** | C4 diagrams as code (AC2) | Mermaid = zero new binary, renders in-page; Structurizr DSL = canonical C4 if you want a single model → multiple views | <https://c4model.com/> |
| **ruff pydocstyle rules (`D`)** | Docstring lint gate (AC6) | Ruff is **already a dependency** (`pyproject.toml`) — enabling the `D` ruleset on public packages is a config change, *no new install* | <https://oneuptime.com/blog/post/2026-01-27-generate-documentation-github-actions/view> |
| **lychee** or **mkdocs `--strict`** | Dead-link / broken-anchor gate (AC5/AC11) | `--strict` ships with MkDocs (no new tool); lychee adds external-link checking | docs-in-CI |
| *(alt)* **Sphinx + autodoc + myst-parser** | Reference-first alternative to MkDocs | Choose only if you later want intersphinx / PDF / heavier reference tooling | <https://github.com/encode/httpx/discussions/1220> |

**Recommendation:** adopt **MkDocs Material + mkdocstrings + Mermaid**, and enable
**ruff `D` rules** (already-present tool). This is the lowest-friction path to AC1–AC6.

---

## 5. Docs CI to add (AC5, AC6, AC11, AC12)

Extend `.github/workflows/ci.yml` (currently test + self-test only) with a `docs`
job — runnable without Qt, so it's fast:

```yaml
  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen --group docs        # NEW optional dep-group: mkdocs-material, mkdocstrings[python]
      - name: Docstring lint (public API surfaces)
        run: uv run ruff check --select D src/labdesk/db src/labdesk/services \
                                            src/labdesk/report src/labdesk/licensing \
                                            src/labdesk/whatsapp.py
      - name: Build docs (strict — fails on warnings & dead links)
        run: uv run mkdocs build --strict
      # optional publish on main:
      # - run: uv run mkdocs gh-deploy --force   (only on main)
```

Plus a small **traceability check** (AC12): a tiny script (e.g.
`scripts/check_traceability.py`) that parses `docs/reference/traceability.md` and
asserts every referenced test id exists in `tests/` and every `module:line`
resolves — so the matrix can't silently rot. Wire it into the `docs` job.

CI gates this delivers: docs build is enforced on every PR; public docstrings are
linted; dead links fail the build; the traceability matrix is validated.

---

## 6. Ordered, file-specific gap-closing plan

Effort S/M/L · Risk is to the *codebase* (docs work is inherently Low-risk; "risk"
here is mostly churn/accuracy-maintenance, never runtime).

| # | Step | Files | Effort | Risk | Impact | Satisfies |
|---|---|---|---|---|---|---|
| 1 | Fix the known stale docs first (cheap credibility win) | `audit/02-module-map.md` (whatsapp label, `__version__`), `README.md` (seed "no branding"; mark WeasyPrint removed), `report/__init__.py` docstring note | S | Low | Med | AC11 |
| 2 | Scaffold `docs/` Diátaxis tree + `docs/index.md` compass; add `mkdocs.yml` (Material, nav by mode) | `docs/`, `mkdocs.yml` | S | Low | High | AC1 |
| 3 | Port audit §2 → `explanation/architecture-overview.md`; audit §4 → `reference/schema.md` **with the `schema.sql` + `_EXTRA_COLUMNS` warning**; audit §3 → `reference/modules.md` | new docs; sources `db/_config.py`, `schema.sql` | M | Low | High | AC8 |
| 4 | Author C4 diagrams as code (Context, Container, Component=db write boundary/audit chain) | `docs/diagrams/*.mmd`, embed in `reference/architecture.md` | M | Low | High | AC2 |
| 5 | Write `CONTRIBUTING.md` + `explanation/developing.md` from audit §5.4 (layering, Qt-free rule, env overrides) | `CONTRIBUTING.md`, `docs/explanation/developing.md` | S | Low | High | AC7 |
| 6 | Write `explanation/where-the-rules-live.md` — the inline-write-path caveat (`ui/reception.py:627`, `ui/worklist.py:425`, `ui/microbiology.py:237`) | new doc | S | Low | High | AC7, AC10 |
| 7 | Split README/WhatsApp content into Diátaxis how-tos (build/install/license/whatsapp) and shrink the originals to pointers | `docs/how-to/*`, trim `README.md`, move `WHATSAPP_SETUP.md` | M | Low | Med | AC1 |
| 8 | Write tutorials (run-from-source; first-report walkthrough) | `docs/tutorials/*` | M | Low | Med | AC1 |
| 9 | Write `how-to/operations-runbook.md` — ≥6 failure modes (key loss, unlock fail, audit-chain break via `db/audit.py` verifier, backup/restore via `db/backup.py`, license expiry, plaintext→encrypted via `db/connection.py`) | new doc | M | Low | High | AC9 |
| 10 | Author the 10 ADRs (§3.3) + ADR index | `docs/decisions/*.md` | M | Low | High | AC3 |
| 11 | Enable mkdocstrings; generate `reference/api/` from docstrings for `db`, `services`, `report`, `licensing`, `whatsapp` | `mkdocs.yml`, `docs/reference/api/` | M | Low | High | AC4 |
| 12 | Enable ruff `D` docstring rules for public packages (ruff already a dep — config only) | `pyproject.toml [tool.ruff]` | S | **Med** | Med | AC6 |
| 13 | Author SRS-lite `reference/requirements.md` (numbered REQ-###) for trust-critical behavior (auth/RBAC, audit chain, money math, result release, report verify, licensing, encryption) | new doc | M | Low | High | AC10 |
| 14 | Build `reference/traceability.md` matrix: REQ → `module:line` → test, targeting the 0%-coverage trust features (`db/audit.py:61`, `report/verify.py:44`, `services/billing.py:15`) called out in the brief | new doc; reads `tests/` | L | Low | High | AC10 |
| 15 | Add `docs` CI job (build `--strict`, docstring lint) + optional `gh-deploy` on main | `.github/workflows/ci.yml`, new `docs` dep-group in `pyproject.toml` | M | Low | High | AC5 |
| 16 | Add `scripts/check_traceability.py` and wire into CI so the matrix can't rot | new script, `ci.yml` | M | Low | Med | AC12 |
| 17 | Version-stamp docs to `__version__`; add a docs section to `CONTRIBUTING` ("update docs in the same PR as code") | `mkdocs.yml`, `CONTRIBUTING.md` | S | Low | Med | AC11 |

**Sequencing note:** Steps 1–5 get you most of the way to a **solid A** quickly
(IA + diagrams + schema + onboarding + de-staling). Steps 9–16 (runbook, ADRs,
generated API, requirements, traceability matrix, docs CI) are what earn the **A+**,
with the **traceability matrix (14) + docs CI (15/16) being the decisive, regulated-
software differentiators**.

### Risk callouts
- **Step 12 (ruff `D` rules) is the only non-trivial-risk item:** enabling pydocstyle
  on the whole tree will flood the existing code with warnings. Mitigation: scope `D`
  to public-API packages only (`db`, `services`, `report`, `licensing`,
  `whatsapp`), `per-file-ignores` for `ui/`/`render/` internals, and ratchet up. It
  is a *config* change to an already-present tool — no install, no runtime change.
- Everything else is additive docs/CI — **no source/runtime risk**.

---

## 7. Honest scoping — what this does and does NOT claim

- This plan delivers an **A+ *documentation* posture**, including the 62304-style
  *documentation artifacts* (SRS-lite, design description, traceability matrix). It
  does **not** constitute IEC 62304 certification, an ISO 14971 risk-management
  file, or a QMS — those are program-level, out of a docs uplift's scope, and are
  named here so the boundary is explicit and not oversold.
- It deliberately **reuses** the already-verified audit content (§2/§4/§5.4) rather
  than rewriting it; the work is largely *restructuring + diagramming + decision-
  recording + wiring CI*, not net-new prose discovery.
- The `0010` ADR and `where-the-rules-live.md` intentionally document a known
  *defect* (inline write paths) rather than hide it — recording debt is itself an
  A+ documentation behavior, and it dovetails with the Architecture uplift plan.

---

## 8. Key sources
- Diátaxis framework — <https://diataxis.fr/>
- C4 model — <https://c4model.com/> ; overview — <https://miro.com/diagramming/c4-model-for-software-architecture/>
- MADR — <https://adr.github.io/madr/> ; MADR repo — <https://github.com/adr/madr> ; ADR templates — <https://adr.github.io/adr-templates/>
- Sphinx vs MkDocs / autodoc setup — <https://pydevtools.com/handbook/how-to/how-to-set-up-documentation-for-a-python-package/> ; <https://github.com/encode/httpx/discussions/1220>
- Generate docs in CI (GitHub Actions) — <https://oneuptime.com/blog/post/2026-01-27-generate-documentation-github-actions/view>
- Runbook best practices — <https://blog.incidenthub.cloud/The-No-Nonsense-Guide-to-Runbook-Best-Practices> ; <https://rootly.com/incident-response/runbooks>
- IEC 62304 traceability — <https://www.dqsglobal.com/en/explore/blog/iec62304-traceability-framework> ; <https://www.jamasoftware.com/requirements-management-guide/medical-devices/iec-62304/>
