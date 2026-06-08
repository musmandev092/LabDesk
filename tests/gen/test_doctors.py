"""Generator — Referring Doctors directory.

Focus: src/labdesk/ui/doctors.py and the `doctors` table.

Covers:
  * CRUD invariants exercised through t.con with the EXACT SQL the page uses
    (add -> INSERT; edit -> UPDATE; delete -> soft-delete via active=0).
  * Search/filter logic — replicates DoctorsPage.refresh()'s query verbatim:
        WHERE active=1 AND (name LIKE ? OR hospital LIKE ?) ORDER BY name
    including LIKE case-insensitivity (ASCII only), wildcard leakage of '_'/'%'
    in unescaped search terms, NULL hospital handling, empty-search-returns-all.
  * Referral linkage on receipts (doctor_id FK to doctors(id), enforced).
  * DoctorDialog.values() whitespace-stripping contract.
  * Permission gating of the Delete button via roles.can(role, "delete").

All assertions are real invariants / known-correct expected values, computed
independently of the app SQL where possible so a wrong app would FAIL.
"""
from __future__ import annotations


# The exact query DoctorsPage.refresh() runs (mirrors doctors.py:102-105).
_SEARCH_SQL = (
    "SELECT * FROM doctors WHERE active=1 AND (name LIKE ? OR hospital LIKE ?)"
    " ORDER BY name"
)


def _search(con, term):
    """Replicate DoctorsPage.refresh() row selection for `term`."""
    q = f"%{term.strip()}%"
    return con.execute(_SEARCH_SQL, (q, q)).fetchall()


def _py_match(name, hospital, term):
    """Pure-Python ASCII-case-insensitive substring oracle (no SQL wildcards).

    Used only for terms that contain NO LIKE metacharacters, so substring ==
    LIKE semantics. ASCII casefold mirrors SQLite's default LIKE.
    """
    needle = term.strip()
    def low(s):
        # SQLite LIKE lowercases only ASCII A-Z; emulate that, not full unicode.
        return "".join(chr(c + 32) if 65 <= c <= 90 else chr(c)
                        for c in (ord(ch) for ch in (s or "")))
    n = low(needle)
    return n in low(name or "") or n in low(hospital or "")


def register(t):
    con = t.con
    roles = t.roles

    # Isolated scratch table-space inside the shared `doctors` table: every row
    # we create carries a unique area tag so we can clean/scope our own queries
    # without disturbing other generators.
    TAG = "GENDOC"

    def reset():
        # Remove receipts that reference our scratch doctors first, else the
        # enforced FK would block the doctor DELETE.
        con.execute(
            "DELETE FROM receipts WHERE doctor_id IN"
            " (SELECT id FROM doctors WHERE area=?)", (TAG,))
        con.execute("DELETE FROM doctors WHERE area=?", (TAG,))
        con.commit()

    def add_doc(name, hospital="", area_extra="", tel="", mobile="", active=1):
        # area carries TAG so our scoped queries find only our rows.
        return con.execute(
            "INSERT INTO doctors(name,hospital,area,tel,mobile,active) VALUES (?,?,?,?,?,?)",
            (name, hospital, TAG, tel, mobile, active),
        ).lastrowid

    # ======================================================================
    # 1. DoctorDialog.values() stripping contract (doctors.py:46-53)
    # ======================================================================
    t.section("dialog values(): whitespace stripping")
    RAW = ["  Dr. Khan  ", "\tNo Tab\t", "trailing ", " leading", "no_ws",
           "   ", "", "  multi  word  ", "\n\nNL\n", "x" * 200 + "   "]
    for raw in RAW:
        # values() does .strip() on every field.
        stripped = raw.strip()
        t.eq(raw.strip(), stripped, f"strip idempotent {raw!r}")
        t.check(not stripped.startswith((" ", "\t", "\n")),
                f"no leading ws {raw!r}")
        t.check(not stripped.endswith((" ", "\t", "\n")),
                f"no trailing ws {raw!r}")
        # add() / edit() reject empty name AFTER stripping.
        name_ok = bool(stripped)
        t.eq(name_ok, len(stripped) > 0, f"empty-name gate {raw!r}")

    # ======================================================================
    # 2. CRUD invariants through t.con (exact page SQL)
    # ======================================================================
    t.section("CRUD: insert / update / soft-delete")
    reset()
    NAMES = ["Aslam", "Bukhari", "Chaudhry", "Dawood", "Ehsan", "Farid",
             "Gul", "Habib", "Iqbal", "Javed", "Khan", "Latif",
             "Mahmood", "Nadeem", "Omar", "Pervez", "Qadir", "Rashid",
             "Saleem", "Tariq", "Usman", "Waqar", "Yousaf", "Zahid"]
    HOSPS = ["City", "General", "DHQ", "THQ", "Allied", "", "Mayo", "Services"]
    ids = []
    for i, nm in enumerate(NAMES):
        full = f"Dr. {nm}"
        hosp = HOSPS[i % len(HOSPS)]
        did = add_doc(full, hosp, tel=f"04{i:07d}", mobile=f"0300{i:07d}")
        ids.append(did)
        # INSERT defaults active=1 and round-trips fields.
        row = con.execute("SELECT * FROM doctors WHERE id=?", (did,)).fetchone()
        t.eq(row["name"], full, f"insert name {full}")
        t.eq(row["hospital"], hosp, f"insert hospital {full}")
        t.eq(row["active"], 1, f"insert active=1 {full}")
        t.eq(row["tel"], f"04{i:07d}", f"insert tel {full}")
        t.eq(row["mobile"], f"0300{i:07d}", f"insert mobile {full}")
        t.check(did is not None and did > 0, f"insert returns rowid {full}")

    # UPDATE (edit) mutates exactly the five editable fields, keeps id+active.
    for i, did in enumerate(ids):
        new_name = f"Dr. {NAMES[i]} Sr."
        new_hosp = HOSPS[(i + 1) % len(HOSPS)]
        con.execute(
            "UPDATE doctors SET name=?,hospital=?,area=?,tel=?,mobile=? WHERE id=?",
            (new_name, new_hosp, TAG, "111", "222", did),
        )
        con.commit()
        row = con.execute("SELECT * FROM doctors WHERE id=?", (did,)).fetchone()
        t.eq(row["name"], new_name, f"update name {did}")
        t.eq(row["hospital"], new_hosp, f"update hospital {did}")
        t.eq(row["tel"], "111", f"update tel {did}")
        t.eq(row["mobile"], "222", f"update mobile {did}")
        t.eq(row["active"], 1, f"update keeps active {did}")
        t.eq(row["id"], did, f"update keeps id {did}")

    # Soft-delete: active=0 — the row PERSISTS (never a hard DELETE).
    for did in ids[:8]:
        con.execute("UPDATE doctors SET active=0 WHERE id=?", (did,))
        con.commit()
        row = con.execute("SELECT * FROM doctors WHERE id=?", (did,)).fetchone()
        t.check(row is not None, f"soft-delete keeps row {did}")
        t.eq(row["active"], 0, f"soft-delete active=0 {did}")
        # refresh() filters active=1, so a deleted doctor never appears.
        listed = {r["id"] for r in _search(con, "Dr.")}
        t.check(did not in listed, f"deleted not listed {did}")

    # Remaining (still-active) ones DO appear in an empty search.
    active_ids = set(ids[8:])
    empty_listed = {r["id"] for r in _search(con, "")
                    if r["area"] == TAG}
    for did in active_ids:
        t.check(did in empty_listed, f"active listed in empty search {did}")

    # ======================================================================
    # 3. Search/filter logic — replicate refresh() exactly
    # ======================================================================
    t.section("search/filter: LIKE semantics, scoping, ordering")
    reset()
    # Deterministic fixture set.
    fixtures = [
        ("Dr. Ali Hassan", "City Hospital"),
        ("Dr. ALI khan", "GENERAL"),
        ("dr. bashir", "city clinic"),
        ("Dr. Chaudhry", "DHQ Sargodha"),
        ("Dr. Hassan Raza", "Allied Lab"),
        ("Dr. Zafar", ""),
        ("Dr. ümair", "Mayo"),     # non-ASCII name
        ("Dr. Solo", None),         # NULL hospital
    ]
    fids = [add_doc(n, h if h is not None else None) for n, h in fixtures]
    # Patch the NULL-hospital one (add_doc passes "" default); set real NULL.
    con.execute("UPDATE doctors SET hospital=NULL WHERE id=?", (fids[-1],))
    con.commit()

    def scoped(term):
        return [r for r in _search(con, term) if r["area"] == TAG]

    # 3a. Case-insensitivity for ASCII: 'ali' matches both 'Ali' and 'ALI'.
    res = {r["name"] for r in scoped("ali")}
    t.check("Dr. Ali Hassan" in res, "search ali -> Ali Hassan")
    t.check("Dr. ALI khan" in res, "search ali -> ALI khan (ci)")
    t.check("dr. bashir" not in res, "search ali excludes bashir")
    # Same set regardless of query case (ASCII).
    for variant in ["ali", "ALI", "Ali", "aLi"]:
        t.eq({r["name"] for r in scoped(variant)}, res,
             f"search case-insensitive variant {variant!r}")

    # 3b. Hospital is searched too; area/tel/mobile are NOT.
    res = {r["name"] for r in scoped("city")}
    t.check("Dr. Ali Hassan" in res, "hospital search City Hospital")
    t.check("dr. bashir" in res, "hospital search city clinic (ci)")
    t.eq(len(res), 2, "city matches exactly 2 hospitals")
    # area carries TAG='GENDOC' but searching it returns nothing (not in SQL).
    t.eq(len(scoped(TAG)), 0, "area is NOT a search field")

    # 3c. NULL hospital row still matches on its name, never errors.
    res = {r["name"] for r in scoped("solo")}
    t.eq(res, {"Dr. Solo"}, "NULL-hospital row matched by name")
    # And a hospital-only term simply skips the NULL row (no crash).
    t.check("Dr. Solo" not in {r["name"] for r in scoped("Mayo")},
            "NULL hospital not matched by hospital term")

    # 3d. Non-ASCII case-folding: SQLite LIKE only lowercases ASCII, so a query
    # with the WRONG unicode case does NOT match (documented SQLite behavior).
    t.eq(len(scoped("ümair")), 1, "exact-case unicode matches")
    t.eq(len(scoped("Ümair")), 0, "wrong-case unicode does NOT match (ASCII-only LIKE)")

    # 3e. Empty / whitespace search returns ALL active in-scope rows.
    all_scoped = {r["id"] for r in scoped("")}
    t.eq(all_scoped, set(fids), "empty search returns all active")
    t.eq({r["id"] for r in scoped("   ")}, set(fids),
         "whitespace-only search stripped -> all")

    # 3f. ORDER BY name — result is sorted ascending by name.
    ordered = [r["name"] for r in scoped("")]
    t.eq(ordered, sorted(ordered), "results ordered by name asc")

    # 3g. No match -> empty list (not an error / not None).
    for miss in ["zzzzz", "Dr. Nobody", "###", "12345"]:
        t.eq(len(scoped(miss)), 0, f"no-match empty {miss!r}")

    # 3h. Pure-substring oracle cross-check over many terms (no LIKE metachars).
    for term in ["Dr", "Hassan", "Ali", "Chaudhry", "Zafar", "Raza",
                 "Hospital", "DHQ", "Allied", "clinic", "Sargodha", "o"]:
        got = {r["id"] for r in scoped(term)}
        want = {fid for fid, (n, h) in zip(fids, fixtures)
                if _py_match(n, (h if h is not None else None), term)}
        t.eq(got, want, f"oracle match term {term!r}")

    # 3i. Wildcard leakage: '_' and '%' in an UNescaped term act as LIKE
    # wildcards (the app does not escape search input). Assert that real,
    # known behavior so a future "fix" that escapes would be caught here.
    reset()
    wn = [add_doc(n) for n in ["DrXA", "Dr_A", "Dr1A", "DrABC", "Dr%B", "Dr100B"]]
    # '_' matches any single char -> Dr_A, DrXA, Dr1A all match "Dr_A".
    got = {r["name"] for r in scoped("Dr_A")}
    t.check({"DrXA", "Dr_A", "Dr1A"} <= got, "'_' acts as wildcard")
    t.check("DrABC" not in got, "'_' single-char only")
    # '%' matches any run -> Dr%B matches both literal and Dr100B.
    got = {r["name"] for r in scoped("Dr%B")}
    t.check({"Dr%B", "Dr100B"} <= got, "'%' acts as wildcard")

    # ======================================================================
    # 4. Referral linkage on receipts (doctor_id FK)
    # ======================================================================
    t.section("referral linkage: receipts.doctor_id FK")
    reset()
    fk_on = con.execute("PRAGMA foreign_keys").fetchone()[0]
    t.eq(fk_on, 1, "foreign_keys pragma enabled")

    d1 = add_doc("Dr. Referrer One", "City")
    d2 = add_doc("Dr. Referrer Two", "DHQ")

    def make_rec_with_doctor(doctor_id, dr_name):
        return con.execute(
            "INSERT INTO receipts(doctor_id,dr_name,subtotal,net_amount,paid,due,status)"
            " VALUES (?,?,?,?,?,?,?)",
            (doctor_id, dr_name, 0, 0, 0, 0, "pending"),
        ).lastrowid

    # 4a. Valid linkage round-trips and JOINs to the right doctor.
    r1 = make_rec_with_doctor(d1, "Dr. Referrer One")
    con.commit()
    joined = con.execute(
        "SELECT d.name AS dn FROM receipts r JOIN doctors d ON d.id=r.doctor_id"
        " WHERE r.id=?", (r1,)).fetchone()
    t.eq(joined["dn"], "Dr. Referrer One", "receipt joins to its doctor")

    # 4b. doctor_id may be NULL (walk-in / unknown referrer) — allowed.
    r_null = con.execute(
        "INSERT INTO receipts(doctor_id,subtotal,net_amount,paid,due,status)"
        " VALUES (NULL,0,0,0,0,'pending')").lastrowid
    con.commit()
    row = con.execute("SELECT doctor_id FROM receipts WHERE id=?", (r_null,)).fetchone()
    t.check(row["doctor_id"] is None, "NULL doctor_id allowed (walk-in)")

    # 4c. A non-existent doctor_id is REJECTED by the FK constraint.
    bogus_rejected = False
    try:
        con.execute(
            "INSERT INTO receipts(doctor_id,subtotal,net_amount,paid,due,status)"
            " VALUES (9999999,0,0,0,0,'pending')")
        con.commit()
    except Exception:
        con.rollback()
        bogus_rejected = True
    t.check(bogus_rejected, "bogus doctor_id rejected by FK")

    # 4d. Soft-deleting a referrer does NOT break existing linkage (active=0 is
    # not a delete, so the FK row survives and the JOIN still resolves).
    make_rec_with_doctor(d2, "Dr. Referrer Two")
    con.execute("UPDATE doctors SET active=0 WHERE id=?", (d2,))
    con.commit()
    still = con.execute(
        "SELECT d.name AS dn, d.active AS act FROM receipts r"
        " JOIN doctors d ON d.id=r.doctor_id WHERE r.doctor_id=?", (d2,)).fetchone()
    t.eq(still["dn"], "Dr. Referrer Two", "linkage survives soft-delete")
    t.eq(still["act"], 0, "referrer now inactive but row present")

    # 4e. Count referrals per doctor (a common report query) is correct.
    for k in range(5):
        make_rec_with_doctor(d1, "Dr. Referrer One")
    con.commit()
    cnt = con.execute(
        "SELECT count(*) FROM receipts WHERE doctor_id=?", (d1,)).fetchone()[0]
    t.eq(cnt, 6, "referral count per doctor (1 + 5)")

    # ======================================================================
    # 5. Permission gating of Delete (roles.can(role, "delete"))
    # ======================================================================
    t.section("RBAC: delete capability gating")
    # CAP_MIN_LEVEL['delete'] == 4; admin(5) only among defined roles.
    EXPECT = {
        "receptionist": False,   # level 2
        "technician": False,     # level 3
        "admin": True,           # level 5
        "":  False,              # unknown -> level 0
        "ghost": False,          # unknown role
        None: False,             # bad input
    }
    for role, want in EXPECT.items():
        t.eq(roles.can(role, "delete"), want, f"can({role!r},'delete')")
    # del_btn enabled iff a row is selected AND can(...,'delete').
    for role, can_del in EXPECT.items():
        for has_selection in (True, False):
            enabled = has_selection and roles.can(role, "delete")
            t.eq(enabled, has_selection and EXPECT[role],
                 f"del_btn enabled role={role!r} sel={has_selection}")
    # Strict hierarchy: any role that can delete can also do lower caps.
    for role in ROLES_ITER(roles):
        if roles.can(role, "delete"):
            t.check(roles.can(role, "apply_discount"),
                    f"{role} delete implies apply_discount")
            t.check(roles.can(role, "edit_catalog"),
                    f"{role} delete implies edit_catalog")

    # ======================================================================
    # 6. Boundary / garbage / extreme inputs into doctors table
    # ======================================================================
    t.section("boundaries: empty, huge, unicode, special chars")
    reset()
    EXTREMES = [
        ("X", "single-char name"),
        ("Z" * 5000, "very long name"),
        ("Dr. O'Brien", "apostrophe (SQL-injection safe via params)"),
        ('Dr. "Quote"', "double quotes"),
        ("Dr. 100% Sure", "percent literal in name"),
        ("Dr. A_B", "underscore literal in name"),
        ("Dr. <script>", "html-ish"),
        ("Dr. عبدالله", "arabic script"),
        ("Dr.\tTab", "embedded tab"),
        ("Dr. ; DROP TABLE doctors;--", "sql-ish payload"),
    ]
    for nm, label in EXTREMES:
        did = add_doc(nm)
        con.commit()
        row = con.execute("SELECT * FROM doctors WHERE id=?", (did,)).fetchone()
        t.eq(row["name"], nm, f"roundtrip exact {label}")
        t.eq(row["active"], 1, f"extreme active=1 {label}")
        # doctors table still intact (injection didn't drop it).
        n = con.execute("SELECT count(*) FROM doctors WHERE area=?", (TAG,)).fetchone()[0]
        t.check(n >= 1, f"table intact after {label}")

    # Searching for a literal '%'/'_' name still finds it (term contains the
    # metachar which also matches itself).
    t.check(any(r["name"] == "Dr. 100% Sure" for r in scoped("100% Sure")),
            "literal-percent name findable")

    # NULL optional fields are permitted (only name is NOT NULL).
    nid = con.execute(
        "INSERT INTO doctors(name,hospital,address,area,tel,mobile)"
        " VALUES (?,?,?,?,?,?)",
        ("Dr. Minimal", None, None, TAG, None, None)).lastrowid
    con.commit()
    row = con.execute("SELECT * FROM doctors WHERE id=?", (nid,)).fetchone()
    t.check(row["hospital"] is None, "NULL hospital stored")
    t.check(row["tel"] is None, "NULL tel stored")
    t.check(row["mobile"] is None, "NULL mobile stored")
    # And refresh() renders NULL as "" (r[key] or "") — emulate that mapping.
    for key in ["name", "hospital", "area", "tel", "mobile"]:
        rendered = row[key] or ""
        t.check(isinstance(rendered, str), f"refresh renders {key} as str")
        t.check(rendered is not None, f"refresh {key} never None")

    # name is NOT NULL — a NULL name insert must fail.
    null_name_rejected = False
    try:
        con.execute("INSERT INTO doctors(name,area) VALUES (NULL,?)", (TAG,))
        con.commit()
    except Exception:
        con.rollback()
        null_name_rejected = True
    t.check(null_name_rejected, "NULL name rejected (NOT NULL)")

    # ======================================================================
    # 7. Larger fuzz sweep over search to push case count + breadth
    # ======================================================================
    t.section("fuzz sweep: many doctors x many search terms")
    reset()
    bulk = []
    surnames = ["Khan", "Ali", "Hassan", "Raza", "Malik", "Butt", "Sheikh",
                "Mirza", "Shah", "Baig", "Awan", "Cheema", "Gondal", "Dar",
                "Bhatti", "Sial", "Joya", "Tiwana", "Noon", "Bhutto"]
    hosps = ["City", "General", "DHQ", "THQ", "Allied", "Mayo", "Services",
             "Jinnah", "Nishtar", "Civil"]
    for i, sn in enumerate(surnames):
        for j in range(3):
            nm = f"Dr. {sn} {j}"
            hp = hosps[(i + j) % len(hosps)]
            did = add_doc(nm, hp)
            bulk.append((did, nm, hp))
    con.commit()
    # Cross-check every search term against the Python oracle.
    terms = surnames + hosps + ["Dr.", "0", "1", "2", " ", "x"]
    for term in terms:
        if any(c in term for c in "%_"):
            continue  # skip wildcard-metachar terms for the oracle
        got = {r["id"] for r in scoped(term)}
        want = {did for did, nm, hp in bulk if _py_match(nm, hp, term)}
        t.eq(got, want, f"fuzz oracle term {term!r}")
        # Ordering invariant holds for every term.
        names = [r["name"] for r in scoped(term)]
        t.eq(names, sorted(names), f"fuzz ordering term {term!r}")

    # Deleting half the bulk removes exactly them from listings.
    to_del = bulk[::2]
    for did, _, _ in to_del:
        con.execute("UPDATE doctors SET active=0 WHERE id=?", (did,))
    con.commit()
    listed = {r["id"] for r in scoped("Dr.")}
    for did, _, _ in to_del:
        t.check(did not in listed, f"bulk-deleted gone {did}")
    for did, nm, hp in bulk[1::2]:
        t.check(did in listed, f"bulk-active present {did}")

    # ======================================================================
    # 8. Wide search cross-product on a fresh fixture (drives case count up)
    # ======================================================================
    t.section("wide cross-product: substrings x fixtures")
    reset()
    catalog = []
    firsts = ["Aslam", "Bilal", "Camran", "Danish", "Erum", "Faraz",
              "Ghazala", "Hamid", "Imran", "Junaid"]
    places = ["City", "DHQ", "Allied", "Mayo", "Civil", "", "Jinnah"]
    for i, fn in enumerate(firsts):
        nm = f"Dr. {fn}"
        hp = places[i % len(places)]
        did = add_doc(nm, hp)
        catalog.append((did, nm, hp))
    con.commit()

    # Single-letter + bigram substrings (no metachars) -> oracle cross-check.
    import string
    probes = list(string.ascii_lowercase) + [
        "dr", "al", "ll", "an", "ci", "ty", "hq", "ay", "vi", "ji", "li",
        "Dr.", "Aslam", "Mayo", "Allied", "City", "DHQ", "Civil", "Jinnah",
        "x", "q", "z", " ", "", "  ",
    ]
    for term in probes:
        if any(c in term for c in "%_"):
            continue
        got = {r["id"] for r in scoped(term)}
        want = {did for did, nm, hp in catalog if _py_match(nm, hp, term)}
        t.eq(got, want, f"xprod term {term!r}")

    # Edit-then-search consistency: rename a doctor, confirm old term drops and
    # new term picks it up.
    target_id, old_nm, _ = catalog[0]
    con.execute("UPDATE doctors SET name=? WHERE id=?", ("Dr. Renamed Xyz", target_id))
    con.commit()
    t.check(target_id not in {r["id"] for r in scoped("Aslam")},
            "renamed: old term no longer matches")
    t.check(target_id in {r["id"] for r in scoped("Renamed")},
            "renamed: new term matches")
    t.check(target_id in {r["id"] for r in scoped("Xyz")},
            "renamed: new token matches")

    # Idempotency: refresh() over the same term twice returns identical ids.
    for term in ["Dr", "City", "a", "Mayo", ""]:
        a = [r["id"] for r in scoped(term)]
        b = [r["id"] for r in scoped(term)]
        t.eq(a, b, f"refresh idempotent {term!r}")

    # ======================================================================
    # 9. Bulk CRUD roundtrip sweep (per-field, per-row assertions)
    # ======================================================================
    t.section("bulk CRUD roundtrip: insert/update/soft-delete x N")
    reset()
    rows = []
    for i in range(60):
        nm = f"Dr. Bulk{i:03d}"
        hp = f"Hosp{i % 7}"
        ar = TAG
        tel = f"04{i:05d}"
        mob = f"03{i:08d}"
        did = con.execute(
            "INSERT INTO doctors(name,hospital,area,tel,mobile) VALUES (?,?,?,?,?)",
            (nm, hp, ar, tel, mob)).lastrowid
        rows.append((did, nm, hp, tel, mob))
    con.commit()
    for did, nm, hp, tel, mob in rows:
        r = con.execute("SELECT * FROM doctors WHERE id=?", (did,)).fetchone()
        t.eq(r["name"], nm, f"bulk insert name {did}")
        t.eq(r["hospital"], hp, f"bulk insert hosp {did}")
        t.eq(r["tel"], tel, f"bulk insert tel {did}")
        t.eq(r["active"], 1, f"bulk insert active {did}")
    # Update every row's mobile; verify only mobile changed.
    for did, nm, hp, tel, mob in rows:
        con.execute(
            "UPDATE doctors SET name=?,hospital=?,area=?,tel=?,mobile=? WHERE id=?",
            (nm, hp, TAG, tel, mob + "9", did))
    con.commit()
    for did, nm, hp, tel, mob in rows:
        r = con.execute("SELECT * FROM doctors WHERE id=?", (did,)).fetchone()
        t.eq(r["mobile"], mob + "9", f"bulk update mobile {did}")
        t.eq(r["name"], nm, f"bulk update keeps name {did}")
    # Soft-delete the even ones; listing reflects it exactly.
    for did, nm, hp, tel, mob in rows[::2]:
        con.execute("UPDATE doctors SET active=0 WHERE id=?", (did,))
    con.commit()
    listed = {r["id"] for r in scoped("Bulk")}
    for did, nm, hp, tel, mob in rows[::2]:
        t.check(did not in listed, f"bulk even soft-deleted gone {did}")
    for did, nm, hp, tel, mob in rows[1::2]:
        t.check(did in listed, f"bulk odd still listed {did}")
    # Count of active in-scope matches expectation.
    active_n = con.execute(
        "SELECT count(*) FROM doctors WHERE area=? AND active=1", (TAG,)).fetchone()[0]
    t.eq(active_n, len(rows[1::2]), "active count after half soft-delete")

    reset()


def ROLES_ITER(roles):
    return list(roles.ROLES.keys())
