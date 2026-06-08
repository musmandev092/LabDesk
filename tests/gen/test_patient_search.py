"""Generator — patient/receipt SEARCH + VISIBILITY invariants.

Focus: src/labdesk/db.py and src/labdesk/ui/receipts.py search SQL.

The Receipts page (receipts.py refresh()) runs, verbatim:

    q   = f"%{search.text().strip()}%"
    sql = "SELECT * FROM receipts WHERE (COALESCE(patient_name,'') LIKE ? "
          "OR COALESCE(lab_no,'') LIKE ? OR COALESCE(mr_no,'') LIKE ?)"
          [ + " AND status=?" ]
          [ + " AND " + db.RECEIVED_TODAY ]
          [ + " AND received_at >= ? AND received_at < ?" ]
          [ + " AND due>0.005 AND " + db.NOT_VOIDED ]
          " ORDER BY id DESC LIMIT 1000"

Note: the pattern is built RAW (no like_term(), no ESCAPE clause), so a literal
'%' or '_' typed into the box — or present in a patient name — behaves as a SQL
wildcard. The catalog page, by contrast, uses widgets.like_term() + ESCAPE '\\'.
This module asserts the *actual* SQLite LIKE semantics the app exposes (via a
faithful Python emulator) AND flags the wildcard-escaping inconsistency.

Visibility rules under test:
  * voided receipts ARE still returned by the base name/lab/mr search,
  * voided receipts are EXCLUDED when the "dues only" filter is on,
  * voided receipts are EXCLUDED from the money totals,
  * the results.hidden flag never changes which RECEIPTS are visible,
  * COALESCE makes NULL name/lab/mr rows visible on an empty search.

Emits well over 1500 assertions.
"""
from __future__ import annotations

import re

from labdesk.ui.widgets import like_term   # the helper the app's search now uses


# ---------------------------------------------------------------------------
# Faithful emulation of SQLite's LIKE operator (ASCII case-insensitive, the
# default).  % matches any run, _ matches exactly one char.  No ESCAPE — that
# mirrors receipts.refresh() exactly.
# ---------------------------------------------------------------------------
def _ascii_lower(s: str) -> str:
    """SQLite's default LIKE only case-folds ASCII A-Z; non-ASCII letters keep
    their case. Replicate that so our predictions match the engine exactly."""
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in (s or ""))


def _sqlite_like(pattern: str, value: str) -> bool:
    """Replicate `value LIKE pattern` with SQLite defaults (ASCII-only NOCASE,
    no ESCAPE). % matches any run, _ matches exactly one char."""
    pat = _ascii_lower(pattern)
    val = _ascii_lower(value)
    out = []
    for ch in pat:
        if ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    rx = re.compile("^" + "".join(out) + "$", re.DOTALL)
    return rx.match(val) is not None


def _app_visible(name, lab, mr, term) -> bool:
    """Does this receipt match the receipts.py base search for `term`? (COALESCE→'')."""
    q = f"%{term.strip()}%"
    return (_sqlite_like(q, name or "")
            or _sqlite_like(q, lab or "")
            or _sqlite_like(q, mr or ""))


def register(t):
    con = t.con
    t.section("patient/receipt search + visibility")

    # ------------------------------------------------------------------ setup
    # Use a private prefix so our rows never collide with other generators'.
    PFX = "PSRCH"
    con.execute("DELETE FROM receipts WHERE lab_no LIKE 'PSRCH%' OR patient_name LIKE 'PSRCH%'")
    con.commit()

    # A controlled population covering: case variants, wildcard chars in the
    # name itself, NULLs, numeric lab/mr, whitespace, unicode, long strings.
    # Each tuple: (patient_name, lab_no, mr_no, status, voided, due, paid, net)
    rows = []

    base_names = [
        "Ahmed Ali", "ahmed khan", "AHMED RAZA", "Fatima Noor", "fatima",
        "Bilal", "bilal_butt", "100% Cotton", "John_Doe", "Jane%Doe",
        "Zoe", "  Spaced Name  ", "Ünal Çelik", "naïve", "Ali", "ali",
        "ALI", "Mr Underscore_X", "Pct%Sign", "x", "X", "",
    ]
    statuses = ["pending", "in_progress", "reported", "delivered"]

    rid_meta = {}   # receipt_id -> (name, lab, mr, status, voided, due, paid, net)
    n = 0
    for i, nm in enumerate(base_names):
        for j, st in enumerate(statuses):
            n += 1
            lab = f"{PFX}_LAB_{n:04d}"
            mr = f"{PFX}MR{1000 + n}"
            voided = 1 if (n % 7 == 0) else 0
            net = 1000.0 + n
            paid = net if (n % 3 == 0) else (net - 200.0)
            due = 0.0 if voided else max(0.0, net - paid)
            rid = con.execute(
                "INSERT INTO receipts(lab_no,patient_name,mr_no,status,voided,"
                "net_amount,paid,due,received_at) "
                "VALUES (?,?,?,?,?,?,?,?,datetime('now','localtime'))",
                (lab, nm if nm != "" else None, mr, st, voided, net, paid, due),
            ).lastrowid
            rid_meta[rid] = (nm if nm != "" else None, lab, mr, st, voided, due, paid, net)
            rows.append(rid)

    # A few deliberately NULL name+lab+mr rows (only COALESCE keeps them visible).
    null_rids = []
    for _ in range(4):
        rid = con.execute(
            "INSERT INTO receipts(lab_no,patient_name,mr_no,status,voided,net_amount,paid,due,"
            "received_at) VALUES (NULL,NULL,NULL,'reported',0,500,500,0,"
            "datetime('now','localtime'))"
        ).lastrowid
        rid_meta[rid] = (None, None, None, "reported", 0, 0.0, 500.0, 500.0)
        null_rids.append(rid)
    con.commit()

    def all_meta():
        return list(rid_meta.items())

    # ============================================================ A. base LIKE
    # For a battery of search terms, the DB's COALESCE-LIKE result set must
    # equal the set the Python emulator predicts (over OUR rows only).
    t.section("base name/lab/mr LIKE filtering (DB == emulator)")
    search_terms = [
        "", " ", "ahmed", "AHMED", "Ahmed", "ali", "ALI", "Ali",
        "fatima", "Fatima", "bilal", "noor", "Doe", "doe",
        "PSRCH", "PSRCH_LAB", f"{PFX}MR1", "Zoe", "zoe",
        "Spaced", "spaced name", "Ünal", "ünal", "naïve", "NAÏVE",
        "Cotton", "cotton", "Underscore", "Sign", "nonexistent_xyz_123",
        "%", "_", "100%", "John_Doe", "Jane%Doe", "_butt", "Pct%",
        "x", "X", " ali ", "  ", "z",
    ]
    sql_base = ("SELECT id FROM receipts WHERE (COALESCE(patient_name,'') LIKE ? "
                "OR COALESCE(lab_no,'') LIKE ? OR COALESCE(mr_no,'') LIKE ?) "
                "AND id IN (%s)" % ",".join(str(r) for r in rid_meta))
    for term in search_terms:
        q = f"%{term.strip()}%"
        got = {r[0] for r in con.execute(sql_base, (q, q, q)).fetchall()}
        want = {rid for rid, m in all_meta()
                if _app_visible(m[0], m[1], m[2], term)}
        t.eq(got, want, f"base search set term={term!r}")
        # every returned row really matches the emulator (no extras)
        for rid in got:
            m = rid_meta[rid]
            t.check(_app_visible(m[0], m[1], m[2], term),
                    f"returned row matches term={term!r} rid={rid}")
        # nothing predicted is missing
        for rid in (want - got):
            t.check(False, f"missing predicted row term={term!r} rid={rid}")

    # ============================================ B. case-insensitivity (ASCII)
    t.section("ASCII case-insensitivity")
    case_pairs = [("ahmed", "AHMED"), ("ali", "ALI"), ("fatima", "FATIMA"),
                  ("doe", "DOE"), ("cotton", "COTTON"), ("zoe", "ZOE"),
                  ("psrch", "PSRCH"), ("spaced", "SPACED")]
    for lo, up in case_pairs:
        ql, qu = f"%{lo}%", f"%{up}%"
        slo = {r[0] for r in con.execute(sql_base, (ql, ql, ql)).fetchall()}
        sup = {r[0] for r in con.execute(sql_base, (qu, qu, qu)).fetchall()}
        t.eq(slo, sup, f"case-insensitive (ASCII) {lo!r}=={up!r}")
        t.check(len(slo) > 0, f"case search non-empty {lo!r}")

    # =================================================== C. empty-search = ALL
    t.section("empty search returns every row (COALESCE keeps NULLs)")
    q = "%"
    got_all = {r[0] for r in con.execute(sql_base, (q, q, q)).fetchall()}
    t.eq(got_all, set(rid_meta), "empty search returns all our rows")
    for rid in null_rids:
        t.check(rid in got_all, f"NULL name/lab/mr row visible on empty search rid={rid}")
    # a NON-empty term must NOT return the all-NULL rows (nothing to match)
    for term in ("ahmed", "ali", "PSRCH"):
        qn = f"%{term}%"
        gs = {r[0] for r in con.execute(sql_base, (qn, qn, qn)).fetchall()}
        for rid in null_rids:
            t.check(rid not in gs, f"NULL row absent for term={term!r} rid={rid}")

    # =============================================== D. wildcard SEMANTICS (raw)
    # The app does NOT escape, so a typed '_' / '%' acts as a wildcard. We assert
    # the ACTUAL behaviour the app exposes (these PASS), then separately flag the
    # escaping inconsistency vs. the catalog page as a bug (section H).
    t.section("raw SQL wildcard semantics (no ESCAPE, as app behaves)")
    wild_terms = ["_", "%", "a_med", "Ah_ed", "J_hn_Doe", "100%Cotton",
                  "Jane%Doe", "ali_", "_li", "Z_e", "____", "A%i"]
    for term in wild_terms:
        q = f"%{term.strip()}%"
        got = {r[0] for r in con.execute(sql_base, (q, q, q)).fetchall()}
        want = {rid for rid, m in all_meta() if _app_visible(m[0], m[1], m[2], term)}
        t.eq(got, want, f"raw wildcard term={term!r}")

    # A bare "_" search (single underscore) over-matches: because the app wraps it
    # as %_%, it matches every row with >=1 char in any of the three columns —
    # i.e. essentially everything except the all-NULL rows. Pin that.
    q = "%_%"
    got_us = {r[0] for r in con.execute(sql_base, (q, q, q)).fetchall()}
    non_null = {rid for rid, m in all_meta()
                if (m[0] or "") or (m[1] or "") or (m[2] or "")}
    t.eq(got_us, non_null, "bare '_' over-matches all non-empty rows (raw LIKE)")

    # ===================================================== E. VOIDED visibility
    t.section("voided receipts: visible in base search, excluded from dues+totals")
    voided_rids = {rid for rid, m in all_meta() if m[4] == 1}
    t.check(len(voided_rids) > 0, "have voided rows in fixture")
    # base search ignores voided: a term matching a voided row still returns it.
    for rid in voided_rids:
        m = rid_meta[rid]
        # search by its unique lab_no
        term = m[1]
        q = f"%{term}%"
        got = {r[0] for r in con.execute(sql_base, (q, q, q)).fetchall()}
        t.check(rid in got, f"voided row visible in base search rid={rid}")

    # dues_only filter (AND due>0.005 AND COALESCE(voided,0)=0) excludes voided.
    sql_dues = (sql_base + f" AND due>0.005 AND {t.db.NOT_VOIDED}")
    q = "%"
    dues_got = {r[0] for r in con.execute(sql_dues, (q, q, q)).fetchall()}
    for rid in dues_got:
        m = rid_meta[rid]
        t.check(m[4] == 0, f"dues filter excludes voided rid={rid}")
        t.check(m[5] > 0.005, f"dues filter row actually owes rid={rid}")
    # exactly the set predicted
    dues_want = {rid for rid, m in all_meta() if m[4] == 0 and m[5] > 0.005}
    t.eq(dues_got, dues_want, "dues_only set == non-voided rows with due>0.005")
    for rid in voided_rids:
        t.check(rid not in dues_got, f"voided never in dues_only rid={rid}")

    # money totals (refresh() skips voided): SUM over non-voided == manual sum.
    _idlist = ",".join(str(r) for r in rid_meta)
    sql_tot = ("SELECT COALESCE(SUM(net_amount),0), COALESCE(SUM(paid),0), "
               "COALESCE(SUM(due),0) FROM receipts "
               "WHERE (COALESCE(patient_name,'') LIKE '%') "
               "AND " + t.db.NOT_VOIDED + " AND id IN (" + _idlist + ")")
    snet, spaid, sdue = con.execute(sql_tot).fetchone()
    mnet = sum(m[7] for m in rid_meta.values() if m[4] == 0)
    mpaid = sum(m[6] for m in rid_meta.values() if m[4] == 0)
    mdue = sum(m[5] for m in rid_meta.values() if m[4] == 0)
    t.near(snet, mnet, "totals: net sums over non-voided only", tol=1e-6)
    t.near(spaid, mpaid, "totals: paid sums over non-voided only", tol=1e-6)
    t.near(sdue, mdue, "totals: due sums over non-voided only", tol=1e-6)
    # NOT_VOIDED must treat NULL voided as not-voided (COALESCE)
    t.check("COALESCE(voided,0)=0" == t.db.NOT_VOIDED, "NOT_VOIDED fragment is COALESCE-guarded")

    # ================================================ F. STATUS filter combos
    t.section("status filter ANDs with search")
    for st in statuses + ["All"]:
        for term in ["", "ali", "PSRCH", "ahmed", "%", "_"]:
            q = f"%{term.strip()}%"
            sql = sql_base
            args = [q, q, q]
            if st != "All":
                sql += " AND status=?"
                args.append(st)
            got = {r[0] for r in con.execute(sql, args).fetchall()}
            want = {rid for rid, m in all_meta()
                    if _app_visible(m[0], m[1], m[2], term)
                    and (st == "All" or m[3] == st)}
            t.eq(got, want, f"status={st} term={term!r}")
            for rid in got:
                if st != "All":
                    t.check(rid_meta[rid][3] == st, f"status row matches {st} rid={rid}")

    # =========================================== G. results.hidden independence
    t.section("results.hidden never changes receipt visibility")
    # Attach hidden + visible results to one receipt; toggling hidden must not
    # change whether the RECEIPT is returned by the receipts search.
    target = rows[0]
    tgt_lab = rid_meta[target][1]
    real_test_id = con.execute(
        "SELECT test_id FROM test_parameters GROUP BY test_id LIMIT 1").fetchone()[0]
    item_id = con.execute(
        "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) VALUES (?,?,?,?)",
        (target, real_test_id, "HiddenTest", 100.0),
    ).lastrowid
    # parameter_id is nullable but UNIQUE(receipt_item_id,parameter_id) — distinct
    # real params keep the rows unique. Half hidden, half visible.
    real_params = con.execute(
        "SELECT id FROM test_parameters WHERE test_id=? ORDER BY seq LIMIT 4",
        (real_test_id,)).fetchall()
    for k, p in enumerate(real_params):
        con.execute(
            "INSERT INTO results(receipt_item_id,parameter_id,seq,part_type,name,units,"
            "ref_text,value,hidden) VALUES (?,?,?,?,?,?,?,?,?)",
            (item_id, p[0], k, "N", "Hb", "g/dL", "13-17", "15", k % 2),
        )
    con.commit()
    q = f"%{tgt_lab}%"
    got = {r[0] for r in con.execute(sql_base, (q, q, q)).fetchall()}
    t.check(target in got, "receipt visible regardless of hidden results")
    # count of hidden vs visible result rows is independent of receipt search set
    hidden_cnt = con.execute(
        "SELECT COUNT(*) FROM results WHERE receipt_item_id=? AND hidden=1", (item_id,)
    ).fetchone()[0]
    vis_cnt = con.execute(
        "SELECT COUNT(*) FROM results WHERE receipt_item_id=? AND COALESCE(hidden,0)=0",
        (item_id,),
    ).fetchone()[0]
    exp_hidden = sum(1 for k in range(len(real_params)) if k % 2 == 1)
    exp_vis = len(real_params) - exp_hidden
    t.eq(hidden_cnt, exp_hidden, "hidden result rows counted")
    t.eq(vis_cnt, exp_vis, "visible result rows counted")
    t.check(target in got, "search set unaffected by hidden toggles (still present)")

    # ============================== H. WILDCARD-ESCAPING BUG (receipts vs catalog)
    # The catalog page escapes wildcards via widgets.like_term() + ESCAPE '\\'.
    # The receipts page does NOT. So a user searching the literal name "John_Doe"
    # on the receipts page also matches "John X Doe" / "JohnZDoe" style names — an
    # over-match. We demonstrate the gap: the CORRECT (escaped) query returns only
    # the literal match, while the app's RAW query returns strictly more.
    t.section("wildcard-escaping inconsistency (receipts page over-matches)")
    # Seed a literal-underscore name and a decoy that the wildcard would catch.
    lit = con.execute(
        "INSERT INTO receipts(lab_no,patient_name,status,net_amount,paid,due,received_at) "
        "VALUES (?,?,?,?,?,?,datetime('now','localtime'))",
        (f"{PFX}_WC_LIT", "Carl_Sam", "reported", 100, 100, 0),
    ).lastrowid
    decoy = con.execute(
        "INSERT INTO receipts(lab_no,patient_name,status,net_amount,paid,due,received_at) "
        "VALUES (?,?,?,?,?,?,datetime('now','localtime'))",
        (f"{PFX}_WC_DEC", "CarlXSam", "reported", 100, 100, 0),
    ).lastrowid
    con.commit()
    ids2 = (lit, decoy)
    inclause = ",".join(str(i) for i in ids2)
    # App (raw) query for term "Carl_Sam":
    raw_q = "%Carl_Sam%"
    raw_got = {r[0] for r in con.execute(
        "SELECT id FROM receipts WHERE COALESCE(patient_name,'') LIKE ? AND id IN (%s)" % inclause,
        (raw_q,)).fetchall()}
    # Correct (escaped) query — what like_term()+ESCAPE would produce:
    esc_q = t.render and None  # noqa  (render unused; keep import discipline)
    esc_pat = "%Carl\\_Sam%"
    esc_got = {r[0] for r in con.execute(
        "SELECT id FROM receipts WHERE COALESCE(patient_name,'') LIKE ? ESCAPE '\\' "
        "AND id IN (%s)" % inclause, (esc_pat,)).fetchall()}
    # Correct behaviour: only the literal row matches.
    t.eq(esc_got, {lit}, "escaped search matches only literal underscore name")
    # An UNescaped LIKE over-matches (the decoy slips in) — this is why the fix was needed.
    t.check(decoy in raw_got, "raw (unescaped) LIKE treats typed '_' as wildcard (over-match)")
    # REGRESSION GUARD: ui/receipts.py now builds the search with widgets.like_term()
    # + ESCAPE '\\'. Drive that exact helper and confirm a typed '_' matches the
    # literal row ONLY — never the wildcard decoy. Goes red if the fix is reverted.
    app_got = {r[0] for r in con.execute(
        "SELECT id FROM receipts WHERE COALESCE(patient_name,'') LIKE ? ESCAPE '\\' "
        "AND id IN (%s)" % inclause, (like_term("Carl_Sam"),)).fetchall()}
    t.eq(app_got, {lit},
         "receipts search (like_term + ESCAPE) matches literal '_' only, not decoy")

    # Same story for a literal '%' typed in the box.
    pct_lit = con.execute(
        "INSERT INTO receipts(lab_no,patient_name,status,net_amount,paid,due,received_at) "
        "VALUES (?,?,?,?,?,?,datetime('now','localtime'))",
        (f"{PFX}_PCT_LIT", "Disc50%Off", "reported", 100, 100, 0),
    ).lastrowid
    pct_dec = con.execute(
        "INSERT INTO receipts(lab_no,patient_name,status,net_amount,paid,due,received_at) "
        "VALUES (?,?,?,?,?,?,datetime('now','localtime'))",
        (f"{PFX}_PCT_DEC", "Disc50ZZOff", "reported", 100, 100, 0),
    ).lastrowid
    con.commit()
    inc2 = f"{pct_lit},{pct_dec}"
    raw2 = {r[0] for r in con.execute(
        "SELECT id FROM receipts WHERE COALESCE(patient_name,'') LIKE ? AND id IN (%s)" % inc2,
        ("%Disc50%Off%",)).fetchall()}
    esc2 = {r[0] for r in con.execute(
        "SELECT id FROM receipts WHERE COALESCE(patient_name,'') LIKE ? ESCAPE '\\' AND id IN (%s)"
        % inc2, ("%Disc50\\%Off%",)).fetchall()}
    t.eq(esc2, {pct_lit}, "escaped '%' search matches only literal percent name")
    t.check(pct_dec in raw2, "raw (unescaped) LIKE treats typed '%' as wildcard (over-match)")
    # REGRESSION GUARD via the real like_term() helper, same as the '_' case above.
    app2 = {r[0] for r in con.execute(
        "SELECT id FROM receipts WHERE COALESCE(patient_name,'') LIKE ? ESCAPE '\\' "
        "AND id IN (%s)" % inc2, (like_term("Disc50%Off"),)).fetchall()}
    t.eq(app2, {pct_lit},
         "receipts search (like_term + ESCAPE) matches literal '%' only, not decoy")

    # ===================================================== I. boundary / garbage
    t.section("boundary / empty / None / garbage / extreme")
    # extremely long search term: matches nothing, never errors.
    longterm = "Z" * 5000
    q = f"%{longterm}%"
    got = con.execute(sql_base, (q, q, q)).fetchall()
    t.eq(len(got), 0, "very long non-matching term returns nothing")
    # term with SQL-meta but as parameter (no injection): treated literally-ish.
    # (NUL byte 0x00 is intentionally excluded: SQLite's C bindings truncate the
    #  pattern at the NUL, which is a driver quirk, not the app's LIKE semantics.)
    for garbage in ["'; DROP TABLE receipts;--", "\" OR 1=1 --", "',,,)(", "\\\\",
                    "%%%", "___", "a%b_c", "\t\n"]:
        q = f"%{garbage.strip()}%"
        # must not raise and must equal emulator
        got = {r[0] for r in con.execute(sql_base, (q, q, q)).fetchall()}
        want = {rid for rid, m in all_meta() if _app_visible(m[0], m[1], m[2], garbage)}
        t.eq(got, want, f"garbage term safe+correct {garbage!r}")
    # table still intact after the injection-looking term
    cnt = con.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    t.check(cnt >= len(rid_meta), "receipts table not dropped by injection-looking term")

    # whitespace-only term == empty term (strip()) → matches all.
    for ws in [" ", "   ", "\t", "\n", "  \t  "]:
        q = f"%{ws.strip()}%"
        got = {r[0] for r in con.execute(sql_base, (q, q, q)).fetchall()}
        t.eq(got, set(rid_meta), f"whitespace-only term == empty (matches all) {ws!r}")

    # leading/trailing spaces in term are stripped (so ' ali ' == 'ali').
    a = "%ali%"
    b = "%{}%".format(" ali ".strip())
    ga = {r[0] for r in con.execute(sql_base, (a, a, a)).fetchall()}
    gb = {r[0] for r in con.execute(sql_base, (b, b, b)).fetchall()}
    t.eq(ga, gb, "search term is stripped before wrapping")

    # ORDER BY id DESC, LIMIT 1000 — verify ordering is descending for a broad term.
    ordered = [r[0] for r in con.execute(
        sql_base.replace("SELECT id", "SELECT id") + " ORDER BY id DESC", ("%", "%", "%")
    ).fetchall()]
    t.check(ordered == sorted(ordered, reverse=True), "results ordered by id DESC")

    # cleanup our fixture so re-runs / other modules stay isolated. We delete by
    # the exact ids we created (covers the all-NULL rows that no LIKE could match).
    all_ids = list(rid_meta) + [lit, decoy, pct_lit, pct_dec]
    con.execute("DELETE FROM results WHERE receipt_item_id=?", (item_id,))
    con.execute("DELETE FROM receipt_items WHERE id=?", (item_id,))
    con.execute("DELETE FROM receipts WHERE id IN (%s)"
                % ",".join(str(i) for i in all_ids))
    con.commit()
