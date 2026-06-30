# Security model

Built for a **single-site, trusted-operator** deployment holding medical, financial,
and patient data on a lab's own PCs.

## Authentication

- Passwords hashed with **scrypt** (`scrypt$N$r$p$salt$hash`; legacy sha256 upgraded
  on next login). Constant-time verify; a fixed-cost dummy verify on the user-miss
  path defeats username-enumeration by timing.
- Brute-force **lockout** (`failed_attempts` / `locked_until`), with an exponential
  window that self-heals against a wrong system clock; counter incremented atomically.
- New accounts / resets force a password change on first login.

## Authorization

Role-based (`roles.py`): `receptionist` (2), `technician` (3), `admin` (5); higher
levels subsume lower. Two checks: `can()` / `can_view_page()` drive **widget
visibility** (UX only); **`require(role, capability)`** is the **authoritative** gate
— every privileged `application/` mutation calls it and raises `PermissionError`
regardless of the calling path. Capabilities → min level live in `CAP_MIN_LEVEL`.

> Defence-in-depth — **not** a barrier against someone who already holds the shared
> SQLCipher key and edits the DB directly (see threat model).

## Encryption, licensing, verification

- **At rest:** the whole DB is SQLCipher-encrypted; the connection layer is
  fail-closed (`db/connection.py`, `keyvault.py`, `crypto.py`).
- **Licensing:** offline **Ed25519** verification (vendored RFC-8032 in
  `licensing/_ed25519.py`) bound to a machine fingerprint, resisting copying and
  clock-rollback. Issued by `scripts/licensing/`.
- **Report code:** each finalised report's footer is **HMAC(per-lab key, fingerprint)**
  over its snapshotted content incl. the impression (`report/verify.py`). Re-verified
  against the lab's own DB; altering paper breaks it, forging needs the secret key.
- **Audit trail:** `audit_log` is a rolling **SHA-256 hash chain**
  (`db/audit.py::verify_audit_chain`); `log_audit` never raises (falls back to an
  owner-only file so gaps stay visible).

## Threat model

**Mitigated:** lost/stolen disk (encryption); a low-privilege operator doing
privileged writes (`require()`); tampered printout (HMAC); silent audit edit/deletion
(hash chain); license copying / clock rollback (Ed25519 + fingerprint).

**Known limits (single-site model):** all data, the `users`/role table, and
`audit_log` share **one** SQLCipher passphrase every operator must know — so a
key-holder can edit their own role or rebuild-and-rechain the log undetected, and the
chain head isn't anchored off-DB. Key separation + off-DB anchor (Wave 5 in
[`../DEBT.md`](../DEBT.md)) is required before any multi-terminal / multi-site use.
