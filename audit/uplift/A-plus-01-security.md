# LabDesk Security Uplift Plan — From B to A/A+

**Dimension:** Security · **Current grade:** B · **Target:** A (table-stakes) → A+ (stretch)
**Author:** Security uplift pass · **Date:** 2026-06-16 · **Branch:** `dev`
**Grounding:** `audit/05-security-audit.md` (read in full) + confirmed source reads of `roles.py`, `ui/reception.py`, `ui/worklist.py`.
**Scope rule:** PLANNING ONLY. No source/test/config files modified. The only file written is this report.

---

## 0. Executive summary

The B grade is correct and well-earned: crypto primitives are right (scrypt KDF, SQLCipher at rest, RFC-8032 Ed25519, SHA-256 audit chain), the connection layer fails closed, and the whole-tree sweep found **no Critical** injection/deserialization/secret findings. The grade is held below A by **one systemic class of defect**: the *authoritative* authorization gate `roles.require()` (`roles.py:65-77`) is applied to lesser money/catalog mutations but **bypassed for the three highest-stakes write paths** — bill creation (`ui/reception.py:save` ~627), result entry/finalization (`ui/worklist.py:425`, `ui/microbiology.py:237`), and all `users` table mutations (`ui/settings.py:448,473,777`) — which instead run multi-table transactions inline in Qt widgets gated only by UX-level `can()`. This is textbook **CWE-862 Missing Authorization** / **CWE-863 Incorrect Authorization** (both on the 2024 CWE Top 25) and a direct **OWASP ASVS V8 Authorization** failure.

Secondary gaps that block A+: single shared SQLCipher passphrase covers data + RBAC + audit (no key separation), the audit chain has no off-DB anchor (forgeable via `rechain_audit()`), no documented threat model, and no SAST / dependency-scanning CI gate.

**A is achievable** by closing H1 (service-boundary authz) + H2/M1 partial (off-DB audit anchor + audit-key separation) + adding SAST/dep-scan CI gates + a written threat model. **A+** additionally requires ASVS L2 self-verified-clean, WORM/notarized audit anchoring, and full crypto-config pinning with assertions.

---

## 1. The A+ bar for a healthcare desktop LIS — researched definition

### 1.1 Which standard, which level

| Standard | What it governs | Target for LabDesk |
|---|---|---|
| **OWASP ASVS 5.0** | App security verification, leveled L1/L2/L3 | **L2** is the bar. L2 "maps most cleanly onto regulated industries including healthcare" and covers "regulated or business-critical data" ([SecureCodingHub](https://www.securecodinghub.com/blog/owasp-asvs-developers-complete-guide)). **L3** is reserved for systems where breach is *catastrophic / causes physical harm* (life-support, critical infrastructure). A single-site results/billing LIS that does not drive a device is correctly **L2**; selectively adopt L3 controls (key separation, full audit integrity) as A+ stretch. |
| **OWASP Top 10 (2021)** | Risk classes | A01 Broken Access Control is LabDesk's live risk (H1). A02 Cryptographic Failures, A09 Logging/Monitoring Failures are partially open (M1/M2/M4). |
| **CWE Top 25 (2024)** | Most dangerous weaknesses | **CWE-862 Missing Authorization** and **CWE-863 Incorrect Authorization** both rank in the 2024 Top 25 ([CISA](https://www.cisa.gov/news-events/alerts/2024/11/20/2024-cwe-top-25-most-dangerous-software-weaknesses)) — H1 maps directly. CWE-284 Improper Access Control also applies. |
| **NIST SP 800-63B Rev.4 (Jul 2025)** | Authentication / memorized secrets | Single-factor passwords **SHALL be ≥15 chars**; verifiers SHOULD allow ≥64; compare against a **breach/blocklist**; **rate-limit to ≤100 consecutive failed attempts**; salt ≥32 bits + approved hashing; *optionally* a keyed hash ("pepper") with the key in a hardware-protected area ([NIST 800-63B](https://pages.nist.gov/800-63-4/sp800-63b.html)). |
| **HIPAA Security Rule §164.312** | Technical safeguards for ePHI | **Access Control** (unique user ID, automatic logoff, encryption/decryption), **Audit Controls**, **Integrity** (mechanism to authenticate ePHI / detect improper alteration), **Person/Entity Authentication**, **Transmission Security** ([HHS / Accountable](https://www.accountablehq.com/post/hipaa-security-rule-technical-safeguards-the-complete-requirements-list-45-cfr-164-312)). |
| **IEC 62304** | Medical device SW lifecycle | If LabDesk is ever classed as a medical device, it is likely **Class A/B**; mandates **SOUP** (Software of Unknown Provenance) inventory with version/source/verification rationale and cybersecurity hazard consideration ([SecurityCompass](https://www.securitycompass.com/blog/iec-62304-medical-software-lifecycle/)). Treat as stretch documentation discipline. |
| **NIST SP 800-92 / tamper-evident logging** | Audit log integrity | Hash-chain + **periodic notarization/anchoring to an external trusted location**; store only digests externally, never raw PII ([DesignGurus](https://www.designgurus.io/answers/detail/how-do-you-design-tamperevident-audit-logs-merkle-trees-hashing), [Cossack Labs](https://www.cossacklabs.com/blog/audit-logs-security/)). |

### 1.2 The five A+ acceptance pillars (per task brief), made concrete for LabDesk

1. **Every mutation authorized at an audited boundary.** No `con.execute(INSERT/UPDATE/DELETE …)` on `users`, `results`, `receipts`, `payments`, `bills` lives in a `ui/` widget. Each goes through a `services/`-layer function that calls `roles.require(role, capability)` *then* `log_audit(...)` in the same transaction. ASVS V8: "enforce access control on a trusted service layer."
2. **Key separation.** The audit chain is MAC'd / the audit-integrity key and (ideally) the RBAC trust anchor are NOT derivable solely from the shared DB passphrase that every operator holds.
3. **Tamper-evident, off-DB-anchored audit chain.** Chain head exported to an append-only/WORM witness on each launch; `rechain_audit()` invocations themselves audited; full-chain forgery detectable against the external witness.
4. **Documented threat model.** STRIDE-per-element over a DFD with the trust boundary (shared-key desktop) drawn explicitly; checked into the repo.
5. **SAST + dependency scanning in CI, build-failing.** `bandit` (Python SAST), `pip-audit`/`uv audit` (dependency CVEs), `semgrep` (taint/cross-file + custom rules e.g. "no raw `con.execute` write in `ui/`"). 0 high/critical to merge.

### 1.3 Measurable A / A+ thresholds

| Criterion | A (table-stakes) | A+ (stretch) |
|---|---|---|
| Authz coverage of mutations | 100% of `users`/`results`/`receipts`/`payments` writes behind `require()` at a service boundary | + automated semgrep rule forbidding write SQL in `ui/`, enforced in CI |
| Audit boundary | Every privileged mutation emits an audit row in the same txn | + role *changes* and `rechain` invocations audited; audit write failure surfaces a UI alert |
| ASVS level | L2 self-assessment, all V8 Authorization + V2 Authentication "must" items met | L2 fully green; selected L3 audit-integrity & key-mgmt items met |
| Password policy (800-63B) | ≥12 char min + breach blocklist (top-N) + login-audit after forced change | ≥15 char single-factor min, ≤100-attempt rate-limit, pepper |
| Crypto pinning | `kdf_iter`, `cipher_compatibility`, `cipher_memory_security` pinned + asserted post-`PRAGMA key` | + assert `cipher_provider_version` floor; reject header KDF below floor on restore |
| Audit integrity | Off-DB head anchor exported per launch | HMAC chain with non-staff key + WORM/append-only witness or daily signed digest |
| Key separation | Distinct audit-integrity key not in DB | Distinct RBAC trust anchor; consider OS keyring/HSM-class storage |
| Secret transport | Secret Service over encrypted (DH) session, not `plain` | + scrub PII from `audit_fallback.log` / crash logs or encrypt them |
| CI security gates | bandit + pip-audit fail build on high/critical | + semgrep custom rules, SARIF upload, SBOM/SOUP inventory |
| Threat model | STRIDE DFD doc in repo | Reviewed each release; abuse-case tests for top threats |

---

## 2. Current-state mapping (evidence)

| A+ pillar | LabDesk today | Evidence | Status |
|---|---|---|---|
| Mutations at audited boundary | Money/catalog mutations OK; `users`, `results`, bill creation NOT | `services/receipts.py:27,57` (good) vs `ui/reception.py:~627`, `ui/worklist.py:425`, `ui/microbiology.py:237`, `ui/settings.py:448,473,777` (bad) | **FAIL (H1)** |
| `enter_results`/`finalize`/`manage_users` capabilities exist | No `enter_results` capability; `manage_users` overloaded as admin proxy | `roles.py` `CAP_MIN_LEVEL`, `ui/worklist.py:308` | **FAIL (H1)** |
| Key separation | Single shared passphrase = data + RBAC + audit | `roles.py:65-77`, `db/audit.py:95-111`, `schema.sql:25` | **FAIL (H2)** |
| Off-DB audit anchor | None; `rechain_audit()` recomputes whole chain, unaudited | `db/audit.py:95-111` | **FAIL (M1)** |
| Crypto config pinning | No `kdf_iter`/`cipher_*` pinned; relies on linked defaults | `db/connection.py:88-93`, `db/_driver.py:24-31` | **PARTIAL (M2)** |
| Secret transport | Secret Service over `plain` D-Bus session | `db/keyvault.py:44-56` | **PARTIAL (M4)** |
| Password policy | min 6 chars, blocks literal "admin" only; login audited before forced change | `ui/login.py:139-143`, `db/auth.py:54-73` | **PARTIAL (M3)** |
| Threat model doc | Not present | repo (no `docs/threat-model*`) | **FAIL** |
| SAST / dep-scan CI | Not present (CI exists per commit `82b5740`) | `.github/workflows/` (verify) | **FAIL** |
| Injection / deserialization / secrets | Clean | audit §6 | **PASS** |
| Encryption-at-rest fail-closed | Strong | `db/connection.py:37-64,106-131` | **PASS** |
| Licensing (Ed25519 node-lock) | Sound deterrent, accept as designed | `licensing/__init__.py` | **PASS (L1 accept)** |

---

## 3. Gap-closing plan (ordered)

> Effort S≈≤0.5d, M≈1-2d, L≈3-5d. Each step names exact files and the standard it satisfies. Steps 1-5 are **table-stakes for A**; 6-10 are **A+ stretch**.

### Step 1 — Route `users` mutations through a `services/users.py` boundary behind `require()`  *(A)*
- **Files:** new `src/labdesk/services/users.py`; refactor callers `ui/settings.py:432-453` (create/role), `:462-482` (enable/disable), `:764-786` (password reset). Add capabilities `manage_users`, `assign_role` to `roles.py` `CAP_MIN_LEVEL`.
- Each function: `roles.require(actor_role, cap)` → mutate → `log_audit(...)` (esp. **role changes**, currently unaudited per audit §2 H1) in one transaction.
- **Effort M · Risk Med · Impact High** · Satisfies: ASVS V8 Authorization (trusted service layer), CWE-862/863, HIPAA §164.312(a) Access Control + (b) Audit Controls.

### Step 2 — Move result entry/finalization to `services/results.py` with `enter_results`/`finalize_results` capabilities  *(A)*
- **Files:** new `src/labdesk/services/results.py`; refactor `ui/worklist.py:425-485` (`save_results`) and `ui/microbiology.py:237`. Add `enter_results`, `finalize_results` to `CAP_MIN_LEVEL` (the `enter_results` capability does not exist today). **Remove the `manage_users`-as-admin-proxy** at `ui/worklist.py:308`.
- **Effort L · Risk Med · Impact High** · Satisfies: ASVS V8, CWE-863 (confused-deputy), HIPAA Integrity §164.312(c) (authenticate who altered ePHI).

### Step 3 — Move bill/payment creation to a `services/billing` boundary behind `require()`  *(A)*
- **Files:** `ui/reception.py:save` (~627) multi-table txn → `services/billing.py` (already hosts the money math at `services/billing.py:15`) or `services/receipts.py`. Gate with `create_bill` capability + audit; keep the existing discount-approval logic (`ui/reception.py:638`) but enforce it server-side too.
- **Effort L · Risk Med · Impact High** · Satisfies: ASVS V8, key systemic finding in brief, HIPAA Access/Audit Controls.

### Step 4 — Add SAST + dependency-scanning CI gates  *(A)*
- **Files:** `.github/workflows/*.yml` (existing CI), new `.bandit`/`pyproject.toml [tool.bandit]`, `.semgrep.yml`.
- **Recommend (do not install now):** `bandit` (Python SAST, ~15s scans, low FP, standard for Python CI ([Semgrep blog](https://semgrep.dev/blog/2021/python-static-analysis-comparison-bandit-semgrep/))); `pip-audit` or `uv audit` (dependency CVEs); `semgrep` (cross-file taint + a **custom rule banning write-SQL `con.execute("INSERT/UPDATE/DELETE …")` inside `src/labdesk/ui/**`** — this is the regression guard for Steps 1-3). Gate: **0 high/critical to merge**; upload SARIF.
- **Effort M · Risk Low · Impact High** · Satisfies: OWASP Top 10 proactive controls, IEC 62304 SOUP discipline, brief's SAST/dep-scan requirement.

### Step 5 — Off-DB audit-chain anchor + audit `rechain` + key-separated MAC  *(A, partial → A+)*
- **Files:** `db/audit.py:31-58` (log), `:61-92` (verify), `:95-111` (`rechain_audit`), `app.py` launch path, `db/keyvault.py`/`paths.py` (for the separate key).
- (a) On each launch, append the current chain-head hash + timestamp to an **append-only off-DB witness** (the existing `audit_fallback.log` location, or a separate `audit-anchor.log`, 0600) so later truncation is detectable. (b) **Audit every `rechain_audit()` invocation** (who/when/row-count-before/after). (c) **HMAC each row / the chain with a key NOT stored in the DB** (e.g. material in `.secrets.json`, which is already excluded from DB+backups per `paths.py:67-91`) so a staff member with only the DB key cannot forge a valid chain.
- **Effort M · Risk Med · Impact High** · Satisfies: HIPAA §164.312(b) Audit Controls + (c) Integrity, NIST SP 800-92, tamper-evident-log anchoring guidance.

### Step 6 — Pin SQLCipher KDF/cipher settings and assert them  *(A+)*
- **Files:** `db/connection.py:88-93` (after `PRAGMA key`), `:48-64` (`_assert_cipher_active`), `db/_driver.py`.
- Set `PRAGMA cipher_compatibility = 4`, `PRAGMA kdf_iter = 256000` (SQLCipher 4 default; pin so a weaker linked build cannot silently lower it), `PRAGMA cipher_memory_security = ON` ([Zetetic](https://www.zetetic.net/sqlcipher/sqlcipher-api/)). Assert these in `_assert_cipher_active`; on **restore** (`backup.py:175`) reject a header whose KDF is below the floor.
- **Effort M · Risk Med · Impact Med** (memory_security has perf cost — measure) · Satisfies: OWASP A02 Crypto Failures, ASVS V6 Cryptography, defense vs M2 header-KDF substitution.

### Step 7 — Switch Secret Service to encrypted (DH) session  *(A+)*
- **Files:** `db/keyvault.py:44-56` (`OpenSession('plain', …)` → `dh-ietf1024-sha256-aes128-cbc-pkcs7`), `:88`/`:133` (encrypt/decrypt secret with negotiated key).
- **Effort M · Risk Med · Impact Med** · Satisfies: HIPAA §164.312(e) Transmission Security (no cleartext master passphrase on the session bus), ASVS V6.

### Step 8 — Strengthen password policy to 800-63B Rev.4  *(A+)*
- **Files:** `ui/login.py:139-143` (min length → **≥15** single-factor; add a bundled **top-N breached/dictionary blocklist** check incl. service/username derivatives), `db/auth.py:54-73` (cap at **≤100 consecutive** failed attempts; consider a pepper with key outside the DB), and move the `"login"` audit row to **after** any forced password change (`ui/login.py:102-104`). Optionally bump `_SCRYPT_N` from 16384 toward 2^17 per `db/crypto.py` (audit note line 35).
- **Effort M · Risk Low · Impact Med** · Satisfies: NIST SP 800-63B Rev.4 memorized-secret requirements, HIPAA §164.312(d) Authentication.

### Step 9 — Write and commit a STRIDE threat model  *(A+)*
- **Files:** new `docs/security/threat-model.md` + DFD (OWASP Threat Dragon / draw.io export). Draw the **shared-key desktop trust boundary** explicitly (every operator holds the DB key — the core H2 reality), enumerate STRIDE per element (login, SQLCipher store, audit chain, WhatsApp gateway, license/fingerprint, backup/restore), map each to the mitigations above, and record residual/accepted risks (L1 licensing, L2 plaintext fallback PII).
- **Effort M · Risk Low · Impact Med** · Satisfies: OWASP Threat Modeling, ASVS V1 (architecture/threat model), IEC 62304 risk discipline.

### Step 10 — Backfill security tests for the trust-critical, 0%-coverage paths  *(A+)*
- **Files:** new tests under `tests/` for `db/audit.py:61` (verifier incl. tamper/rechain negatives + off-DB anchor mismatch), `report/verify.py:44` (HMAC), `services/billing.py:15` (money math), and **authz-bypass abuse-case tests** asserting a low-privilege role gets `PermissionError` from the new `services/users.py`/`results.py`/`billing` functions (regression guard for Steps 1-3). These three trust features currently have **0% coverage** (brief).
- **Effort L · Risk Low · Impact High** · Satisfies: ASVS verification evidence, IEC 62304 verification, OWASP A09.

### Optional — L2/L3 stretch: scrub or encrypt fallback/crash PII *(A+ polish)*
- **Files:** `db/audit.py:18-28`, `app.py:200-209`. Redact patient names/lab numbers (hash or omit) from `audit_fallback.log` and crash logs, or encrypt them. (L2 finding — accept-as-designed today, but a medical-data polish item.)
- **Effort S · Risk Low · Impact Low** · Satisfies: HIPAA minimum-necessary, OWASP A09 sensitive-data-in-logs.

---

## 4. Recommended tooling (recommendations only — not installed)

| Tool | Purpose | Rationale / source |
|---|---|---|
| **bandit** | Python SAST in CI | Standard for Python, fast (~15s), low memory, catches weak crypto/hardcoded secrets ([Semgrep blog](https://semgrep.dev/blog/2021/python-static-analysis-comparison-bandit-semgrep/)) |
| **pip-audit** (or `uv audit`) | Dependency CVE scanning | Covers runtime deps bandit misses; pair the two for full coverage ([dev.to comparison](https://dev.to/rahulxsingh/semgrep-vs-bandit-python-security-scanning-compared-2026-5e5j)) |
| **semgrep** | Cross-file taint + custom org rules | Custom rule to **ban write-SQL in `ui/`** = the durable guard for Steps 1-3; SARIF + PR comments + build-block ([semgrep.dev](https://semgrep.dev/)) |
| **OWASP Threat Dragon** | DFD / STRIDE threat model authoring | Free OWASP tool for Step 9 ([OWASP](https://owasp.org/www-community/Threat_Modeling_Process)) |
| **cyclonedx-py / syft** | SBOM / SOUP inventory | IEC 62304 SOUP documentation + supply-chain visibility |
| (existing) **scrypt / SQLCipher / Ed25519** | Keep | Already correct per audit §1,3,4 — do not replace |

---

## 5. Honest grade trajectory

- **B → A** requires Steps 1-5 (service-boundary authz on the three hot paths + users; off-DB audit anchor with a key staff don't hold; SAST/dep-scan CI gate) plus a written threat model (Step 9). These close the single systemic A01/CWE-862 defect that holds the grade and satisfy ASVS L2 V8 + HIPAA Access/Audit Controls.
- **A → A+** requires Steps 6-8, 10, and the L2/L3 polish: full crypto-config pinning with assertions, encrypted Secret Service session, 800-63B-Rev.4 password policy, and tests on the 0%-coverage trust paths — i.e., a self-verified-clean ASVS L2 with selected L3 audit-integrity/key-management controls.

**Caveat (be honest):** On a shared-key single-binary desktop app, an operator who holds the DB passphrase can always edit any table directly — `require()` and the audit chain are **defense-in-depth and tamper-evidence, not a hard server boundary** (acknowledged in `roles.py:require` docstring and audit H2). True tamper-*proofing* would need a server/HSM the operator can't reach; that is out of scope for this product shape and should be stated as an accepted residual risk in the threat model (Step 9), not papered over.

---

## 6. Key sources

- OWASP ASVS 5.0 levels (L2 = healthcare/regulated): https://www.securecodinghub.com/blog/owasp-asvs-developers-complete-guide
- OWASP ASVS project (official): https://owasp.org/www-project-application-security-verification-standard/
- 2024 CWE Top 25 (CWE-862/863 Missing/Incorrect Authorization): https://www.cisa.gov/news-events/alerts/2024/11/20/2024-cwe-top-25-most-dangerous-software-weaknesses
- NIST SP 800-63B Rev.4 (memorized secrets, ≥15 char, rate-limit, salt+hash): https://pages.nist.gov/800-63-4/sp800-63b.html
- HIPAA §164.312 technical safeguards: https://www.accountablehq.com/post/hipaa-security-rule-technical-safeguards-the-complete-requirements-list-45-cfr-164-312
- IEC 62304 + SOUP: https://www.securitycompass.com/blog/iec-62304-medical-software-lifecycle/
- SQLCipher API / PRAGMA hardening (kdf_iter 256000, cipher_memory_security, cipher_compatibility): https://www.zetetic.net/sqlcipher/sqlcipher-api/
- Tamper-evident audit logs / off-system anchoring: https://www.designgurus.io/answers/detail/how-do-you-design-tamperevident-audit-logs-merkle-trees-hashing
- Cryptographically signed tamper-proof audit logs: https://www.cossacklabs.com/blog/audit-logs-security/
- OWASP Threat Modeling Process: https://owasp.org/www-community/Threat_Modeling_Process
- bandit vs semgrep (Python SAST in CI): https://semgrep.dev/blog/2021/python-static-analysis-comparison-bandit-semgrep/
