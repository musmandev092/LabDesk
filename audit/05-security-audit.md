# LabDesk Security Audit (Principal Security Engineer)

**Scope:** Authentication, Authorization, Encryption-at-rest, Licensing, Audit logging, plus a whole-tree sweep for injection / unsafe subprocess / deserialization / secrets / file-permission / path-traversal / TOCTOU issues.
**Method:** Read-only static review of `src/labdesk/` (~15.5k LOC), `scripts/licensing/`, `schema.sql`. Evidence cited as `file:line`.
**Date:** 2026-06-16 · **Branch:** `dev`

## Overall posture: **B**

LabDesk is, for a single-site desktop LIS, notably well hardened. The crypto choices are correct (scrypt password KDF, SQLCipher at rest, vendored RFC-8032 Ed25519 with constant-time-ish verify, SHA-256 audit chain), and the code is unusually deliberate about *fail-closed* behavior (refusing to open an unencrypted patient DB, refusing single-signal node-locks, blocking cross-host redirects that would exfiltrate the WhatsApp token + patient PDF). There are **no Critical findings**: no SQL injection, no `eval`/`pickle`/`yaml.load`, no shell-string subprocess, no embedded private key, no hardcoded credentials beyond the documented one-time `admin/admin` bootstrap that is force-reset.

The grade is held at B (not A) by a consistent **architectural gap**: the *real* authorization gate `roles.require()` is enforced for catalog/money mutations in the service layer, but several equally-sensitive mutations — **user creation, role assignment, password reset, enable/disable, result entry, and result finalization** — are gated **only by the Qt UI** (`can()` / page visibility), with the raw `con.execute` write performed directly in the view. Combined with the documented (and unavoidable on a shared-key desktop app) fact that anyone holding the DB passphrase can rewrite any table including `audit_log`, the authorization story is "UX-deep" in places where it should be "service-deep."

---

## Critical / High summary table

| # | Severity | Category | Finding | Location |
|---|----------|----------|---------|----------|
| H1 | **High** | Authorization | User-management & result-entry mutations enforce authz **only in the Qt UI** (`can()`), not in a data-layer `require()` — inconsistent with the `roles.require()` pattern used elsewhere; privilege escalation possible via any non-UI code path / DB edit | `ui/settings.py:448`, `ui/settings.py:473`, `ui/settings.py:777`, `ui/worklist.py:425-485` |
| H2 | **High** | Authorization / Integrity | The audit chain, RBAC role, and all data live in **one SQLCipher DB under a single shared passphrase**. Any authenticated staff member (all of whom must know the DB password to open the app) can edit their own `role`, forge/`rechain` the audit log, or zero `failed_attempts` directly. No server-side trust boundary. | `roles.py:65-77`, `db/audit.py:95-111`, `schema.sql:25` |
| M1 | **Medium** | Audit logging | `rechain_audit()` can rewrite the entire chain to be internally-valid after tampering; the chain head is **not signed/anchored** anywhere outside the same writable DB, so deletion+rechain is undetectable. | `db/audit.py:95-111` |
| M2 | **Medium** | Encryption | SQLCipher is keyed with the raw user passphrase via `PRAGMA key='...'` with **no explicit `kdf_iter` / cipher pinning**; security depends entirely on the linked SQLCipher version's defaults, and KDF params are taken from the (attacker-modifiable) DB header on open. | `db/connection.py:88-93`, `db/_driver.py:24-31` |
| M3 | **Medium** | Authentication | No password complexity policy (min length 6, only blocks literal "admin"); brute-force lockout is **per-username** and resettable, and `must_change_password` enforcement happens **after** a successful `verify_user` already logged "login". | `ui/login.py:139-143`, `db/auth.py:54-73` |
| M4 | **Medium** | Encryption / Key storage | Secret Service ("remember password") uses a **`plain` (unencrypted) D-Bus session**; the DB passphrase crosses the session bus in cleartext, readable by any process in the same session. | `db/keyvault.py:44-56` |
| L1 | **Low** | Licensing | Node-lock + signature are sound, but enforcement keys off `__compiled__`/`sys.frozen` and an env var; the embedded public key + `_signals_match`/`_seen_stamp` are extractable from the binary — defeats casual copying only (by design). | `licensing/__init__.py:54-80,134-153` |
| L2 | **Low** | Disclosure | `audit_fallback.log` and crash logs persist patient names / lab numbers to plaintext files (0600) in the data dir, outside the encrypted DB. | `db/audit.py:18-28`, `app.py:200-209` |

---

## 1. Authentication

### Password hashing — **Good**
`db/crypto.py:17-50`. scrypt with `N=16384, r=8, p=1, dklen=32`, 16-byte random hex salt from `secrets.token_hex` (`_config.py:135`). Self-describing string `scrypt$N$r$p$salt$hash`; verification is constant-time via `hmac.compare_digest` (`crypto.py:46,50`). Legacy SHA-256 rows are still verified and **transparently upgraded to scrypt on next login** (`auth.py:42-46`) and otherwise force-reset (`connection.py:197-201`). Username-enumeration timing is equalised with `_dummy_verify` running a real scrypt on the user-miss path (`auth.py:30`, `crypto.py:56-62`). This is textbook-correct.

> Note: `_SCRYPT_N=16384` is on the low end for 2026 (OWASP suggests N≥2^17 for scrypt). Acceptable for a desktop login, but bump-worthy.

### Brute-force lockout — **Adequate, with caveats (M3)**
`auth.py:54-73`, policy in `_config.py:131-133`. After 5 fails, exponential backoff `60·2^(n-5)` capped at 3600s. Two weaknesses:
- **Per-username only.** A single attacker password-spraying many usernames is never globally throttled, and on a desktop app there are few accounts so this is minor — but there is also no IP/host dimension (N/A for local desktop).
- **Lockout is resettable by any admin and by the user's own first-login flow** — `_reset_user_pw` and `verify_user` success zero `failed_attempts`/`locked_until` (`auth.py:48`, `settings.py:779`). Expected, but combined with H2 (DB write access) the lockout is not a hard control.
- **Login is audit-logged as "login" *before* the forced password change** (`login.py:102` then `:103`), so a `must_change_password` user who cancels the change is denied entry (`login.py:104` returns) yet has already produced a "signed in" audit row. Cosmetic, but it muddies the trail.

### Password reset / first-login — **Good**
Admin reset generates a single-use `Temp-<8 hex>` (32-bit) and sets `must_change_password=1` (`settings.py:775-781`), shown in a copyable non-dismissing dialog (`settings.py:786`). First-login change enforces ≥6 chars and bans literal "admin" (`login.py:139-143`). The 32-bit temp token is fine as a one-time, must-change credential.

**M3 remediation:** enforce a real password policy (length ≥10, reject top-N common passwords), and emit the "login" audit row only *after* any forced password change completes.

### Session handling — desktop-appropriate
There is no server session; the authenticated `user` dict (incl. `role`) is held in `MainWindow` memory (`main_window.py:71`). Idle auto-lock re-prompts and correctly **rebuilds the session if a *different* user unlocks** (`main_window.py:248-265`) — good. The risk is H2: the role string is trusted from the DB row and can be self-edited by anyone with the key.

---

## 2. Authorization

### Model — clean, but two-tier with a gap
`roles.py` defines a strict numeric hierarchy (receptionist=2, technician=3, admin=5) and two enforcement primitives:
- `can()` / `can_view_page()` — **UX only** (drive widget/page visibility), `main_window.py:133`.
- `require()` — **authoritative**, raises `PermissionError` (`roles.py:65-77`).

`require()` is correctly invoked for the money/catalog mutators in the service+query layer: `edit_catalog` (`queries.py:45,72,136`), `receive_payment` (`queries.py:86`), `void_receipt` (`services/receipts.py:27`), `deliver_report` (`services/receipts.py:57`). This is the right pattern.

### H1 — Sensitive mutations gated only in the UI
The following mutations are **not** routed through `require()` and instead do a direct `con.execute` inside the Qt view, guarded only by an early `if not can(...)` return:

- **Create user / assign role:** `settings.py:432-453` (`INSERT INTO users(...)` at `:448`).
- **Enable/disable user:** `settings.py:462-482` (`UPDATE users SET active...` at `:473`).
- **Reset another user's password:** `settings.py:764-786` (`UPDATE users SET pass_hash...` at `:777`).
- **Enter / overwrite patient results:** `worklist.py:425-485` (`INSERT INTO results ...`). The only gate is that the Worklist page is visible at level ≥3 (`roles.py:24`) plus a status-lock check (`worklist.py:433`). There is **no `require("enter_results")`** capability at all — the capability doesn't exist in `CAP_MIN_LEVEL`.
- **Finalize-edit override:** "reported" reports are editable by re-using the unrelated `manage_users` capability as a proxy for "admin" (`worklist.py:308`), which is a confused-deputy code smell.

**Exploit/impact:** Because the authoritative check lives in the widget, *any* code path that reaches these writes without going through that widget — a future refactor, a scripted call, a test helper, or a direct DB session by a logged-in lower-privilege user (every user has the DB key) — performs the privileged write unchecked. A receptionist who can open the SQLCipher file (they must, to use the app) can `UPDATE users SET role='admin' WHERE id=<self>`; nothing in the app prevents or even necessarily audits it. The `require()` pattern was clearly intended to be the universal gate but was not applied to the highest-value table (`users`) or to result entry.

**H1 remediation:** Move every `users`/`results` mutation into the service/query layer behind `require()`; add explicit capabilities `manage_users`, `enter_results`, `finalize_results`. Stop overloading `manage_users` as the admin proxy in `worklist.py:308`. Audit every `users` mutation (creation is logged; toggling/reset are logged; role *changes* via direct SQL are not).

### IDOR — not applicable in the usual sense
Records are addressed by integer PK throughout (`receipt_id`, `parameter_id`), but there is no multi-tenant boundary — it is one lab's data and any logged-in user of sufficient level may read any record by design. No horizontal-privilege bug beyond H1/H2.

---

## 3. Encryption at rest

### SQLCipher usage — **fail-closed, well-instrumented**
`db/_driver.py` imports `sqlcipher3` as `sqlite3` and sets `ENCRYPTION_AVAILABLE`. The connection layer is admirably defensive:
- `_require_encryption()` **raises** rather than silently writing plaintext when the cipher engine is missing (`connection.py:37-45`), unless the explicit dev opt-in `LABDESK_ALLOW_PLAINTEXT=1` is set.
- `_assert_cipher_active()` proves the cipher is actually engaged via `PRAGMA cipher_version` and **aborts** if empty (`connection.py:48-64`) — defends against a stdlib import masquerading as encrypted.
- `verify_passphrase()` fails closed on empty key, plaintext file, or missing engine (`connection.py:106-131`).
- Plaintext→encrypted migration is atomic (`os.replace`) and verifies the encrypted copy opens before destroying the original (`connection.py:267-304`). Rekey takes an OLD-key backup first and verifies the rewrite (`connection.py:232-264`).

This is the strongest part of the codebase.

### Key derivation injection-safety — **safe**
`PRAGMA key='%s'` and `PRAGMA rekey`/`ATTACH ... KEY` inline the passphrase with doubled-single-quote escaping (`connection.py:93,224,257,285`, `_config`-adjacent). PRAGMA cannot be parameterized; the `replace("'", "''")` is correct SQL string escaping and the passphrase never reaches a shell. No injection.

### M2 — No explicit cipher/KDF pinning
Grep confirms **no `PRAGMA kdf_iter`, `cipher_page_size`, `cipher_hmac_algorithm`, or `cipher_compatibility`** anywhere (`connection.py`). The app relies entirely on the linked SQLCipher version's compiled defaults. Two consequences:
1. **Version drift:** if a build links an older/misconfigured SQLCipher (or someone sets a low default), iteration count silently weakens — there is no in-code floor. The `install.sh` hash-pin (per `_driver.py` docstring) mitigates but is out of this audit's tree.
2. **Header-controlled KDF on open:** when opening an *existing* file, SQLCipher reads the KDF salt and (for plaintext-header variants) parameters from the DB header. A backup/restore path (`backup.py:175`, `restore_db`) that accepts an attacker-substituted file could, in principle, supply a header with weakened parameters; `_looks_like_labdesk_db` validates structure but not cipher strength.

**M2 remediation:** explicitly set `PRAGMA cipher_memory_security=ON` and pin `PRAGMA kdf_iter` to a known-strong value (e.g. ≥256000) immediately after `PRAGMA key`, and assert the active `cipher_settings` match expectations in `_assert_cipher_active`.

### M4 — Wallet stores key over a *plain* D-Bus session
`keyvault.py:44-56` opens the Secret Service with `OpenSession('plain', ...)`. The passphrase is then transmitted to/from the wallet as **cleartext bytes over the session bus** (`store_key:88`, `load_key:133`). The docstring acknowledges "the local session bus is already trusted," but any process running in the same user session (a compromised browser extension host, a malicious AppImage, a screen-scraper) can sniff `org.freedesktop.secrets` traffic and recover the master DB passphrase — which unlocks *all* patient data. The file says it "defends a copied DB and other OS accounts," which is true, but the plain session is weaker than the wallet's own encrypted-session (DH) mode that jeepney can negotiate.

**M4 remediation:** use the Secret Service `dh-ietf1024-sha256-aes128-cbc-pkcs7` encrypted session instead of `plain`, so the passphrase is never in cleartext on the bus.

### Secrets kept out of the DB — **good design**
WhatsApp token lives in `.secrets.json` (0600) in the 0700 data dir, deliberately **excluded** from the DB and backups (`paths.py:67-91`, `_config.py:84-85`). `set_secret` uses `os.open(..., O_CREAT|O_TRUNC, 0o600)` then re-`chmod` — created 0600 atomically (`paths.py:86-90`). Minor TOCTOU: if the file pre-exists with looser perms, `O_TRUNC` doesn't tighten them until the trailing `chmod`; window is negligible and the dir is 0700.

---

## 4. Licensing (Ed25519, offline node-lock)

### Signature verification — **correct**
`_ed25519.py` is the RFC-8032 reference implementation, validated against the RFC test vector incl. tamper/wrong-message negatives (`_ed25519.py:168-184`). `verify()` checks `len(public)==32`, `len(signature)==64`, **rejects non-canonical `s` (`s >= q`)** (`_ed25519.py:158`), decompresses points safely, and returns `False` (never raises) on malformed input (`_ed25519.py:144-165`). Standard (non-cofactored) equation `sB == R + hA`. The signed payload is canonical sorted-JSON minus `sig` (`__init__.py:122-126`), shared verbatim with `issue_license.py` — no canonicalization mismatch. **No embedded private key**; only the 32-byte public key is shipped (`__init__.py:42`), and `git ls-files` shows no tracked key/license/secret files.

### Node-lock — **hardened against single-value cloning**
`_signals_match` requires ≥2 bound signals and `max(2, n-1)` to match, so copying one world-readable `/etc/machine-id` cannot pass (`__init__.py:190-203`); the issuer refuses <2-signal licenses (`scripts/licensing/issue_license.py:71-76`). Signals are SHA-256-salted, raw IDs never leave the box (`fingerprint.py:30-31,88-96`).

### Clock-rollback — **mitigated, not unbreakable (L1)**
`_seen_path` high-water mark is HMAC-stamped with the public key so it can't be hand-edited to an earlier date (`__init__.py:134-153`), and `_effective_today = max(today, high_water)` prevents reviving an expired license by setting the clock back (`__init__.py:171-175`). The HMAC key is the *public* key, which is in the binary, so a determined attacker can recompute the stamp — explicitly acknowledged. Enforcement only bites in packaged builds (`is_packaged_build` via `__compiled__`/`sys.frozen`) and cannot be disabled by env there (`__init__.py:62-80`).

**Assessment:** This is a *deterrent* licensing system, appropriate for offline desktop. It correctly resists copying, license editing, and naive clock rollback. It cannot resist a reverse-engineer with the binary (the public key + verify logic are local) — which is inherent to any client-side offline scheme and is documented. **L1, accept as designed.**

---

## 5. Audit logging (SHA-256 hash chain)

### Chain construction — **correct and append-only in normal use**
`log_audit` (`audit.py:31-58`) computes `SHA256(prev_hash | at | user | action | detail)` and inserts it; `verify_audit_chain` recomputes and reports the first divergent id (`audit.py:61-92`). It correctly handles legacy pre-chain NULL rows (skips until the chain "starts," then any NULL = tampering, `audit.py:73-76`). `log_audit` never raises and falls back to an owner-only file on DB failure (`audit.py:53-58`) so a gap stays visible. Inputs are length-capped and `str()`-coerced to avoid injection/throwing (`audit.py:38-40`). Login attempts log the attacker-controlled username into `detail`, not the `username` actor column (`login.py:111-116`) — good anti-log-spoofing hygiene.

### M1 — The chain is forgeable by anyone with the DB key
The chain is **tamper-*evident*, not tamper-*proof***, and only against an attacker who edits rows but doesn't recompute. Three structural weaknesses:
1. **`rechain_audit()` exists in-tree** (`audit.py:95-111`) and recomputes the *entire* chain over current rows, producing a chain that `verify_audit_chain` will accept. Intended for "authorised purge," but it is a ready-made oracle: delete the rows you want gone, call rechain, and the log verifies clean. There is no record of *what* was purged or *who* rechained.
2. **No external anchor.** The chain head (latest hash) is never signed, exported, printed, or written anywhere outside the same writable SQLCipher DB. So full-chain forgery (rewrite all rows + recompute) is undetectable — there is no trusted prior value to compare against.
3. **No per-row signature.** Rows are hash-chained but not MAC'd with a key the staff don't hold; since all users hold the DB key, the chain protects only against accidental/clumsy edits, not malicious staff.

**M1 remediation:** (a) On each launch, export the current chain-head hash to the append-only fallback file (and/or a printed/emailed daily digest) so a later truncation is detectable against an off-DB witness. (b) HMAC the chain with a key NOT stored in the DB (e.g. derived material only the vendor holds, or at least the `.secrets.json` token) so staff can't recompute a valid chain. (c) Audit `rechain` invocations themselves.

---

## 6. Whole-tree sweep

| Class | Result | Evidence |
|-------|--------|----------|
| SQL injection | **None.** All user data is parameterized. Three f-string/`%` SQL spots are safe: `connection.py:374` (`_ensure_columns`) uses hardcoded internal `_EXTRA_COLUMNS` table/column names; `worklist.py:449` interpolates only `?`-placeholders for an `IN()` list; PRAGMA key escaping is correct. | `connection.py:374`, `worklist.py:447-450`, `connection.py:93` |
| Command injection / unsafe subprocess | **None.** Single `subprocess.run` uses a fixed argv list (no `shell=True`, no user input): desktop-cache refreshers (`update-desktop-database`, `kbuildsycoca6`…). | `app.py:172-181` |
| Unsafe deserialization | **None.** No `pickle`/`marshal`/`yaml.load`/`eval`/`exec`. All `.exec()` hits are Qt `QDialog.exec()`. License/secret data parsed with `json.loads` only. | grep clean; `__init__.py:228-232`, `paths.py:73` |
| Hardcoded secrets / embedded keys | **None beyond documented bootstrap.** Only the Ed25519 *public* key is embedded (`__init__.py:42`). Seeded `admin/admin` is a one-time bootstrap force-reset on first login (`connection.py:176-201`). No private key tracked in git. | grep clean |
| Path traversal | **Low.** Backup `restore_db(path)` and `import_asset(src)` copy caller-chosen paths, but the caller is a local file-picker dialog operated by an admin; restore validates the source is a real LabDesk DB before swap (`backup.py:143-209`). `_safe_filename` sanitizes WhatsApp attachment names (`whatsapp.py:288-291`). No web-facing input reaches the filesystem. | `backup.py:175`, `paths.py:49` |
| SSRF / token exfiltration | **Mitigated.** WhatsApp gateway URL is validated (http/https + host), and a custom redirect handler **blocks cross-host and https→http-downgrade redirects** that would leak the token + base64 patient PDF (`whatsapp.py:73-102`). Non-local gateways trigger a warning (`whatsapp.py:176-193`). Caption templating deliberately avoids `str.format` to prevent `{x.__class__}` reaching internals (`whatsapp.py:54-65`). Good. | `whatsapp.py:73-102,147-160` |
| TOCTOU | **Low.** `set_secret` O_CREAT|O_TRUNC then chmod (negligible window in 0700 dir, `paths.py:86`); `_harden_perms` best-effort. Backup safety-copy de-dups by timestamp loop (`backup.py:193-197`). No exploitable race found. | `paths.py:86-90` |
| Plaintext PII leakage (L2) | `audit_fallback.log` and crash logs write patient names / lab numbers to plaintext 0600 files outside the encrypted DB. Acceptable trade for a visible audit gap, but worth noting for a medical-data product. | `audit.py:18-28`, `app.py:200-209` |

---

## Prioritized remediation

1. **(H1)** Route all `users` and `results` mutations through `roles.require()` in the service/query layer with dedicated capabilities (`manage_users`, `enter_results`, `finalize_results`); audit role changes. Stop using `manage_users` as the admin proxy in `worklist.py:308`.
2. **(H2/M1)** Anchor the audit chain off-DB (export head hash at launch + HMAC with a non-staff key) and audit `rechain_audit`. Document the shared-key trust boundary prominently.
3. **(M2)** Pin SQLCipher KDF iterations and cipher settings explicitly after `PRAGMA key`; assert them in `_assert_cipher_active`.
4. **(M4)** Switch the Secret Service to an encrypted (DH) session instead of `plain`.
5. **(M3)** Add a real password policy and move the "login" audit row to after forced password change.
6. **(L1/L2)** Accept licensing as a designed deterrent; consider scrubbing PII from fallback/crash logs or encrypting them.
