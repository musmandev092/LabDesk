# Changelog

All notable changes to LabDesk are recorded here.

## Unreleased

### Security
- **Supply chain:** `appimagetool` is pinned to a tagged release (1.9.0) and
  verified by SHA-256 before use; the build emits a `.sha256` for the AppImage,
  and `install_desktop.sh` verifies it before installing. Removed the unverified
  `repack_xz.sh` micromamba `curl | tar` path.
- **WhatsApp:** warns before saving a plain-`http` gateway URL that points
  anywhere other than this computer (token/PDF would travel unencrypted);
  delivery status is now read from the gateway's JSON reply instead of matching
  English phrases; access-token key removed from default settings (it lives only
  in the `0600` secret file).
- **Access control:** backup/restore is gated behind a new `manage_backups`
  (admin) capability; an idle-locked session unlocked by a *different* user ends
  instead of inheriting the previous user's pages.
- **Data at rest:** `restore` rejects files that aren't a real LabDesk SQLite DB;
  `audit_fallback.log` is `0600`; chosen logos are copied into the `0700` data
  dir rather than referenced from arbitrary paths; legacy non-scrypt password
  hashes are forced to reset (rehash to scrypt) on next login.
- **Privacy/consent:** per-patient "Send reports & bills on WhatsApp" consent in
  Reception (on by default, timestamped); PDF exports are forced to a `.pdf`
  path; stronger temporary-password entropy; gateway URL validated before the
  linking page opens.
- **Docs:** new "Security & data protection" section in the README (trust
  boundary, OS-account/disk-encryption guidance, third-party delivery),
  checksum-verification step, and a CPython 3.12 EOL (Oct 2028) maintenance note.

### Fixed
- **Cash receipt:** equal left/right margins (was shifted left).
- **Patient card:** long values (e.g. specimen) word-wrap across two lines
  instead of being clipped to one line — applies to both receipt and report.
- **Reporting date:** never fabricated from "now". The cash receipt (a billing
  document) no longer shows a reporting date at all; the report shows the stored
  reporting date or "—" when results aren't finalised; finalising a
  microbiology/culture result now stamps the receipt's reporting date too.
