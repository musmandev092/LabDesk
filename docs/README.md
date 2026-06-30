# LabDesk developer docs

Docs for people working *on* the code. End-user install, packaging, and the feature
tour are in the repo-root [`README.md`](../README.md).

| Doc | What it answers |
|-----|-----------------|
| [onboarding.md](./onboarding.md) | Set up, run, test, and the quality gates a change must pass |
| [architecture.md](./architecture.md) | Layers, the dependency rule, and the authorized service boundary |
| [database.md](./database.md) | Schema, encryption, migrations, indexes |
| [security-model.md](./security-model.md) | AuthZ, encryption, licensing, audit chain, threat model |
| [decisions/](./decisions/) | Architecture Decision Records |

## Map

- **Source** `src/labdesk/`: `db` (encrypted SQLite), `application` (authorized,
  audited write services + money math), `report`/`render` (PDF/print), `presentation`
  (Qt screens), `licensing`, plus `app.py` (composition root), `roles.py`,
  `whatsapp.py`, `catalog_render.py`.
- **Tests** `tests/`: `QT_QPA_PLATFORM=offscreen uv run pytest`.
- **Debt register & gates** [`../DEBT.md`](../DEBT.md). Historical audit reports
  [`../audit/`](../audit/).
