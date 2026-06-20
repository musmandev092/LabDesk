# LabDesk developer documentation

Developer-facing docs, organised loosely along the [Diátaxis](https://diataxis.fr/)
axes. End-user installation, build packaging, and the high-level feature tour live in
the repo-root [`README.md`](../README.md); this tree is for people working *on* the code.

| Doc | Diátaxis | What it answers |
|-----|----------|-----------------|
| [onboarding.md](./onboarding.md) | tutorial / how-to | Set up, run, test, and the quality gates a change must pass |
| [architecture.md](./architecture.md) | explanation | Layers, the dependency rule, and how a write flows through the service boundary |
| [database.md](./database.md) | reference | Schema shape, encryption at rest, migrations, indexes |
| [security-model.md](./security-model.md) | explanation | AuthZ, encryption, licensing, the audit chain, and the threat model |
| [decisions/](./decisions/) | explanation | Architecture Decision Records (ADRs) |

## Quick map

- Source: `src/labdesk/` — packages `db`, `render`, `report`, `services`, `ui`,
  `licensing`, plus `app.py` (composition root), `roles.py`, `whatsapp.py`.
- Tests: `tests/` — run with `QT_QPA_PLATFORM=offscreen uv run pytest`.
- The A+ uplift plan and the read-only audit that motivated it: [`../audit/`](../audit/).
- The tracked technical-debt register and quality gates: [`../DEBT.md`](../DEBT.md).
