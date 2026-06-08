"""Generator — Worklist / Results: status transitions (pending -> reported) and
result-entry persistence rules, exercised headlessly through t.con on
receipts / receipt_items / results.

We never construct a WorklistPage window. Instead we drive the SAME SQL that
``WorklistPage.save_results`` runs (see src/labdesk/ui/worklist.py) directly on
the isolated connection, plus the pure helpers ``resolve_ref`` (worklist) and
``report._flag``, and assert the documented invariants:

  * status only advances pending|in_progress -> reported (never delivered/void);
  * reported_at is stamped exactly once and is stable across re-saves;
  * single-line (parameter_id IS NULL) results DELETE-then-INSERT (no dup);
  * multi-parameter results UPSERT on (receipt_item_id, parameter_id);
  * the hidden flag round-trips; empty/garbage/extreme values persist verbatim;
  * resolve_ref picks the gender-appropriate range with sane fallbacks.

This module emits well over 1,200 cases.
"""
from __future__ import annotations

from labdesk.ui.worklist import resolve_ref


# ---------------------------------------------------------------------------
# helpers that replicate the real save_results persistence, on t.con
# ---------------------------------------------------------------------------
def _mk_receipt(con, *, status="pending", sex="Male", phone="03001234567",
                reported_at=None):
    """Create a patient + receipt with one real test line. Returns (rid, item_id,
    test_id). Mirrors the column set save_results / load_receipt rely on."""
    pid = con.execute(
        "INSERT INTO patients(name,age,age_desc,sex,telephone) VALUES (?,?,?,?,?)",
        ("WL Patient", 30, "Years", sex, phone),
    ).lastrowid
    test_id = con.execute(
        "SELECT test_id FROM test_parameters GROUP BY test_id "
        "ORDER BY COUNT(*) DESC LIMIT 1"
    ).fetchone()[0]
    tname = con.execute("SELECT name FROM tests WHERE id=?", (test_id,)).fetchone()[0]
    rid = con.execute(
        """INSERT INTO receipts(lab_no,patient_id,patient_name,age,age_desc,sex,
                                telephone,subtotal,net_amount,paid,due,status,reported_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (f"WL_{pid:05d}", pid, "WL Patient", 30, "Years", sex, phone,
         500.0, 500.0, 500.0, 0.0, status, reported_at),
    ).lastrowid
    item_id = con.execute(
        "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) VALUES (?,?,?,?)",
        (rid, test_id, tname, 500.0),
    ).lastrowid
    con.commit()
    return rid, item_id, test_id


def _save_param(con, item_id, param_id, sex, value, hidden):
    """Replicates the multi-parameter UPSERT branch of save_results."""
    p = con.execute("SELECT * FROM test_parameters WHERE id=?", (param_id,)).fetchone()
    ref = resolve_ref(p, sex)
    con.execute(
        """INSERT INTO results
           (receipt_item_id,parameter_id,seq,part_type,group_head,name,units,
            superscript,ref_text,value,hidden)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(receipt_item_id,parameter_id) DO UPDATE SET
             value=excluded.value, ref_text=excluded.ref_text, hidden=excluded.hidden""",
        (item_id, param_id, p["seq"], p["part_type"], p["group_head"], p["name"],
         p["units"], p["superscript"], ref, value, hidden),
    )
    con.commit()


def _save_single(con, item_id, value, hidden):
    """Replicates the single-line (parameter_id IS NULL) DELETE-then-INSERT branch."""
    con.execute(
        "DELETE FROM results WHERE receipt_item_id=? AND parameter_id IS NULL",
        (item_id,),
    )
    con.execute(
        "INSERT INTO results(receipt_item_id,parameter_id,seq,part_type,name,value,hidden)"
        " VALUES (?,?,?,?,?,?,?)",
        (item_id, None, 0, "N", "Result", value, hidden),
    )
    con.commit()


def _finalise(con, rid):
    """Replicates the status/reported_at stamp of save_results."""
    con.execute(
        "UPDATE receipts SET status='reported', "
        "reported_at=datetime('now','localtime') "
        "WHERE id=? AND status IN ('pending','in_progress')",
        (rid,),
    )
    con.commit()


# ---------------------------------------------------------------------------
def register(t):
    con = t.con

    # =====================================================================
    # 1) resolve_ref: gender selection + fallbacks
    # =====================================================================
    t.section("resolve_ref gender selection + fallbacks")

    class _P(dict):
        def __getitem__(self, k):
            return dict.get(self, k)

    # explicit male/female present -> pick by sex prefix (case/garbage tolerant)
    SEX_F = ["Female", "female", "FEMALE", "f", "F", "fem"]
    SEX_M = ["Male", "male", "M", "m", "man", "Other", "", None, "x", "  "]
    for m in ["13.0 - 18.0", "4 - 11", "", "0-5"]:
        for f in ["11.5 - 16.0", "1 - 20", "", "x"]:
            p = _P(ref_male=m, ref_female=f)
            for sx in SEX_F:
                want = f or m   # female falls back to male when female blank
                t.eq(resolve_ref(p, sx), want, f"resolve female m={m!r} f={f!r} sx={sx!r}")
            for sx in SEX_M:
                want = m or f   # non-female falls back to female when male blank
                t.eq(resolve_ref(p, sx), want, f"resolve male m={m!r} f={f!r} sx={sx!r}")

    # None columns coalesce to "" (never raises, never returns None)
    for sx in ["Male", "Female", None, "", "garbage"]:
        p = _P(ref_male=None, ref_female=None)
        t.eq(resolve_ref(p, sx), "", f"resolve both-None -> '' sx={sx!r}")
        p2 = _P(ref_male=None, ref_female="9-9")
        # male path with male None -> female fallback; female path -> female
        t.eq(resolve_ref(p2, sx), "9-9", f"resolve maleNone fallback sx={sx!r}")

    # =====================================================================
    # 2) status transitions (pending|in_progress -> reported only)
    # =====================================================================
    t.section("status transition matrix on finalise")
    # finalise should advance these
    for start in ["pending", "in_progress"]:
        rid, item_id, _ = _mk_receipt(con, status=start)
        _finalise(con, rid)
        row = con.execute("SELECT status, reported_at FROM receipts WHERE id=?",
                          (rid,)).fetchone()
        t.eq(row["status"], "reported", f"{start} -> reported")
        t.check(row["reported_at"] is not None, f"{start}: reported_at stamped")
    # finalise must NOT touch a terminal/other status
    for start in ["reported", "delivered"]:
        rid, item_id, _ = _mk_receipt(con, status=start, reported_at="2020-01-01 00:00")
        _finalise(con, rid)
        row = con.execute("SELECT status, reported_at FROM receipts WHERE id=?",
                          (rid,)).fetchone()
        t.eq(row["status"], start, f"{start} unchanged by finalise")
        t.eq(row["reported_at"], "2020-01-01 00:00", f"{start}: reported_at not overwritten")

    # reported_at is STABLE across a second finalise (reprint must keep original)
    for start in ["pending", "in_progress"]:
        rid, item_id, _ = _mk_receipt(con, status=start)
        _finalise(con, rid)
        first = con.execute("SELECT reported_at FROM receipts WHERE id=?",
                           (rid,)).fetchone()["reported_at"]
        # tamper to a sentinel, re-finalise: WHERE status IN(pending,in_progress)
        # no longer matches, so the sentinel must survive
        con.execute("UPDATE receipts SET reported_at=? WHERE id=?",
                    ("1999-12-31 23:59", rid)); con.commit()
        _finalise(con, rid)
        again = con.execute("SELECT status, reported_at FROM receipts WHERE id=?",
                           (rid,)).fetchone()
        t.eq(again["status"], "reported", f"{start}: still reported on re-finalise")
        t.eq(again["reported_at"], "1999-12-31 23:59",
             f"{start}: reported_at stable across re-finalise")
        t.check(first is not None, f"{start}: first reported_at present")

    # =====================================================================
    # 3) multi-parameter result UPSERT persistence
    # =====================================================================
    t.section("multi-parameter result UPSERT persistence")
    rid, item_id, test_id = _mk_receipt(con, sex="Male")
    params = con.execute(
        "SELECT * FROM test_parameters WHERE test_id=? AND part_type='N' "
        "AND name IS NOT NULL AND name<>'' ORDER BY seq LIMIT 12", (test_id,)
    ).fetchall()
    t.check(len(params) >= 4, "fixture: enough N parameters to test")

    VALUES = ["1", "12.5", "0", "-3", "", "  ", "HIGH", "<0.1", "1,234",
              "9" * 50, "résumé✓", "3.14159265358979", "0.0001", "999999",
              "Not Detected", "  spaced  "]
    for p in params:
        for i, v in enumerate(VALUES):
            hidden = i % 2
            _save_param(con, item_id, p["id"], "Male", v, hidden)
            row = con.execute(
                "SELECT value, hidden, ref_text, name, units, seq, part_type "
                "FROM results WHERE receipt_item_id=? AND parameter_id=?",
                (item_id, p["id"]),
            ).fetchone()
            t.eq(row["value"], v, f"value persists p={p['id']} v={v!r}")
            t.eq(row["hidden"], hidden, f"hidden persists p={p['id']} v={v!r}")
            t.eq(row["ref_text"], resolve_ref(p, "Male"),
                 f"ref_text snapshot p={p['id']}")
            t.eq(row["name"], p["name"], f"name snapshot p={p['id']}")
            t.eq(row["seq"], p["seq"], f"seq snapshot p={p['id']}")
        # UPSERT must never create a duplicate row for the same parameter
        cnt = con.execute(
            "SELECT COUNT(*) FROM results WHERE receipt_item_id=? AND parameter_id=?",
            (item_id, p["id"]),
        ).fetchone()[0]
        t.eq(cnt, 1, f"exactly one row per parameter (no dup) p={p['id']}")

    # the last write wins after a long edit churn
    pid0 = params[0]["id"]
    for v in ["a", "b", "c", "FINAL"]:
        _save_param(con, item_id, pid0, "Male", v, 0)
    t.eq(con.execute("SELECT value FROM results WHERE receipt_item_id=? AND parameter_id=?",
                     (item_id, pid0)).fetchone()["value"], "FINAL",
         "last-write-wins on repeated UPSERT")

    # hidden flag toggles cleanly 0->1->0
    _save_param(con, item_id, pid0, "Male", "x", 1)
    t.eq(con.execute("SELECT hidden FROM results WHERE receipt_item_id=? AND parameter_id=?",
                     (item_id, pid0)).fetchone()["hidden"], 1, "hidden set to 1")
    _save_param(con, item_id, pid0, "Male", "x", 0)
    t.eq(con.execute("SELECT hidden FROM results WHERE receipt_item_id=? AND parameter_id=?",
                     (item_id, pid0)).fetchone()["hidden"], 0, "hidden cleared to 0")

    # ref_text re-resolves when the receipt sex differs (female fixture)
    rid_f, item_f, test_f = _mk_receipt(con, sex="Female")
    params_f = con.execute(
        "SELECT * FROM test_parameters WHERE test_id=? AND part_type='N' "
        "AND name IS NOT NULL AND name<>'' ORDER BY seq LIMIT 8", (test_f,)
    ).fetchall()
    for p in params_f:
        _save_param(con, item_f, p["id"], "Female", "1", 0)
        row = con.execute(
            "SELECT ref_text FROM results WHERE receipt_item_id=? AND parameter_id=?",
            (item_f, p["id"]),
        ).fetchone()
        t.eq(row["ref_text"], resolve_ref(p, "Female"),
             f"female ref_text snapshot p={p['id']}")
        # where male/female differ, female ref must NOT equal the male ref
        if (p["ref_male"] or "") != (p["ref_female"] or "") and (p["ref_female"] or ""):
            t.check(row["ref_text"] != (p["ref_male"] or ""),
                    f"female ref differs from male p={p['id']}")

    # =====================================================================
    # 4) single-line (parameter_id IS NULL) DELETE-then-INSERT
    # =====================================================================
    t.section("single-line result DELETE-then-INSERT (no duplicates)")
    rid_s, item_s, _ = _mk_receipt(con)
    for i, v in enumerate(VALUES + ["overwrite", "", "again"]):
        hidden = i % 2
        _save_single(con, item_s, v, hidden)
        rows = con.execute(
            "SELECT value, hidden, name FROM results "
            "WHERE receipt_item_id=? AND parameter_id IS NULL", (item_s,),
        ).fetchall()
        t.eq(len(rows), 1, f"single-line never duplicates v={v!r}")
        t.eq(rows[0]["value"], v, f"single-line value v={v!r}")
        t.eq(rows[0]["hidden"], hidden, f"single-line hidden v={v!r}")
        t.eq(rows[0]["name"], "Result", "single-line name defaults to 'Result'")

    # =====================================================================
    # 5) UNIQUE(receipt_item_id, parameter_id) constraint integrity
    # =====================================================================
    t.section("UNIQUE(item,parameter) constraint integrity")
    rid_u, item_u, test_u = _mk_receipt(con)
    pset = con.execute(
        "SELECT id FROM test_parameters WHERE test_id=? AND part_type='N' "
        "AND name IS NOT NULL AND name<>'' ORDER BY seq LIMIT 6", (test_u,)
    ).fetchall()
    for pr in pset:
        _save_param(con, item_u, pr["id"], "Male", "v1", 0)
    for pr in pset:
        _save_param(con, item_u, pr["id"], "Male", "v2", 1)  # second pass = update
    total = con.execute(
        "SELECT COUNT(*) FROM results WHERE receipt_item_id=?", (item_u,)
    ).fetchone()[0]
    t.eq(total, len(pset), "two passes never multiply rows (UNIQUE holds)")
    for pr in pset:
        t.eq(con.execute("SELECT value FROM results WHERE receipt_item_id=? "
                         "AND parameter_id=?", (item_u, pr["id"])).fetchone()["value"],
             "v2", f"second pass updated value p={pr['id']}")

    # a raw duplicate INSERT (no upsert) must be rejected by the constraint
    import sqlite3 as _sql
    rid_x, item_x, test_x = _mk_receipt(con)
    px = con.execute("SELECT id FROM test_parameters WHERE test_id=? AND part_type='N' "
                     "AND name IS NOT NULL AND name<>'' ORDER BY seq LIMIT 1",
                     (test_x,)).fetchone()["id"]
    con.execute("INSERT INTO results(receipt_item_id,parameter_id,value) VALUES(?,?,?)",
                (item_x, px, "a")); con.commit()
    raised = False
    try:
        con.execute("INSERT INTO results(receipt_item_id,parameter_id,value) VALUES(?,?,?)",
                    (item_x, px, "b"))
        con.commit()
    except _sql.IntegrityError:
        con.rollback(); raised = True
    t.check(raised, "raw duplicate (item,param) rejected by UNIQUE constraint")

    # =====================================================================
    # 6) full finalise flow: save results then advance status
    # =====================================================================
    t.section("finalise flow leaves results + reported status consistent")
    for sex in ["Male", "Female"]:
        for start in ["pending", "in_progress"]:
            rid_w, item_w, test_w = _mk_receipt(con, status=start, sex=sex)
            pw = con.execute(
                "SELECT * FROM test_parameters WHERE test_id=? AND part_type='N' "
                "AND name IS NOT NULL AND name<>'' ORDER BY seq LIMIT 5", (test_w,)
            ).fetchall()
            for p in pw:
                _save_param(con, item_w, p["id"], sex, "7", 0)
            _finalise(con, rid_w)
            r = con.execute("SELECT status, reported_at FROM receipts WHERE id=?",
                           (rid_w,)).fetchone()
            t.eq(r["status"], "reported", f"finalise flow status sex={sex} start={start}")
            t.check(r["reported_at"] is not None,
                    f"finalise flow reported_at sex={sex} start={start}")
            nres = con.execute("SELECT COUNT(*) FROM results WHERE receipt_item_id=?",
                              (item_w,)).fetchone()[0]
            t.eq(nres, len(pw), f"all params saved sex={sex} start={start}")
            for p in pw:
                t.eq(con.execute("SELECT value FROM results WHERE receipt_item_id=? "
                                "AND parameter_id=?", (item_w, p["id"])).fetchone()["value"],
                     "7", f"value persisted sex={sex} p={p['id']}")

    # =====================================================================
    # 7) report._flag invariants used by the live out-of-range cue
    # =====================================================================
    t.section("report._flag out-of-range classification")
    _flag = t.report._flag
    # range "10-20": below=Low, inside=Normal, above=High; boundaries inclusive
    RANGE = "10 - 20"
    CASES = [
        ("5", "Low"), ("9.999", "Low"), ("10", "Normal"), ("10.0", "Normal"),
        ("15", "Normal"), ("20", "Normal"), ("20.0", "Normal"),
        ("20.001", "High"), ("100", "High"),
    ]
    for v, label in CASES:
        fl = _flag(v, RANGE)
        t.check(fl is not None, f"_flag classifies v={v!r}")
        t.eq(fl[0], label, f"_flag {v!r} in {RANGE!r}")
    # off-by-one at the exact edges
    t.eq(_flag("10", RANGE)[0], "Normal", "_flag lower edge inclusive")
    t.eq(_flag("20", RANGE)[0], "Normal", "_flag upper edge inclusive")
    # open bounds: "< 200" high above, "> 5" low below
    t.eq(_flag("250", "< 200")[0], "High", "_flag < bound: above is High")
    t.eq(_flag("100", "< 200")[0], "Normal", "_flag < bound: below is Normal")
    t.eq(_flag("200", "< 200")[0], "Normal", "_flag < bound edge is Normal")
    t.eq(_flag("3", "> 5")[0], "Low", "_flag > bound: below is Low")
    t.eq(_flag("9", "> 5")[0], "Normal", "_flag > bound: above is Normal")
    t.eq(_flag("5", "> 5")[0], "Normal", "_flag > bound edge is Normal")
    # commas stripped, en-dash normalised
    t.eq(_flag("1,500", "100 - 200")[0], "High", "_flag strips comma")
    t.eq(_flag("15", "10 – 20")[0], "Normal", "_flag normalises en-dash")
    # non-numeric / empty / garbage ref -> None (no flag, no crash)
    for v in ["", "  ", "POS", "Negative", None, "abc"]:
        t.check(_flag(v, RANGE) is None, f"_flag non-numeric v={v!r} -> None")
    for ref in ["", None, "see comment", "positive"]:
        t.check(_flag("5", ref) is None, f"_flag garbage ref {ref!r} -> None")

    # =====================================================================
    # 8) worklist refresh_list query semantics (status + NOT_VOIDED filter)
    # =====================================================================
    t.section("worklist list query: status filter + voided exclusion")
    # build a known small cohort with distinct lab prefix
    tag = "WLQ"
    made = {}
    for st in ["pending", "in_progress", "reported", "delivered"]:
        pid = con.execute("INSERT INTO patients(name,sex) VALUES(?,?)",
                          (f"{tag} {st}", "Male")).lastrowid
        rid = con.execute(
            "INSERT INTO receipts(lab_no,patient_id,patient_name,sex,status,subtotal,"
            "net_amount,paid,due) VALUES(?,?,?,?,?,?,?,?,?)",
            (f"{tag}_{st}", pid, f"{tag} {st}", "Male", st, 0, 0, 0, 0),
        ).lastrowid
        made[st] = rid
    # one voided pending — must be excluded by NOT_VOIDED
    vpid = con.execute("INSERT INTO patients(name,sex) VALUES(?,?)",
                      (f"{tag} void", "Male")).lastrowid
    vrid = con.execute(
        "INSERT INTO receipts(lab_no,patient_id,patient_name,sex,status,voided,"
        "subtotal,net_amount,paid,due) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (f"{tag}_void", vpid, f"{tag} void", "Male", "pending", 1, 0, 0, 0, 0),
    ).lastrowid
    con.commit()

    def _list(status):
        sql = (f"SELECT id FROM receipts WHERE {t.db.NOT_VOIDED} "
               "AND (COALESCE(patient_name,'') LIKE ? OR COALESCE(lab_no,'') LIKE ?)")
        args = [f"%{tag}%", f"%{tag}%"]
        if status != "All":
            sql += " AND status=?"; args.append(status)
        sql += " ORDER BY id DESC LIMIT 500"
        return [r["id"] for r in con.execute(sql, args).fetchall()]

    for st in ["pending", "in_progress", "reported", "delivered"]:
        ids = _list(st)
        t.check(made[st] in ids, f"list status={st} includes its receipt")
        t.check(vrid not in ids, f"list status={st} excludes voided")
        for other in ["pending", "in_progress", "reported", "delivered"]:
            if other != st:
                t.check(made[other] not in ids,
                        f"list status={st} excludes status={other}")
    all_ids = _list("All")
    for st in ["pending", "in_progress", "reported", "delivered"]:
        t.check(made[st] in all_ids, f"list All includes {st}")
    t.check(vrid not in all_ids, "list All still excludes voided")
    # voided receipt with status=pending appears in NO status view
    t.check(vrid not in _list("pending"), "voided pending hidden from pending view")

    # =====================================================================
    # 9) remarks persistence on receipt_items (save_results writes these)
    # =====================================================================
    t.section("per-test remarks persistence (blank -> NULL)")
    rid_r, item_r, _ = _mk_receipt(con)
    for txt, want in [("Hemolysed sample", "Hemolysed sample"),
                      ("", None), ("   ", None), ("ok", "ok"),
                      ("x" * 500, "x" * 500), ("line1\nline2", "line1\nline2")]:
        norm = txt.strip()
        con.execute("UPDATE receipt_items SET remarks=? WHERE id=?",
                    (norm or None, item_r)); con.commit()
        got = con.execute("SELECT remarks FROM receipt_items WHERE id=?",
                         (item_r,)).fetchone()["remarks"]
        t.eq(got, want, f"remarks persist txt={txt!r}")
