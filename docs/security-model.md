# Security model

LabDesk holds sensitive medical, financial, and patient data on a lab's own PCs. The
security posture is built for a **single-site, trusted-operator** deployment.

## Authentication

- Passwords hashed with **scrypt** (`pass_hash` = `scrypt$N$r$p$salt$hash`; legacy
  sha256 hashes are upgraded on next successful login). Verification is constant-time.
- Failed-attempt **lockout** (`failed_attempts` / `locked_until`).
- New staff and password resets force a change on first login
  (`must_change_password`).

## Authorization

Role-based, defined in `src/labdesk/roles.py`. Three roles with numeric levels:
`receptionist` (2), `technician` (3), `admin` (5). Higher levels subsume lower.

Two checks, with different jobs:

- `can()` / `can_view_page()` — drive **widget visibility** (UX only).
- **`require(role, capability)`** — the **authoritative** gate. Every privileged
  service mutation calls it and raises `PermissionError` if the role lacks the
  capability, regardless of which code path reached the mutator.

Capabilities → minimum level live in `CAP_MIN_LEVEL` (e.g. `create_receipt`:2,
`finalize_results`:3, `void_receipt`:4, `manage_users`:5,
`edit_finalized_results`:5).

> This is defence-in-depth, **not** a barrier against someone who already holds the
> shared SQLCipher key and edits the DB directly. See "Threat model" below.

## Encryption at rest

The entire database is SQLCipher-encrypted; the connection layer is **fail-closed**
(refuses a plaintext fallback). Key derivation and storage are handled in
`db/connection.py` / `db/keyvault.py` / `db/crypto.py`.

## Licensing

Offline **Ed25519** signature verification (vendored RFC-8032 implementation in
`licensing/_ed25519.py`) bound to a machine fingerprint (`licensing/fingerprint.py`),
resisting copying and clock-rollback. Issued/verified by `scripts/licensing/`.

## Report verification code

Each finalised report carries a short footer code = **HMAC(per-lab key, fingerprint)**
over the receipt's snapshotted content (`report/verify.py`). The lab re-verifies a
presented printout against its own DB; altering any value on paper breaks the code,
and forging one needs the lab's secret key.

## Audit trail (tamper-evident)

`audit_log` is a rolling **SHA-256 hash chain**: each row hashes
`(prev_hash, at, user, action, detail)`, so any later edit or deletion is detectable
(`db/audit.py::verify_audit_chain`). `log_audit` never raises — on DB failure it
appends to an owner-only fallback file so the gap stays visible. An authorised purge
re-chains (`rechain_audit`).

## Threat model (summary)

**In scope / mitigated:** lost/stolen disk (encryption at rest); a low-privilege
operator performing privileged writes (service-layer `require()`); tampered printed
report (HMAC verify); silent edit/deletion of the audit log (hash chain); license
copying / clock rollback (Ed25519 + fingerprint).

**Known limitations (single-site model):** all data, the RBAC `users`/role table, and
the `audit_log` share **one** SQLCipher passphrase that every operator must know — so a
key-holder can edit their own role or rebuild-and-rechain the log undetected; and the
chain head is not yet anchored off-DB. Hardening these (key separation + off-DB anchor)
is the **Wave 5** security-depth work tracked in [`../DEBT.md`](../DEBT.md) and the A+
masterplan; do it before any multi-terminal / multi-site deployment.
