# LabDesk — Laboratory Management System

A native Linux desktop app (PySide6/Qt6 + encrypted SQLite) that replaces legacy
Windows VB6 + MS Access lab systems. **White-label** (each lab sets its own name,
branding and logo on first run), shipped as a small **compiled binary** (~2–3 MB,
your code is not readable Python on the target PC) and **node-locked** to each
activated machine. The Python/Qt runtime is installed per-PC at setup (one-time
internet), so the distributable stays tiny.

## Features

- **First-run wizard** — lab name, contact, currency, logo, lab-no prefix, admin
  password; re-editable in Settings. The UI auto-scales to small screens (e.g.
  1366×768).
- **Reception / Billing** — register patients (unique, typo-checked Patient ID;
  names auto-tidied to proper case), pick from the 706-test catalog, discount
  (manager-approved for cashiers), take payment, print a receipt.
- **Worklist / Results** — category-aware entry (numeric grid, serology dropdowns,
  imaging/histopath findings boxes, blood-bank groups) with gender-specific ranges
  and an Impression block. Blank values aren't printed; a report can't be saved empty.
- **Reports** — render **by test category** (numeric tables, qualitative serology,
  blood bank, descriptive imaging/histopath, obstetric biometry, culture); auto-detected,
  overridable per test. Up to 3 prior dated columns (cumulative, toggleable).
- **Receipts/Reports** — print, save-as-PDF, or send on **WhatsApp**; receive dues,
  mark delivered, and **verify** a printout against the lab's records.
- **Microbiology, Doctors, Accounts** (income/expense/dues from a dated ledger),
  **Test Catalog** (706 tests / 742 params + reusable panels), **Settings**.
- **Encrypted database** (SQLCipher) unlocked by a password at launch, with optional
  "remember on this computer" via the system wallet. Automatic encrypted backups +
  manual back-up/restore; change the DB password anytime.
- Tamper-evident audit log; role-based access (receptionist / technician / admin).

## Installing (per lab PC)

**Only requirement: internet once during setup.** From the extracted
`labdesk-<version>/` folder, run:

```bash
./install.sh        # installs uv if needed, fetches Python 3.13 + PySide6 + SQLCipher,
                    # drops in the binary, adds the menu entry. Launch from the menu
                    # or ~/.local/bin/labdesk.  Remove later (keeps data): ./uninstall.sh
```

Everything lives under `~/.local/share/LabDesk/`: the program in `app/` + `runtime/`
(removed by uninstall), and your data at the top level (kept). Data:
`~/.local/share/LabDesk/labdesk.sqlite` — override with `LABDESK_DATA_DIR=/path`.

On **first launch**: activate the machine (send the shown request to the vendor, load
back `license.lic`), set a database password, then run the wizard.

> **⚠ The database password cannot be recovered.** If it's lost, the data cannot be
> opened by anyone. Keep it safe and keep backups. Backups made before a password
> change keep the old password — Restore detects this and asks for it.

### Supported systems

The binary targets **glibc ≥ 2.34** (PySide6 6.11's floor), i.e. any 64-bit x86-64
Linux desktop from ~mid-2021 on: AlmaLinux/Rocky/RHEL 9, Ubuntu 22.04/24.04,
Debian 12, Fedora 35+, Mint 21+, Arch/openSUSE Tumbleweed. **Not** supported: ARM /
Raspberry Pi, Windows/macOS, and the 2.28/2.31 LTS releases (RHEL 8, Ubuntu 20.04,
Debian 11). On a *minimal* install add Qt's dlopen'd libs once (the vendor has
internet at setup), e.g. Debian/Ubuntu:

```bash
sudo apt install -y libxcb1 libxcb-cursor0 libxcb-keysyms1 libxcb-image0 \
  libxcb-render-util0 libxcb-icccm4 libxkbcommon-x11-0 libgl1 libegl1 libopengl0 \
  libfontconfig1 libfreetype6 libglib2.0-0 libdbus-1-3 xdg-desktop-portal xdg-desktop-portal-gtk
```

The launcher sets `QT_QPA_PLATFORMTHEME=xdgdesktopportal` so Open/Save dialogs use the
desktop's native picker (install `xdg-desktop-portal` + a backend; falls back to Qt's
built-in dialog if absent).

## Building from source

Requires [`uv`](https://docs.astral.sh/uv/) and `gcc`.

```bash
uv sync                        # dev env
uv run python -m labdesk       # run from source (licensing NOT enforced in dev)
bash scripts/build_release.sh  # PORTABLE build (Docker/manylinux_2_34) -> dist/labdesk-<ver>.tar.gz (ship this)
bash scripts/build_app.sh      # quick host build (NOT portable — dev testing only)
```

Both compile with **Nuitka** in non-bundling mode (Qt/Python fetched per-PC by
`install.sh`). `schema.sql` + `seed.sqlite` (the catalog) are baked into the binary.
Merging to `main` builds the portable tarball and cuts a GitHub Release automatically.
Developer docs: [`docs/`](docs/).

### Licensing (node-lock, offline, Ed25519-signed)

```bash
uv run python scripts/licensing/generate_keys.py   # ONCE — keypair in ~/Documents/LabDesk-signing-key/, embeds pubkey; then rebuild
uv run python scripts/licensing/issue_license.py \  # per customer machine
  --request "<token-from-the-lab>" --lab "Customer Name" --out CPHC.lic --days 90
```

Send the `.lic` back; the lab loads it on the activation screen (shown at first
launch and under **Settings → License & activation**). The whole license (expiry +
bound machine) is signed, with clock-rollback protection — editing it or copying the
app to another PC is rejected. See `src/labdesk/licensing/`.

> **Maintenance:** the runtime is CPython 3.13 (EOL ~Oct 2029); `install.sh` pins
> `--python 3.13` to stay ABI-matched to the shipped binary. Plan the next bump before
> then (3.14 also needs the `pyside6` floor raised).

## Project layout

```
src/labdesk/
  app.py            composition root (auto-scale → license → unlock → wizard → login → window)
  schema.sql        normalized schema      seed.sqlite   shipped catalog (706 tests)
  constants.py roles.py catalog_render.py  shared helpers, RBAC, render-category classifier
  db/               encrypted SQLite: connection/crypto/auth/audit/settings/backup/keyvault/queries
  application/      authorized + audited write services + money math (billing, receipts, results, users)
  report/ render/   lab-report data/verification; native QPainter→PDF rendering (no WeasyPrint)
  presentation/     one module per screen + wizard, unlock, dialogs, style, widgets
  licensing/        offline Ed25519 node-lock + machine fingerprint
scripts/            build_release.sh / build_app.sh / install.sh / uninstall.sh / licensing/
```
