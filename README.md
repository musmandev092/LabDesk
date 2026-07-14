# LabDesk — Laboratory Management System

Native Linux desktop app (PySide6/Qt6 + encrypted SQLite) replacing legacy VB6/Access
lab systems. White-label, shipped as a small compiled binary (~2–3 MB) node-locked per
machine; the Python/Qt runtime installs per-PC at setup (one-time internet).

## Features

Reception/billing (706-test catalog, discounts, receipts) · category-aware results
entry with gender ranges · reports by category (numeric, serology, blood bank,
imaging/histopath, obstetric, culture) with cumulative history · print / PDF / WhatsApp
delivery · microbiology, doctors, accounts ledger, reusable panels · encrypted DB
(SQLCipher) + automatic backups · tamper-evident audit log · role-based access
(receptionist / technician / admin) · first-run wizard; UI auto-scales to small screens.

## Install (per lab PC)

Needs internet once. From the extracted `labdesk-<version>/` folder:

```bash
./install.sh     # fetches Python 3.13 + PySide6 + SQLCipher, installs the binary + menu entry
                 # uninstall later (keeps data): ./uninstall.sh
```

Data lives at `~/.local/share/LabDesk/labdesk.sqlite` (override with `LABDESK_DATA_DIR`).
First launch: activate the machine (send the request to the vendor, load back the
`.lic`), set a database password, run the wizard.

> ⚠ **The database password cannot be recovered.** Lose it and the data is gone. Keep
> backups — each backup keeps the password it was made with.

Targets glibc ≥ 2.34 (x86-64 Linux from ~2021: RHEL/Alma/Rocky 9, Ubuntu 22.04+, Debian
12, Fedora 35+). Not ARM, Windows or macOS. Minimal installs may need Qt's xcb libs.

## Build from source

Requires [`uv`](https://docs.astral.sh/uv/) + `gcc`.

```bash
uv sync                        # dev env
uv run python -m labdesk       # run from source (licensing not enforced in dev)
bash scripts/build_release.sh  # portable Nuitka build -> dist/labdesk-<ver>.tar.gz (ship this)
```

Merging to `main` builds the tarball and cuts a GitHub Release. Developer docs & layout:
[`docs/`](docs/).

### Licensing (offline, Ed25519-signed node-lock)

```bash
uv run python scripts/licensing/generate_keys.py                 # ONCE — keypair + embed pubkey, then rebuild
uv run python scripts/licensing/issue_license.py \
  --request "<token-from-lab>" --lab "Customer" --out x.lic --days 90
```

Send the `.lic`; the lab loads it on the activation screen. Each license is signed
(expiry + bound machine, clock-rollback protected) — editing it or copying the app to
another PC is rejected. See `src/labdesk/licensing/`.

## License

© 2026 M Usman. All rights reserved. Proprietary software — not open source.
