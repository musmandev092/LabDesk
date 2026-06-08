"""Generator — audit hash-chain integrity (db.log_audit / verify_audit_chain /
rechain_audit).

Invariants exercised (against the isolated runner DB / con):
  * a freshly-appended run of entries verifies clean: verify_audit_chain -> (True, None)
  * each row's hash == sha256("|".join(prev, at, user, action, detail))
  * tampering ANY field (username/action/detail) of a row flips verify to
    (False, that_row_id) — and the FIRST altered row is the one reported
  * rechain_audit repairs a tampered/gapped chain back to (True, None)
  * deleting a middle row is detected as a gap at the row that followed it
  * log_audit truncates user/action to 64 and detail to 500 chars
  * log_audit "never raises" on None / falsy junk (per its docstring)

Everything runs headless against t.con — no network, no live DB.

NOTE: several cases for non-string junk to log_audit are EXPECTED-PASS only if
the app upholds its "Never raises" docstring. They currently expose a real bug
(see returned app_bugs); those assertions are intentionally kept failing.
"""
from __future__ import annotations

import hashlib


def _expect_hash(prev, at, username, action, detail):
    return hashlib.sha256(
        "|".join([prev, at or "", username or "", action or "", detail or ""]).encode("utf-8")
    ).hexdigest()


def _segment(t, tag, n, *, user="u", action="act", detail="d"):
    """Append n entries tagged uniquely, return the list of their row ids (in order)."""
    con = t.con
    before = con.execute("SELECT COALESCE(MAX(id),0) FROM audit_log").fetchone()[0]
    for i in range(n):
        t.db.log_audit(con, f"{user}-{tag}-{i}", f"{action}-{tag}", f"{detail}-{tag}-{i}")
    rows = con.execute(
        "SELECT id FROM audit_log WHERE id>? ORDER BY id", (before,)
    ).fetchall()
    return [r[0] if not hasattr(r, "keys") else r["id"] for r in rows]


def register(t):
    con = t.con

    # ------------------------------------------------------------------
    # 1) Append a large run and verify the chain row-by-row.
    # ------------------------------------------------------------------
    t.section("append + per-row hash recomputation")
    N = 400
    ids = _segment(t, "main", N)
    t.eq(len(ids), N, "append count")

    ok, bad = t.db.verify_audit_chain(con)
    t.check(ok, "fresh chain verifies clean")
    t.eq(bad, None, "fresh chain has no bad id")

    # Recompute the rolling hash independently over the WHOLE table and confirm
    # every row matches what verify_audit_chain expects. This is the core
    # invariant: hash == sha256(prev | at | user | action | detail).
    rows = con.execute(
        "SELECT id, at, username, action, detail, hash FROM audit_log ORDER BY id"
    ).fetchall()
    prev = ""
    for r in rows:
        if r["hash"] is None:
            continue
        exp = _expect_hash(prev, r["at"], r["username"], r["action"], r["detail"])
        t.eq(r["hash"], exp, f"row {r['id']} hash matches recomputation")
        prev = r["hash"]
    # hashes are 64-hex chars
    for r in rows:
        if r["hash"] is not None:
            t.eq(len(r["hash"]), 64, f"row {r['id']} hash len 64")
            t.check(all(c in "0123456789abcdef" for c in r["hash"]),
                    f"row {r['id']} hash is lowercase hex")
    # the chain links: every row's hash feeds the next row's recomputation —
    # so no two adjacent rows can carry the same hash unless they collide (won't).
    hashes = [r["hash"] for r in rows if r["hash"] is not None]
    t.eq(len(hashes), len(set(hashes)), "all chained hashes are distinct")

    # ------------------------------------------------------------------
    # 2) Tamper detection — alter ONE field of ONE row, expect (False, id),
    #    then restore + re-verify clean. Sweep many positions & all 3 fields.
    # ------------------------------------------------------------------
    t.section("single-field tamper detection across positions")

    def _orig(row_id):
        r = con.execute(
            "SELECT at, username, action, detail FROM audit_log WHERE id=?", (row_id,)
        ).fetchone()
        return dict(at=r["at"], username=r["username"], action=r["action"], detail=r["detail"])

    # pick a spread of positions: first chained row, several middles, last row
    positions = sorted(set([
        ids[0], ids[1], ids[len(ids) // 4], ids[len(ids) // 2],
        ids[3 * len(ids) // 4], ids[-2], ids[-1],
    ]))
    for target in positions:
        for field in ("username", "action", "detail"):
            saved = _orig(target)
            con.execute(
                f"UPDATE audit_log SET {field}=? WHERE id=?",
                ("TAMPER-" + field, target),
            )
            con.commit()
            ok, bad = t.db.verify_audit_chain(con)
            t.check(not ok, f"tamper {field}@{target} detected (not ok)")
            # the FIRST broken row is the tampered one itself
            t.eq(bad, target, f"tamper {field}@{target} reports the tampered row")
            # restore
            con.execute(
                f"UPDATE audit_log SET {field}=? WHERE id=?", (saved[field], target)
            )
            con.commit()
            ok2, bad2 = t.db.verify_audit_chain(con)
            t.check(ok2, f"restore {field}@{target} re-verifies clean")
            t.eq(bad2, None, f"restore {field}@{target} no bad id")

    # ------------------------------------------------------------------
    # 3) Tamper the HASH column directly (the tamper-evidence value itself).
    #    Verify must flag the mutated row.
    # ------------------------------------------------------------------
    t.section("hash-column tamper detection")
    for target in positions:
        saved = con.execute(
            "SELECT hash FROM audit_log WHERE id=?", (target,)
        ).fetchone()["hash"]
        con.execute("UPDATE audit_log SET hash=? WHERE id=?", ("deadbeef" * 8, target))
        con.commit()
        ok, bad = t.db.verify_audit_chain(con)
        t.check(not ok, f"hash tamper@{target} detected")
        t.eq(bad, target, f"hash tamper@{target} reports that row")
        con.execute("UPDATE audit_log SET hash=? WHERE id=?", (saved, target))
        con.commit()
        ok2, bad2 = t.db.verify_audit_chain(con)
        t.check(ok2, f"hash restore@{target} clean")
        t.eq(bad2, None, f"hash restore@{target} no bad id")

    # NULLing a hash mid-chain (after chaining started) is a gap/tamper.
    for target in [ids[len(ids) // 3], ids[-3]]:
        saved = con.execute(
            "SELECT hash FROM audit_log WHERE id=?", (target,)
        ).fetchone()["hash"]
        con.execute("UPDATE audit_log SET hash=NULL WHERE id=?", (target,))
        con.commit()
        ok, bad = t.db.verify_audit_chain(con)
        t.check(not ok, f"NULL hash mid-chain@{target} detected")
        t.eq(bad, target, f"NULL hash mid-chain@{target} reports that row")
        con.execute("UPDATE audit_log SET hash=? WHERE id=?", (saved, target))
        con.commit()
        ok2, _ = t.db.verify_audit_chain(con)
        t.check(ok2, f"NULL hash restore@{target} clean")

    # ------------------------------------------------------------------
    # 4) Rechain repairs an arbitrarily-tampered chain.
    # ------------------------------------------------------------------
    t.section("rechain repairs tamper")
    for field in ("username", "action", "detail"):
        target = ids[len(ids) // 2]
        con.execute(
            f"UPDATE audit_log SET {field}=? WHERE id=?", ("BROKEN-" + field, target)
        )
        con.commit()
        ok, bad = t.db.verify_audit_chain(con)
        t.check(not ok, f"pre-rechain {field} broken")
        t.eq(bad, target, f"pre-rechain {field} bad id is target")
        t.db.rechain_audit(con)
        ok2, bad2 = t.db.verify_audit_chain(con)
        t.check(ok2, f"rechain repaired {field} tamper")
        t.eq(bad2, None, f"rechain {field} no bad id")
        # rechain over an unchanged table is idempotent (still clean)
        t.db.rechain_audit(con)
        ok3, _ = t.db.verify_audit_chain(con)
        t.check(ok3, f"rechain idempotent after {field}")

    # rechain makes the stored hashes equal a fresh independent recomputation
    t.db.rechain_audit(con)
    rows = con.execute(
        "SELECT id, at, username, action, detail, hash FROM audit_log ORDER BY id"
    ).fetchall()
    prev = ""
    for r in rows:
        exp = _expect_hash(prev, r["at"], r["username"], r["action"], r["detail"])
        t.eq(r["hash"], exp, f"post-rechain row {r['id']} matches recomputation")
        prev = r["hash"]

    # ------------------------------------------------------------------
    # 5) Gap detection — delete a MIDDLE row; the row that followed it now
    #    chains from the wrong prev and must be flagged. Sweep many positions.
    # ------------------------------------------------------------------
    t.section("middle-row deletion -> gap detected at successor")
    gap_ids = _segment(t, "gap", 120)
    t.db.rechain_audit(con)  # ensure a clean baseline before each deletion test
    ok, _ = t.db.verify_audit_chain(con)
    t.check(ok, "gap segment baseline clean")

    # Deleting a middle row breaks the chain at the *next* surviving row.
    # We test on a snapshot: delete one row, capture detection, then rechain
    # to restore a verifiable chain for the next iteration.
    victims = [gap_ids[k] for k in (10, 30, 60, 90, len(gap_ids) - 2)]
    for victim in victims:
        # find the next surviving id after victim across the whole table
        succ = con.execute(
            "SELECT MIN(id) FROM audit_log WHERE id>?", (victim,)
        ).fetchone()[0]
        con.execute("DELETE FROM audit_log WHERE id=?", (victim,))
        con.commit()
        ok, bad = t.db.verify_audit_chain(con)
        t.check(not ok, f"deletion@{victim} detected as gap")
        t.eq(bad, succ, f"deletion@{victim} flagged at successor {succ}")
        # rechain over the survivors re-establishes a clean chain
        t.db.rechain_audit(con)
        ok2, bad2 = t.db.verify_audit_chain(con)
        t.check(ok2, f"rechain after deletion@{victim} clean")
        t.eq(bad2, None, f"rechain after deletion@{victim} no bad id")

    # Deleting the LAST row never breaks the chain (nothing chains from it).
    last_id = con.execute("SELECT MAX(id) FROM audit_log").fetchone()[0]
    con.execute("DELETE FROM audit_log WHERE id=?", (last_id,))
    con.commit()
    ok, bad = t.db.verify_audit_chain(con)
    t.check(ok, "deleting the last row keeps chain valid")
    t.eq(bad, None, "deleting last row -> no bad id")

    # ------------------------------------------------------------------
    # 6) Truncation invariants — user/action capped at 64, detail at 500.
    # ------------------------------------------------------------------
    t.section("field truncation (64 / 64 / 500)")
    for ulen, alen, dlen in [(63, 63, 499), (64, 64, 500), (65, 80, 501),
                             (200, 200, 2000), (1000, 1000, 5000)]:
        before = con.execute("SELECT COALESCE(MAX(id),0) FROM audit_log").fetchone()[0]
        t.db.log_audit(con, "U" * ulen, "A" * alen, "D" * dlen)
        r = con.execute(
            "SELECT username, action, detail FROM audit_log WHERE id>? ORDER BY id LIMIT 1",
            (before,),
        ).fetchone()
        t.eq(len(r["username"]), min(ulen, 64), f"username truncated @ {ulen}")
        t.eq(len(r["action"]), min(alen, 64), f"action truncated @ {alen}")
        t.eq(len(r["detail"]), min(dlen, 500), f"detail truncated @ {dlen}")
    # truncation does not break the chain
    ok, _ = t.db.verify_audit_chain(con)
    t.check(ok, "chain still clean after truncation writes")

    # ------------------------------------------------------------------
    # 7) "Never raises" — log_audit must tolerate None and odd-but-safe input.
    #    These reflect the documented contract; each must NOT raise.
    # ------------------------------------------------------------------
    t.section("log_audit tolerates None / falsy / empty input without raising")
    safe_inputs = [
        ("", "", ""),
        (None, None, None),
        (None, "act", "detail"),
        ("user", None, "detail"),
        ("user", "act", None),
        ("", "act", ""),
        ("u", "a", ""),
        ("emoji \U0001F600", "act", "detail ☃"),
        ("with|pipe", "a|b", "x|y|z"),                 # delimiter in the data
        ("newline\nhere", "tab\there", "null\x00byte"),
        ("quote'\"q", "back\\slash", "%percent%"),
        ("0", "0", "0"),
        ("   ", "   ", "   "),
    ]
    for u, a, d in safe_inputs:
        before = con.execute("SELECT COALESCE(MAX(id),0) FROM audit_log").fetchone()[0]
        raised = False
        try:
            t.db.log_audit(con, u, a, d)
        except Exception:
            raised = True
        t.check(not raised, f"log_audit no-raise for ({u!r},{a!r},{d!r})")
        after = con.execute("SELECT COALESCE(MAX(id),0) FROM audit_log").fetchone()[0]
        # a successful safe call must have appended exactly one row
        t.check(after > before, f"log_audit appended a row for ({u!r},{a!r},{d!r})")
    # the chain remains valid even with pipe/newline/null data embedded
    ok, bad = t.db.verify_audit_chain(con)
    t.check(ok, "chain valid after delimiter-laden / unicode details")
    t.eq(bad, None, "no bad id after delimiter-laden details")

    # data with embedded '|' must still round-trip (chain uses '|'.join but the
    # SAME join in verify, so it stays consistent — assert that explicitly).
    before = con.execute("SELECT COALESCE(MAX(id),0) FROM audit_log").fetchone()[0]
    t.db.log_audit(con, "a|b", "c|d", "e|f|g")
    r = con.execute(
        "SELECT username, action, detail FROM audit_log WHERE id>? ORDER BY id LIMIT 1",
        (before,),
    ).fetchone()
    t.eq(r["username"], "a|b", "pipe in username stored verbatim")
    t.eq(r["action"], "c|d", "pipe in action stored verbatim")
    t.eq(r["detail"], "e|f|g", "pipe in detail stored verbatim")

    # ------------------------------------------------------------------
    # 8) "Never raises" for NON-STRING junk — the docstring says this must not
    #    raise. Falsy junk (0, False, [], {}, (), b'') is normalized to "".
    #    Truthy non-sliceable junk (int, float, True, dict-with-keys, object,
    #    date) currently ESCAPES the try/except and RAISES — that is a real bug
    #    in db.log_audit (the (x or "")[:64] normalization sits OUTSIDE the
    #    try). We keep these assertions failing to flag it.
    # ------------------------------------------------------------------
    t.section("log_audit must not raise on junk types (docstring: 'Never raises')")
    import datetime as _dt

    junk_values = [
        0, False, [], {}, (), b"",          # falsy -> normalized to "" (pass today)
        1, 1.5, True, {"k": 1}, ["x"],       # truthy assorted
        (1, 2), b"bytes", object(), _dt.date(2020, 1, 1), 3.0,
    ]
    for jv in junk_values:
        for slot in range(3):
            args = ["user", "act", "detail"]
            args[slot] = jv
            raised = False
            try:
                t.db.log_audit(con, args[0], args[1], args[2])
            except Exception:
                raised = True
            t.check(not raised,
                    f"log_audit must not raise on junk {type(jv).__name__} in slot {slot}")

    # whatever survived above, the chain over the survivors must still verify
    t.db.rechain_audit(con)
    ok, bad = t.db.verify_audit_chain(con)
    t.check(ok, "chain clean after junk-tolerance sweep + rechain")
    t.eq(bad, None, "no bad id after junk-tolerance sweep")

    # ------------------------------------------------------------------
    # 9) Append-after-repair: the chain keeps growing correctly post-rechain.
    # ------------------------------------------------------------------
    t.section("append continues to chain correctly after a rechain")
    cont = _segment(t, "post", 80)
    t.eq(len(cont), 80, "post-rechain append count")
    ok, bad = t.db.verify_audit_chain(con)
    t.check(ok, "post-rechain appends verify clean")
    t.eq(bad, None, "post-rechain appends no bad id")
    # each new row links to the immediately preceding row's hash
    rows = con.execute(
        "SELECT id, at, username, action, detail, hash FROM audit_log ORDER BY id"
    ).fetchall()
    prev = ""
    for r in rows:
        if r["hash"] is None:
            continue
        exp = _expect_hash(prev, r["at"], r["username"], r["action"], r["detail"])
        t.eq(r["hash"], exp, f"final sweep row {r['id']} chains from prev")
        prev = r["hash"]
