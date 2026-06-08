"""Catalog generator — panels CRUD + parameter editor invariants.

Focus: src/labdesk/db.py
  list_panels, panel_tests, save_panel, delete_panel, save_test_parameters
and the tests / test_parameters / panels / panel_items tables.

Covers: CRUD round-trips, panel membership, parameter ordering by seq,
idempotent re-saves, the in-use delete guard, and boundary/garbage inputs.

Contract (see tests/gen/test_billing.py):
  * exactly one register(t)
  * assertions only via t.check / t.eq / t.near / t.has
  * isolated DB only (t.con); no network
"""
from __future__ import annotations


def _mk_test(con, name, charges=0.0):
    """Create a throwaway active test and return its id."""
    return con.execute(
        "INSERT INTO tests(name, charges, active) VALUES (?,?,1)", (name, charges)
    ).lastrowid


def register(t):
    con = t.con
    db = t.db

    # =====================================================================
    # PART 1 — panel CRUD round-trips + membership (parametrized)
    # =====================================================================
    t.section("panel CRUD round-trips + membership")

    # a stable pool of fresh tests, each with a known charge
    pool = []
    for i in range(14):
        tid = _mk_test(con, f"CATTEST {i:02d} µ/L", charges=100.0 + i)
        pool.append(tid)
    con.commit()

    # parametrize over many member-set shapes (including empty + duplicates)
    MEMBER_SETS = [
        [],
        [pool[0]],
        [pool[0], pool[1]],
        [pool[2], pool[3], pool[4]],
        list(pool[:5]),
        list(pool),                       # all of them
        [pool[0], pool[0]],               # duplicate test id
        [pool[1], pool[1], pool[2]],      # dup + extra
        [pool[5], pool[3], pool[1]],      # out-of-order ids -> alphabetical out
        [pool[13], pool[0]],
        [pool[2]],
        [pool[6], pool[7]],
        [pool[8], pool[9], pool[10]],
        list(pool[3:11]),
        [pool[11], pool[12], pool[13]],
        [pool[0], pool[2], pool[4], pool[6], pool[8], pool[10], pool[12]],
        [pool[1], pool[3], pool[5], pool[7], pool[9], pool[11], pool[13]],
        [pool[4], pool[4], pool[5], pool[5]],   # multiple dups
    ]

    created_panels = []
    for idx, members in enumerate(MEMBER_SETS):
        pname = f"CatPanel {idx}"
        pid = db.save_panel(con, pname, members)
        created_panels.append(pid)
        t.check(pid > 0, f"save_panel returns positive id set={idx}")

        # panel exists + name stored + active
        row = con.execute("SELECT name, active FROM panels WHERE id=?", (pid,)).fetchone()
        t.eq(row["name"], pname, f"panel name stored set={idx}")
        t.eq(row["active"], 1, f"new panel active set={idx}")

        # membership: panel_items mirrors exactly the test_ids passed (dups included,
        # since save_panel inserts one row per id with no dedup)
        raw = con.execute(
            "SELECT test_id FROM panel_items WHERE panel_id=? ORDER BY id", (pid,)
        ).fetchall()
        t.eq([r["test_id"] for r in raw], list(members),
             f"panel_items mirror input ids set={idx}")

        # panel_tests joins to live tests, DISTINCT-free, alphabetical by name
        pt = db.panel_tests(con, pid)
        # every returned id is one we asked for
        asked = set(members)
        for m in pt:
            t.check(m["id"] in asked, f"panel_tests id is a member set={idx}")
        # all distinct asked ids appear at least once
        returned_ids = {m["id"] for m in pt}
        t.eq(returned_ids, asked, f"panel_tests covers all distinct members set={idx}")
        # ordering: names non-decreasing (case-insensitive)
        names = [(m["name"] or "").lower() for m in pt]
        t.check(names == sorted(names), f"panel_tests alphabetical set={idx}")
        # charges come through from tests table
        for m in pt:
            want = con.execute("SELECT charges FROM tests WHERE id=?", (m["id"],)).fetchone()[0]
            t.eq(m["charges"], want, f"panel_tests charge matches test set={idx}")
        # list_panels (active) includes this panel
        t.check(any(p["id"] == pid for p in db.list_panels(con)),
                f"list_panels includes new panel set={idx}")

    # =====================================================================
    # PART 2 — save_panel UPDATE path replaces members + renames
    # =====================================================================
    t.section("save_panel update replaces members + renames")

    up_pid = db.save_panel(con, "Renamable", [pool[0], pool[1], pool[2]])
    t.eq(len(db.panel_tests(con, up_pid)), 3, "update-target starts with 3 members")

    UPDATE_SEQ = [
        ("Renamable v2", [pool[3]]),
        ("Renamable v3", [pool[4], pool[5], pool[6], pool[7]]),
        ("Renamable v4", []),                       # update to empty
        ("Renamable v5", [pool[0], pool[0], pool[1]]),  # dup on update
        ("Renamable v6", list(pool[:8])),
    ]
    for uname, umembers in UPDATE_SEQ:
        rid = db.save_panel(con, uname, umembers, up_pid)
        t.eq(rid, up_pid, f"save_panel update returns same id ({uname})")
        # name updated
        t.eq(con.execute("SELECT name FROM panels WHERE id=?", (up_pid,)).fetchone()[0],
             uname, f"save_panel update renames ({uname})")
        # members fully replaced (no leftovers from prior state)
        raw = [r["test_id"] for r in con.execute(
            "SELECT test_id FROM panel_items WHERE panel_id=? ORDER BY id", (up_pid,)).fetchall()]
        t.eq(raw, list(umembers), f"save_panel update replaces members ({uname})")
        # re-activates (active stays 1)
        t.eq(con.execute("SELECT active FROM panels WHERE id=?", (up_pid,)).fetchone()[0], 1,
             f"save_panel update keeps active=1 ({uname})")

    # idempotent re-save: saving the SAME thing twice yields the same state
    db.save_panel(con, "Idem", [pool[0], pool[1], pool[2]], up_pid)
    snap1 = [r["test_id"] for r in con.execute(
        "SELECT test_id FROM panel_items WHERE panel_id=? ORDER BY test_id", (up_pid,)).fetchall()]
    db.save_panel(con, "Idem", [pool[0], pool[1], pool[2]], up_pid)
    snap2 = [r["test_id"] for r in con.execute(
        "SELECT test_id FROM panel_items WHERE panel_id=? ORDER BY test_id", (up_pid,)).fetchall()]
    t.eq(snap1, snap2, "save_panel idempotent re-save: same members")
    t.eq(len(snap2), 3, "save_panel idempotent re-save: no duplicate rows")

    # =====================================================================
    # PART 3 — name handling: trimming + blank rejection
    # =====================================================================
    t.section("save_panel name handling")

    # whitespace is stripped
    sp = db.save_panel(con, "   Trimmed Name   ", [pool[0]])
    t.eq(con.execute("SELECT name FROM panels WHERE id=?", (sp,)).fetchone()[0],
         "Trimmed Name", "save_panel strips surrounding whitespace")

    # blank / whitespace-only / None names rejected with ValueError, no row added
    for bad in ["", "   ", "\t", "\n", None]:
        before = con.execute("SELECT COUNT(*) FROM panels").fetchone()[0]
        try:
            db.save_panel(con, bad, [pool[0]])
            t.check(False, f"save_panel rejects blank name {bad!r}")
        except ValueError:
            t.check(True, f"save_panel rejects blank name {bad!r}")
        except Exception:
            # rollback any half-open txn so later asserts work
            try:
                con.rollback()
            except Exception:
                pass
            t.check(False, f"save_panel raised wrong type for {bad!r}")
        after = con.execute("SELECT COUNT(*) FROM panels").fetchone()[0]
        t.eq(after, before, f"blank-name reject adds no panel {bad!r}")

    # string-coercible test ids are accepted (int(t) in save_panel)
    sc = db.save_panel(con, "StrIds", [str(pool[0]), str(pool[1])])
    t.eq({m["id"] for m in db.panel_tests(con, sc)}, {pool[0], pool[1]},
         "save_panel coerces string ids via int()")

    # =====================================================================
    # PART 4 — delete_panel: soft delete hides + clears members
    # =====================================================================
    t.section("delete_panel soft-delete semantics")

    for idx in range(8):
        dp = db.save_panel(con, f"Doomed {idx}", [pool[idx % len(pool)], pool[(idx + 1) % len(pool)]])
        t.check(any(p["id"] == dp for p in db.list_panels(con)),
                f"doomed panel listed before delete {idx}")
        db.delete_panel(con, dp)
        # active flag flipped to 0
        t.eq(con.execute("SELECT active FROM panels WHERE id=?", (dp,)).fetchone()[0], 0,
             f"delete_panel sets active=0 {idx}")
        # hidden from default list_panels
        t.check(not any(p["id"] == dp for p in db.list_panels(con)),
                f"delete_panel hides from list_panels {idx}")
        # but visible with include_inactive=True
        t.check(any(p["id"] == dp for p in db.list_panels(con, include_inactive=True)),
                f"delete_panel still in include_inactive list {idx}")
        # member rows removed
        t.eq(con.execute("SELECT COUNT(*) FROM panel_items WHERE panel_id=?", (dp,)).fetchone()[0], 0,
             f"delete_panel clears panel_items {idx}")
        # panel_tests now empty
        t.eq(len(db.panel_tests(con, dp)), 0, f"panel_tests empty after delete {idx}")

    # deleting an already-deleted panel is idempotent (no crash, stays gone)
    dd = db.save_panel(con, "DoubleDelete", [pool[0]])
    db.delete_panel(con, dd)
    db.delete_panel(con, dd)
    t.eq(con.execute("SELECT active FROM panels WHERE id=?", (dd,)).fetchone()[0], 0,
         "double delete_panel stays inactive")
    t.eq(con.execute("SELECT COUNT(*) FROM panel_items WHERE panel_id=?", (dd,)).fetchone()[0], 0,
         "double delete_panel keeps members cleared")

    # delete of a non-existent panel id does not raise and adds nothing
    before_cnt = con.execute("SELECT COUNT(*) FROM panels").fetchone()[0]
    db.delete_panel(con, 9_999_999)
    t.eq(con.execute("SELECT COUNT(*) FROM panels").fetchone()[0], before_cnt,
         "delete_panel of missing id is a no-op")

    # =====================================================================
    # PART 5 — list_panels ordering (alphabetical, case-insensitive)
    # =====================================================================
    t.section("list_panels ordering")
    listed = db.list_panels(con)
    lnames = [(p["name"] or "").lower() for p in listed]
    t.check(lnames == sorted(lnames), "list_panels sorted alphabetically (NOCASE)")
    t.check(all(p["active"] == 1 for p in listed), "list_panels returns only active panels")
    # include_inactive superset of active
    active_ids = {p["id"] for p in db.list_panels(con)}
    all_ids = {p["id"] for p in db.list_panels(con, include_inactive=True)}
    t.check(active_ids <= all_ids, "active panels subset of include_inactive")

    # =====================================================================
    # PART 6 — save_test_parameters: insert / order-by-seq / round-trip
    # =====================================================================
    t.section("save_test_parameters insert + seq ordering")

    PART_TYPES = ["N", "H", "L", "Y", "T"]

    def _row(i, ptype="N"):
        return {
            "id": None, "part_type": ptype,
            "name": f"Param {i}", "units": f"u{i}",
            "ref_male": f"m{i}", "ref_female": f"f{i}",
            "default_result": f"d{i}", "superscript": f"s{i}",
            "group_head": f"g{i}",
        }

    # vary the number of rows widely, including 0 (clear) and large
    for n in [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 13, 16, 21, 30, 40, 55]:
        tid = _mk_test(con, f"ParamTest n={n}")
        rows = [_row(i, PART_TYPES[i % len(PART_TYPES)]) for i in range(n)]
        db.save_test_parameters(con, tid, rows)
        stored = con.execute(
            "SELECT * FROM test_parameters WHERE test_id=? ORDER BY seq", (tid,)).fetchall()
        t.eq(len(stored), n, f"insert count matches n={n}")
        # seq is a dense 0..n-1 sequence in insertion order
        t.eq([r["seq"] for r in stored], list(range(n)), f"seq dense 0..n-1 n={n}")
        # full field round-trip per row
        for i, r in enumerate(stored):
            t.eq(r["name"], f"Param {i}", f"name round-trip n={n} i={i}")
            t.eq(r["units"], f"u{i}", f"units round-trip n={n} i={i}")
            t.eq(r["ref_male"], f"m{i}", f"ref_male round-trip n={n} i={i}")
            t.eq(r["ref_female"], f"f{i}", f"ref_female round-trip n={n} i={i}")
            t.eq(r["default_result"], f"d{i}", f"default round-trip n={n} i={i}")
            t.eq(r["superscript"], f"s{i}", f"superscript round-trip n={n} i={i}")
            t.eq(r["group_head"], f"g{i}", f"group_head round-trip n={n} i={i}")
            t.eq(r["part_type"], PART_TYPES[i % len(PART_TYPES)],
                 f"part_type round-trip n={n} i={i}")
            t.eq(r["test_id"], tid, f"test_id stamped n={n} i={i}")

    # =====================================================================
    # PART 7 — missing keys -> defaults ('' for text, 'N' for part_type)
    # =====================================================================
    t.section("save_test_parameters defaults for missing/None keys")

    dt = _mk_test(con, "DefaultsTest")
    db.save_test_parameters(con, dt, [
        {},                                       # totally empty -> all defaults
        {"name": "OnlyName"},                     # only name
        {"part_type": None, "name": None},        # explicit None -> defaults
        {"part_type": "", "name": "EmptyType"},   # empty part_type -> 'N'
    ])
    drows = con.execute(
        "SELECT * FROM test_parameters WHERE test_id=? ORDER BY seq", (dt,)).fetchall()
    t.eq(len(drows), 4, "defaults: all four rows inserted")
    t.eq(drows[0]["part_type"], "N", "empty dict -> part_type 'N'")
    t.eq(drows[0]["name"], "", "empty dict -> name ''")
    t.eq(drows[0]["units"], "", "empty dict -> units ''")
    t.eq(drows[0]["ref_male"], "", "empty dict -> ref_male ''")
    t.eq(drows[1]["name"], "OnlyName", "only-name row keeps name")
    t.eq(drows[1]["part_type"], "N", "only-name row defaults part_type 'N'")
    t.eq(drows[2]["part_type"], "N", "None part_type -> 'N'")
    t.eq(drows[2]["name"], "", "None name -> ''")
    t.eq(drows[3]["part_type"], "N", "empty-string part_type -> 'N'")
    t.eq(drows[3]["name"], "EmptyType", "empty-type row keeps name")

    # =====================================================================
    # PART 8 — idempotent re-save (keep ids), reorder, edit in place
    # =====================================================================
    t.section("save_test_parameters idempotent re-save + reorder + edit")

    et = _mk_test(con, "EditTest")
    db.save_test_parameters(con, et, [_row(i) for i in range(6)])
    base = con.execute(
        "SELECT id,seq,name FROM test_parameters WHERE test_id=? ORDER BY seq", (et,)).fetchall()
    ids = [r["id"] for r in base]

    # 8a: re-save identical rows WITH their ids -> same ids, same count (idempotent)
    same_rows = []
    for i, r in enumerate(base):
        d = _row(i)
        d["id"] = r["id"]
        same_rows.append(d)
    db.save_test_parameters(con, et, same_rows)
    after = con.execute(
        "SELECT id,seq FROM test_parameters WHERE test_id=? ORDER BY seq", (et,)).fetchall()
    t.eq([r["id"] for r in after], ids, "idempotent re-save preserves ids + order")
    t.eq(len(after), 6, "idempotent re-save no duplicate rows")

    # do it a few more times — must stay stable
    for rep in range(5):
        db.save_test_parameters(con, et, same_rows)
        chk = con.execute(
            "SELECT id FROM test_parameters WHERE test_id=? ORDER BY seq", (et,)).fetchall()
        t.eq([r["id"] for r in chk], ids, f"repeated idempotent re-save stable rep={rep}")
        t.eq(con.execute("SELECT COUNT(*) FROM test_parameters WHERE test_id=?", (et,)).fetchone()[0],
             6, f"repeated re-save no growth rep={rep}")

    # 8b: reverse the order, keeping ids -> ids follow new seq order
    rev = list(reversed(same_rows))
    db.save_test_parameters(con, et, rev)
    rev_after = con.execute(
        "SELECT id,seq FROM test_parameters WHERE test_id=? ORDER BY seq", (et,)).fetchall()
    t.eq([r["id"] for r in rev_after], list(reversed(ids)),
         "reorder by reversing keeps ids, flips order")
    t.eq([r["seq"] for r in rev_after], list(range(6)), "reorder re-densifies seq 0..5")

    # 8c: edit a field in place keeps id, updates value
    edit_rows = []
    for i, r in enumerate(rev_after):
        d = _row(i)
        d["id"] = r["id"]
        d["name"] = f"Edited {i}"
        edit_rows.append(d)
    db.save_test_parameters(con, et, edit_rows)
    edited = con.execute(
        "SELECT id,name FROM test_parameters WHERE test_id=? ORDER BY seq", (et,)).fetchall()
    t.eq([r["id"] for r in edited], [r["id"] for r in rev_after],
         "in-place edit keeps ids")
    for i, r in enumerate(edited):
        t.eq(r["name"], f"Edited {i}", f"in-place edit updates name i={i}")

    # 8d: drop some rows (no results) -> removed, survivors keep ids
    keep_rows = [edit_rows[0], edit_rows[2], edit_rows[4]]
    survivor_ids = [r["id"] for r in keep_rows]
    db.save_test_parameters(con, et, keep_rows)
    surv = con.execute(
        "SELECT id FROM test_parameters WHERE test_id=? ORDER BY seq", (et,)).fetchall()
    t.eq([r["id"] for r in surv], survivor_ids, "dropping unused rows removes them, keeps survivors")
    t.eq(len(surv), 3, "dropped rows actually deleted")

    # 8e: clear all rows
    db.save_test_parameters(con, et, [])
    t.eq(con.execute("SELECT COUNT(*) FROM test_parameters WHERE test_id=?", (et,)).fetchone()[0], 0,
         "save_test_parameters with [] clears all rows")

    # =====================================================================
    # PART 9 — unknown id treated as new INSERT (not UPDATE of foreign row)
    # =====================================================================
    t.section("save_test_parameters unknown id -> insert")

    ut = _mk_test(con, "UnknownIdTest")
    # id that doesn't belong to this test (huge) should be inserted as new,
    # NOT update some other test's parameter
    db.save_test_parameters(con, ut, [
        {"id": 9_000_001, "part_type": "N", "name": "Ghost"},
    ])
    grows = con.execute(
        "SELECT id,name FROM test_parameters WHERE test_id=?", (ut,)).fetchall()
    t.eq(len(grows), 1, "unknown id inserts one row")
    t.eq(grows[0]["name"], "Ghost", "unknown-id row stored under this test")
    t.check(grows[0]["id"] != 9_000_001, "unknown id NOT reused (autoincrement assigns fresh)")

    # =====================================================================
    # PART 10 — in-use delete guard + rollback (the safety invariant)
    # =====================================================================
    t.section("save_test_parameters in-use delete guard")

    for trial in range(12):
        gt = _mk_test(con, f"GuardTest {trial}")
        db.save_test_parameters(con, gt, [
            {"id": None, "part_type": "N", "name": f"Keep{trial}"},
            {"id": None, "part_type": "N", "name": f"Used{trial}"},
            {"id": None, "part_type": "N", "name": f"Other{trial}"},
        ])
        rows = con.execute(
            "SELECT id,name FROM test_parameters WHERE test_id=? ORDER BY seq", (gt,)).fetchall()
        used_id = rows[1]["id"]
        # attach a saved result to the middle parameter
        gri = con.execute(
            "INSERT INTO receipts(lab_no,patient_name,sex,status) VALUES(?,?,?,?)",
            (f"LAB_GUARD_{trial}", "GP", "Male", "reported")).lastrowid
        git = con.execute(
            "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) VALUES(?,?,?,0)",
            (gri, gt, "x")).lastrowid
        con.execute(
            "INSERT INTO results(receipt_item_id,parameter_id,name,value) VALUES(?,?,?,?)",
            (git, used_id, f"Used{trial}", "42"))
        con.commit()

        # attempt to save a set that OMITS the in-use param -> must raise + rollback
        raised = False
        try:
            db.save_test_parameters(con, gt, [
                {"id": rows[0]["id"], "part_type": "N", "name": f"Keep{trial}-edited"},
            ])
        except db.ParameterInUseError as e:
            raised = True
            t.check(f"Used{trial}" in e.names, f"ParameterInUseError names the param trial={trial}")
        t.check(raised, f"omitting an in-use param raises ParameterInUseError trial={trial}")

        # rollback invariant: NOTHING from the rejected save persisted
        post = con.execute(
            "SELECT id,name FROM test_parameters WHERE test_id=? ORDER BY seq", (gt,)).fetchall()
        t.eq(len(post), 3, f"rejected save rolled back: row count unchanged trial={trial}")
        post_names = {r["name"] for r in post}
        t.check(f"Keep{trial}-edited" not in post_names,
                f"rejected save did not apply the edit trial={trial}")
        t.check(f"Keep{trial}" in post_names,
                f"original Keep survives the rollback trial={trial}")
        t.check(any(r["id"] == used_id for r in post),
                f"in-use parameter survives rejected delete trial={trial}")

        # a save that KEEPS the in-use param (and edits others) succeeds
        db.save_test_parameters(con, gt, [
            {"id": rows[0]["id"], "part_type": "N", "name": f"Keep{trial}"},
            {"id": used_id, "part_type": "N", "name": f"Used{trial}-renamed"},
        ])
        ok = con.execute(
            "SELECT id,name FROM test_parameters WHERE test_id=? ORDER BY seq", (gt,)).fetchall()
        t.eq(len(ok), 2, f"keeping in-use param allows save trial={trial}")
        t.check(any(r["id"] == used_id and r["name"] == f"Used{trial}-renamed" for r in ok),
                f"in-use param can be renamed in place trial={trial}")
        # the Other param (no results) was dropped successfully
        t.check(f"Other{trial}" not in {r["name"] for r in ok},
                f"unused Other param dropped trial={trial}")

    # =====================================================================
    # PART 11 — extreme / garbage values stored verbatim
    # =====================================================================
    t.section("save_test_parameters extreme values")

    xt = _mk_test(con, "ExtremeTest")
    big = "Z" * 5000
    weird = "aµb℃c'\";--<>&\n\t"
    xrows = [
        {"id": None, "part_type": "N", "name": big, "units": big},
        {"id": None, "part_type": "N", "name": weird, "ref_male": weird},
        {"id": None, "part_type": "N", "name": "neg-seq-test"},
        {"id": None, "part_type": "ZZZZ", "name": "longtype"},   # part_type not validated
    ]
    db.save_test_parameters(con, xt, xrows)
    xs = con.execute(
        "SELECT * FROM test_parameters WHERE test_id=? ORDER BY seq", (xt,)).fetchall()
    t.eq(len(xs), 4, "extreme: all rows inserted")
    t.eq(xs[0]["name"], big, "very long name stored verbatim")
    t.eq(xs[0]["units"], big, "very long units stored verbatim")
    t.eq(xs[1]["name"], weird, "special chars / sql-ish text stored verbatim")
    t.eq(xs[1]["ref_male"], weird, "special chars in ref stored verbatim")
    t.eq(xs[3]["part_type"], "ZZZZ", "part_type stored as-is (no validation)")
    t.eq([r["seq"] for r in xs], [0, 1, 2, 3], "extreme: seq still dense")

    # =====================================================================
    # PART 12 — save_test_parameters does not bleed across tests
    # =====================================================================
    t.section("parameter isolation across tests")

    ta = _mk_test(con, "IsoA")
    tb = _mk_test(con, "IsoB")
    db.save_test_parameters(con, ta, [_row(i) for i in range(4)])
    db.save_test_parameters(con, tb, [_row(i) for i in range(7)])
    t.eq(con.execute("SELECT COUNT(*) FROM test_parameters WHERE test_id=?", (ta,)).fetchone()[0], 4,
         "test A param count isolated")
    t.eq(con.execute("SELECT COUNT(*) FROM test_parameters WHERE test_id=?", (tb,)).fetchone()[0], 7,
         "test B param count isolated")
    # editing A leaves B untouched
    db.save_test_parameters(con, ta, [])
    t.eq(con.execute("SELECT COUNT(*) FROM test_parameters WHERE test_id=?", (tb,)).fetchone()[0], 7,
         "clearing A does not touch B")
    t.eq(con.execute("SELECT COUNT(*) FROM test_parameters WHERE test_id=?", (ta,)).fetchone()[0], 0,
         "clearing A actually clears A")
