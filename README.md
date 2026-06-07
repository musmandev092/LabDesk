# LabDesk — Laboratory Management System

A native Linux desktop application (PySide6 / Qt6 + SQLite) that replaces legacy
Windows VB6 + Microsoft Access lab systems. **White-label**: every lab enters its
own name, address, logo and branding on first run — nothing is hardcoded.
Delivered as a single self-contained **AppImage** that runs on AlmaLinux and most
Linux desktops with no Python, Qt, or database install required.

## Features

- **First-run setup wizard** — each lab enters its name, tagline, address,
  contact, currency, lab-no prefix, logo, and an admin password. Re-editable in Settings.
- **Reception / Billing** — register patients, pick from the 706-test catalog,
  apply discounts, take payment, print a cash receipt.
- **Worklist / Results** — enter results per parameter with gender-specific
  reference ranges, then print / PDF a branded lab report.
- **Test Catalog** — 706 tests + 749 parameters; browse, search, add, edit.
- **Microbiology** — culture & sensitivity (specimen, growth, organism,
  Gram/ZN stain, antibiotic S/I/R).
- **Doctors**, **Accounts** (income/expense/dues), **Settings**, user password.

## Running it

```bash
# (optional but recommended) verify the download is intact/authentic first:
sha256sum -c LabDesk-x86_64.AppImage.sha256

chmod +x LabDesk-x86_64.AppImage
./LabDesk-x86_64.AppImage
```

On first launch you'll see the **setup wizard** — enter your lab's details and an
admin password. After that, sign in as `admin` with the password you set.

Data lives at `~/.local/share/LabDesk/labdesk.sqlite`. It is seeded with the test
catalog on first run. Override the location with `LABDESK` style env var
`LABDESK_DATA_DIR=/path` (legacy name, still honoured).

## Security & data protection

LabDesk holds patient PII and medical results. What the app does for you, and
what the deployment must do:

- **Passwords** are stored with scrypt (memory-hard) + per-user salt; logins are
  rate-limited with an exponential lockout. The audit log is a tamper-evident
  hash chain (see the **Logs** page).
- **On-disk protection.** The data dir is `0700` and the database, its WAL/SHM
  sidecars, the WhatsApp token (`.secrets.json`) and backups are `0600` — i.e.
  readable only by the OS user that runs LabDesk.
- **Trust boundary — important.** Roles (receptionist/technician/admin) are
  enforced inside the app, but the database is a plain file owned by the OS user.
  Anyone who can log into that OS account (or copy the file) can read or change
  the data directly, bypassing roles. Therefore:
  - give each staff member their **own OS login**, *or*
  - on a shared machine, enable **full-disk encryption** and lock the screen.
- **WhatsApp delivery.** Reports/bills are sent through WhatsApp (Meta), so that
  data transits a third party. Send only to patients who have agreed — there is a
  per-patient consent toggle in **Reception** (on by default, timestamped). Use
  an `https://` gateway for anything not running on this same computer; the app
  warns before sending over plain `http` to another host.

### If the app does not start on a *minimal* AlmaLinux

The AppImage bundles Python and Qt, but the X11/`xcb` platform plugin needs a few
low-level system libraries that desktop installs already have. On a minimal
install run once:

```bash
sudo dnf install -y libxcb xcb-util-cursor xcb-util-keysyms xcb-util-image \
    xcb-util-renderutil xcb-util-wm libxkbcommon-x11 mesa-libGL fontconfig
```

AppImages also need FUSE. If you see a FUSE error, either
`sudo dnf install -y fuse fuse-libs` or run
`./LabDesk-x86_64.AppImage --appimage-extract-and-run`.

## Building from source

Requires [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync                          # env with PySide6
uv run python -m labdesk         # run the app
bash scripts/build_appimage.sh   # -> build/LabDesk-x86_64.AppImage (+ .sha256)
```

> **Maintenance TODO:** the bundle ships CPython 3.12, which enters
> security-fixes-only EOL in **Oct 2028**. Plan an interpreter bump (3.13/3.14)
> before then. `appimagetool` is pinned by version + SHA-256 in
> `scripts/build_appimage.sh` — bump both together when updating it.

The test catalog the app ships with is baked into `src/labdesk/seed.sqlite`.
It was built once from the old Access system; that one-time migration is done,
so there is nothing to re-migrate. (The original migration scripts and staging
data were retired — the staging DBs live outside the repo under
`../migration_data/` only as an archive.)

## Project layout

```
src/labdesk/        (internal package name)
  app.py            bootstrap (wizard -> login -> main window)
  db.py             SQLite layer, schema, seeding, auth, white-label settings
  schema.sql        clean normalized schema
  report.py         receipt + lab-report data/logic, print & PDF API
  render.py         native Qt (QPainter→QPdfWriter) PDF rendering — no WeasyPrint
  seed.sqlite       catalog the app ships with (706 tests, no branding)
  ui/               one module per screen + setup_wizard + style
scripts/
  build_appimage.sh   bundle python+PySide6+app -> LabDesk-x86_64.AppImage
  install_desktop.sh  add LabDesk to the applications menu
  qa_screens.py       render screenshots of every screen (dev/QA only)
```
