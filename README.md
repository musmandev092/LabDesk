# LabDesk — Laboratory Management System

A native Linux desktop application (PySide6 / Qt6 + SQLite) that replaces legacy
Windows VB6 + Microsoft Access lab systems. **White-label**: every lab enters its
own name, address, logo and branding on first run — nothing is hardcoded.
The app ships as a small **native binary** — your code is compiled (no readable
Python on the target PC) — and is **node-locked to each machine** it's activated
for. The Python/Qt runtime is installed per-PC at setup (one-time internet), so
the distributable stays tiny (~2 MB) instead of bundling all of Qt.

## Features

- **First-run setup wizard** — each lab enters its name, tagline, address,
  contact, currency, lab-no prefix, logo, and an admin password. Re-editable in Settings.
- **Reception / Billing** — register patients (each gets a unique, typo-checked
  **Patient ID**), pick from the 706-test catalog, apply discounts, take payment,
  print a cash receipt.
- **Worklist / Results** — enter results per parameter with gender-specific
  reference ranges, then print / PDF a branded lab report. The entry screen
  **adapts to each test type**: numeric tests get a value/unit/reference grid with
  a live out-of-range cue; serology gets Positive/Negative/Reactive dropdowns;
  imaging/histopathology get wide multi-line **findings** boxes (pre-filled with
  the normal text); blood-bank gets group/compatibility dropdowns — each with an
  **Impression / Interpretation** box where it applies.
- **Report layouts** — reports render by **test category**, the way real labs print
  them: numeric tables (CBC/LFT/RFT), qualitative serology (Test │ Result │
  Reference, polarity-coloured), blood bank (Result only), descriptive imaging &
  histopathology (organ/findings narrative + **Impression**), obstetric biometry
  (measurements + units + impression), and culture & sensitivity. The layout is
  auto-detected from the test's parameters and can be **overridden per test** in the
  catalog editor. Numeric reports can show up to **3 previous dated results**
  (cumulative reporting, toggleable per lab); imaging carries a "compared with
  previous study" note.
- **Receipts / Reports** — print, save-as-PDF or send the bill/report on
  **WhatsApp**, receive dues, mark delivered, and **verify** a report (below).
- **Report verification** — every finalised report prints a tamper-evident
  **verification code** in its footer; staff re-check a presented printout against
  the lab's own records on **Receipts → Verify report** (✓ authentic / ✗ altered).
- **Test Catalog** — 706 tests + 742 parameters; browse, search, add, edit, and
  group into reusable **panels** (e.g. "Fever Profile").
- **Microbiology** — culture & sensitivity (specimen, growth, organism,
  Gram/ZN stain, antibiotic S/I/R).
- **Doctors**, **Accounts** (income/expense/dues), and **Settings** — branding,
  registration numbers, editable report/receipt footer text, light/dark theme,
  default printer, WhatsApp, users & roles, **automatic encrypted backups** (on exit
  and once a day, to a folder you choose — e.g. a USB drive or network share — with a
  Documents fallback) plus manual **"Back up now"** + restore, and **change the
  database password**.
- **Encrypted database** — all data is encrypted at rest (SQLCipher); a database
  password unlocks it at launch, with an optional "remember on this computer" via the
  system wallet (see Security).
- **Responsive UX** — saves run without freezing the window and confirm with a
  non-blocking toast (top-right); only questions that need an answer are modal.

## Installing (on each lab PC)

LabDesk is installed per-PC: the compiled app is dropped in and its Python/Qt
runtime is fetched once from PyPI. You (the vendor) run this during setup.

**Only requirement:** internet **once** during setup. From the extracted
`labdesk-<version>/` folder you were given, just run:

```bash
./install.sh
```

`install.sh` installs [`uv`](https://docs.astral.sh/uv/) automatically if it isn't
already present (it only needs `curl`), then uses it to build the runtime.

That installs Python 3.13 + PySide6 + SQLCipher + jeepney into an isolated runtime,
drops in the compiled app binary, and adds **LabDesk** to the applications menu
with its icon (refreshes both GNOME/GTK and KDE Plasma caches). Launch it from the
menu, or run `~/.local/bin/labdesk`. To remove it later (keeps your data):
`./uninstall.sh`.

Everything lives under **one** folder, `~/.local/share/LabDesk/`: the program in
`app/` + `runtime/` (these are what `uninstall.sh` removes), and your data — the
encrypted database, license, and lab branding — at the top level (kept on uninstall).

On **first launch** LabDesk asks to **activate this computer** — send the shown
activation request to the vendor and load back the `license.lic` they return (see
*Licensing* under *Building from source*). You can also re-activate or renew later
from **Settings → "License & activation"**. Then you **set a database password**
(encrypts all data) and go through the **setup wizard** — lab details, an admin
password, and (optionally) a **backup folder** (USB drive or network share). After
that each launch asks for the database password first (or unlocks automatically if
you ticked "Remember on this computer"), then you sign in as `admin`.

Data lives at `~/.local/share/LabDesk/labdesk.sqlite`, seeded with the test catalog
on first run. Override the location with `LABDESK_DATA_DIR=/path`.

## Security & data protection

LabDesk holds patient PII and medical results. What the app does for you, and
what the deployment must do:

- **Encryption at rest.** The database is encrypted with **SQLCipher** (page-level
  AES; the data pages *and* the write-ahead log are never written in plaintext).
  A **database password**, set on first run, is entered once at launch to unlock it
  — so a copied `labdesk.sqlite` (and its backups, which are encrypted with the same
  password) is just random bytes to anyone without it. **⚠ The database password
  cannot be recovered — if it is lost, the data cannot be opened by anyone.** Keep it
  safe and keep backups. Optionally tick **"Remember on this computer"** to save the
  password in your **KDE Wallet / GNOME Keyring** so LabDesk unlocks without asking
  (it's protected by your OS login; Settings → Backup & restore → "Forget saved
  password" undoes it). You can **change the database password** anytime in Settings
  (it re-encrypts in place). Backups made *before* a password change keep the *old*
  password — Restore detects this and asks for that backup's password, so an older
  backup is never lost just because the password was rotated.
- **Passwords** are stored with scrypt (memory-hard) + per-user salt; logins are
  rate-limited with an exponential lockout. The audit log is a tamper-evident
  hash chain (see the **Logs** page). (These per-user logins are separate from the
  database password above: the DB password unlocks the file; logins gate roles.)
- **Report verification.** Each finalised report carries a footer code that is a
  keyed HMAC over its snapshotted results (per-lab key, kept in the database so it
  survives backup/restore). **Receipts → Verify report** recomputes it and flags a
  tampered printout. It verifies *against the issuing lab* — there is no public
  verifier, and forging a matching code needs the lab's key, which never leaves
  the lab's database.
- **On-disk protection.** The data dir is `0700` and the database, its WAL/SHM
  sidecars, the WhatsApp token (`.secrets.json`) and backups are `0600` — i.e.
  readable only by the OS user that runs LabDesk.
- **Trust boundary.** A copied database file is now **encrypted** — useless without
  the database password. Roles (receptionist/technician/admin) are still enforced
  *inside* the app, so once the DB is unlocked and a session is open, anyone at that
  logged-in screen operates under that session's privileges. So on a shared machine
  still **lock the screen**, and ideally give each staff member their **own OS
  login**. (The password protects the data on disk / when copied; it is not a
  substitute for not leaving an unlocked session unattended.)
- **WhatsApp delivery.** Reports/bills are sent through WhatsApp (Meta), so that
  data transits a third party. Send only to patients who have agreed — there is a
  per-patient consent toggle in **Reception** (on by default, timestamped). Use
  an `https://` gateway for anything not running on this same computer; the app
  warns before sending over plain `http` to another host.

### Supported systems & required system libraries

The compiled binary targets **glibc 2.34** (PySide6 6.11's own wheel floor, released
Aug 2021), so it runs on any 64-bit (x86-64) Linux desktop from ~mid-2021 onward —
in practice every mainstream distro still in support except the 2018–2020 enterprise
LTS releases. Verified end-to-end on clean AlmaLinux 9 and Ubuntu 22.04 containers.

| ✅ Supported (glibc ≥ 2.34) | ❌ Too old (glibc < 2.34) |
|---|---|
| AlmaLinux / Rocky / RHEL **9** (2.34) | RHEL / AlmaLinux **8** (2.28) |
| Ubuntu **22.04 LTS / 24.04 LTS** (2.35 / 2.39) | Ubuntu **20.04 LTS** (2.31) |
| Debian **12** (2.36) | Debian **11** (2.31) |
| Fedora **35+** | openSUSE Leap **15.x** (2.31) |
| Linux Mint **21+**, Pop!_OS **22.04+** | Linux Mint **20.x** (2.31) |
| Arch / Manjaro / openSUSE Tumbleweed (rolling) | |

Out of scope: **non-x86-64** (no ARM / Raspberry Pi build) and **non-Linux**
(Windows/macOS). To support RHEL 8 / Ubuntu 20.04 you would have to pin PySide6 to
≤ 6.9.x and rebuild on `manylinux_2_28`. Node-lock licensing is a separate per-PC
activation step and does not affect distro compatibility.

Qt dlopens a few low-level system libraries that full desktop installs already have.
On a *minimal* install, add them once (the vendor has internet at setup anyway):

```bash
# RHEL / AlmaLinux 9
sudo dnf install -y libxcb xcb-util-cursor xcb-util-keysyms xcb-util-image \
    xcb-util-renderutil xcb-util-wm libxkbcommon-x11 mesa-libGL libglvnd-egl \
    libglvnd-opengl fontconfig freetype glib2 dbus-libs \
    xdg-desktop-portal xdg-desktop-portal-gtk

# Debian / Ubuntu
sudo apt install -y libxcb1 libxcb-cursor0 libxcb-keysyms1 libxcb-image0 \
    libxcb-render-util0 libxcb-icccm4 libxkbcommon-x11-0 libgl1 libegl1 \
    libopengl0 libfontconfig1 libfreetype6 libglib2.0-0 libdbus-1-3 \
    xdg-desktop-portal xdg-desktop-portal-gtk
```

**Native file dialogs (all desktops).** The launcher sets
`QT_QPA_PLATFORMTHEME=xdgdesktopportal` so LabDesk's Open/Save dialogs use each
desktop's own native picker — GTK on GNOME, Plasma on KDE — through
**xdg-desktop-portal**. (PySide6 ships its *own* Qt, so it can't load the system's
KDE/GNOME Qt theme plugins; the portal talks over D-Bus and sidesteps that.) Install
`xdg-desktop-portal` plus a backend: `xdg-desktop-portal-gnome` or
`xdg-desktop-portal-kde` for that desktop's exact look, or `xdg-desktop-portal-gtk`
as a universal one that works everywhere. Most full desktop installs already have
it; without any backend the app silently falls back to Qt's plain built-in dialog.

## Building from source

Requires [`uv`](https://docs.astral.sh/uv/) and a C compiler (`gcc`).

```bash
uv sync                       # dev env (PySide6 + sqlcipher3 + nuitka)
uv run python -m labdesk      # run from source (licensing is NOT enforced in dev)
bash scripts/build_release.sh # PORTABLE build (Docker) -> dist/labdesk-<version>.tar.gz (ship this)
bash scripts/build_app.sh     # quick host build (NOT portable — dev testing only)
```

`build_release.sh` compiles inside the `manylinux_2_34` container so the binary only
needs glibc 2.34 and runs on every supported distro; it requires Docker (daemon
running, your user in the `docker` group). `build_app.sh` does the same compile on
the dev host — fast, but the binary inherits the host's (newer) glibc, so use it only
for local testing, not for shipping.

Both compile the app to a native binary with **Nuitka** in non-bundling mode — Qt and
Python are deliberately NOT included (the per-PC `install.sh` fetches them from PyPI),
keeping the distributable ~2-3 MB. `schema.sql` and `seed.sqlite` (the catalog) are
**baked into the binary** at build time (`scripts/gen_embedded.py`), so they are never
shipped as loose, readable files; at runtime they're materialised to a private,
auto-deleted temp dir only because SQLite opens by path. Only the cosmetic `assets/`
(fonts/logos, which Qt loads by path) ship as files, found via `LABDESK_RESOURCE_DIR`.
The database is encrypted with **SQLCipher** via the self-contained `sqlcipher3-binary`
wheel. `LABDESK_DB_KEY` supplies the passphrase for the headless self-test
(`LABDESK_SELFTEST=1`). The "remember password" feature uses pure-Python `jeepney`.

### Licensing (node-lock)

The app is locked to each machine it is activated for — fully offline, Ed25519-signed.

**1. Set up your signing keys ONCE:**

```bash
uv run python scripts/licensing/generate_keys.py   # embeds the public key in the app
```

This writes the keypair to **`~/Documents/LabDesk-signing-key/`** (one place, outside
the repo) and embeds the public key into the app. Then rebuild
(`bash scripts/build_release.sh`). Keep `~/Documents/LabDesk-signing-key/private.key`
backed up — if you lose it you can't license new machines; **never share it**.

**2. For each customer machine, sign a license** from the activation request they send:

```bash
uv run python scripts/licensing/issue_license.py \
    --request "<token-from-the-lab>" \
    --lab "City Pathology & Health Care" \
    --out CPHC-Lab.lic \
    --days 90
```

- `--request` — the token the app shows (or a path to a file containing it).
- `--lab` — the customer name, recorded in the license.
- `--out` — a bare filename is saved under `~/Documents/LabDesk-signing-key/licenses/`;
  give a full path to put it elsewhere.
- `--days N` — valid N days (e.g. `90` for a quarterly subscription). Omit for a
  perpetual license, or use `--expiry 2027-06-30` for an explicit date.

Send the resulting `.lic` back; the lab loads it (next step).

**3. Where the lab activates:** the activation screen appears automatically at first
launch (it won't let them in until licensed), **and** any time from
**Settings → "License & activation"** — which shows the current status, this
computer's code, and an "Activate / load license…" button to re-activate or renew.

**Tampering & expiry are covered automatically.** The whole license — including the
expiry date and the bound machine — is signed. Editing the expiry (or anything else)
in the `.lic` file breaks the signature and the app rejects it ("license signature is
invalid"). There's also clock-rollback protection: a high-water-mark file means
setting the system clock backwards can't revive an expired license. Copying the app to
another PC fails too (the machine signals don't match). See `src/labdesk/licensing/`.

> **Maintenance TODO:** the runtime is CPython 3.13 (security-fixes-only EOL
> ~Oct 2029). Plan the next interpreter bump before then; moving to 3.14 also
> needs the `pyside6` floor raised in `pyproject.toml`. Because the shipped binary
> is compiled against 3.13, `install.sh` pins `--python 3.13` to stay ABI-matched.

The test catalog the app ships with is baked into `src/labdesk/seed.sqlite`.
It was built once from the old Access system; that one-time migration is done,
so there is nothing to re-migrate. (The original migration scripts and staging
data were retired — the staging DBs live outside the repo under
`../migration_data/` only as an archive.)

## Project layout

```
src/labdesk/        (internal package name)
  app.py            bootstrap (wizard → login → main window) + desktop integration
  __init__.py       single source of the app version (__version__)
  schema.sql        clean normalized schema
  seed.sqlite       catalog the app ships with (706 tests, no branding)
  constants.py      shared pick-lists + phone normalisation
  roles.py          role-based access control (receptionist / technician / admin)
  catalog_render.py classify each test into a printed-report render category
                    (numeric / qualitative / blood_bank / descriptive / obstetric /
                    culture); honours a tests.render_category override
  whatsapp.py       WhatsApp delivery via a self-hosted wuzapi gateway
  db/               SQLite layer split by responsibility: connection (keyed/SQLCipher
                    + unlock/rekey/migrate), _driver (SQLCipher driver alias), crypto,
                    auth, audit, settings, backup, keyvault (system-wallet), patient-id,
                    queries
  report/           receipt + lab-report data/logic, print & PDF API, verification
  render/           native Qt (QPainter→QPdfWriter) PDF + preview — no WeasyPrint
  services/         pure, Qt-free billing math + receipt mutations (unit-testable)
  ui/               one module per screen + setup_wizard, unlock (DB password),
                    style, widgets (toasts)
scripts/
  build_release.sh    compile app → native binary in manylinux_2_34 (glibc-2.34 portable)
  build_app.sh        same compile on the dev host (fast, NOT portable)
  install.sh          per-PC install: uv runtime + binary + menu entry (run by vendor)
  uninstall.sh        remove the app + runtime (keeps patient data)
  check_version.py    assert the version is in sync (pyproject ↔ __init__)
  qa_screens.py       render screenshots of every screen (dev/QA only)
```

The package was split out of the original single-file `db.py` / `report.py` /
`render.py` modules; each package's `__init__` re-exports the former public API, so
`from . import report` / `report.X(...)` keep working unchanged.
