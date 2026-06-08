# Changelog

All notable changes to LabDesk are recorded here.

## Unreleased

### Added
- **Patient ID** (replaces "MR No"): every patient gets a unique id in the form
  `YY-NNN-NN<L>` (e.g. `26-000-43F`) with a trailing **check letter** computed
  from the digits, so a single mistyped digit — or an adjacent transposition —
  is caught before the record is saved. Existing `MR…` ids are left untouched.
- **Editable receipt footer:** the cash-receipt **Remarks** line and bottom
  **footer note** are now lab-editable in *Settings → Receipt footer* (they were
  hard-coded). The report footer line, department band and signatories were
  already editable.
- **Admin preview of a voided bill:** a voided bill stays read-only, but an
  admin can now preview the cancelled receipt (and report, if results exist) on
  screen for reference/audit — nothing that emits or alters it is enabled.

### Changed
- **Lab number format** is now `PREFIX-YYYYMMDD-NNN` (e.g. `LAB-20260608-003`) —
  compact date, hyphen separators. Existing numbers are left as-is.
- **Theme** no longer previews live: choosing Light/Dark applies only when you
  click **Save settings**, so leaving the page without saving never sticks an
  unsaved theme.
- **Cash-receipt heading & logo sizing** tuned (heading smaller; the main logo
  enlarged on both the cash receipt and the lab report).

### Performance
- **Settings save is instant.** The whole form is written in a single
  transaction (was ~30 separate commits) and the app is restyled only when the
  theme actually changed — that restyle, not the DB writes, was the visible stall.
- **Slow admin actions run off the UI thread** — *Back up now*, *Restore*,
  *Verify integrity* and *Clear old logs* no longer freeze the window; the button
  shows a busy label while the work runs.

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
- **Cumulative report history isolation.** The "previous visits" columns on a
  lab report now include only **finalised, non-voided** visits for the same
  patient & test. Pending visits (which rendered an empty dashes column) and
  voided visits (whose cancelled values reappeared) are excluded, and a visit
  with no entered values no longer adds an empty column.
- **Cash receipt:** equal left/right margins (was shifted left).
- **Patient card:** long values (e.g. specimen) word-wrap across two lines
  instead of being clipped to one line — applies to both receipt and report.
- **Reporting date:** never fabricated from "now". The cash receipt (a billing
  document) no longer shows a reporting date at all; the report shows the stored
  reporting date or "—" when results aren't finalised; finalising a
  microbiology/culture result now stamps the receipt's reporting date too.
