"""Generator — due-recovery invariants for db.receive_due.

Source under test: src/labdesk/db.py :: receive_due(con, receipt_id, amount, username)

Contract recap (read from source):
  * returns None when the receipt is missing, nothing is owed (due falsy/<=0),
    or amount <= 0 — and in that case nothing is written.
  * otherwise:  new_paid = round((paid or 0) + amount, 2)
                new_due  = round(max(0.0, (net_amount or 0) - new_paid), 2)
    writes a 'due_recovery' ledger credit (= amount), updates receipts.paid/due,
    appends a 'due_received' audit entry, and returns (lab_no, new_paid, new_due).

Invariants asserted here:
  * due never goes negative
  * paid strictly accumulates by exactly `amount`
  * overpayment is absorbed (due clamps to 0; paid can exceed net)
  * exact payment zeroes the due
  * each successful call writes exactly one ledger credit and one audit row
  * sequential partial payments converge and never over/under-shoot
  * guard paths (no due, zero/negative amount, garbage receipt id) write nothing
"""
from __future__ import annotations


def _ledger_state(t, rid):
    row = t.con.execute(
        "SELECT COALESCE(SUM(credit),0), COUNT(*) FROM ledger "
        "WHERE ref_id=? AND kind='due_recovery'", (rid,)).fetchone()
    return float(row[0]), int(row[1])


def _audit_count(t, lab_no=None):
    if lab_no is None:
        return t.con.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action='due_received'").fetchone()[0]
    return t.con.execute(
        "SELECT COUNT(*) FROM audit_log WHERE action='due_received' AND detail LIKE ?",
        (f"%{lab_no}%",)).fetchone()[0]


def register(t):
    t.section("due recovery: receive_due paid/due/ledger/audit invariants")

    SUBS = [0, 1, 50, 100, 250, 333.33, 800, 1000, 1250, 4999, 5000, 99999, 123456.78]
    # paid as a fraction-ish of sub so we span fully-paid, partly-paid, unpaid
    PAID_FRACS = [0.0, 0.25, 0.5, 0.75, 1.0]

    # ---- single-payment matrix -------------------------------------------
    for sub in SUBS:
        for frac in PAID_FRACS:
            paid0 = round(sub * frac, 2)
            # make_receipt stores due UNROUNDED as max(0, sub - paid); mirror that.
            due0 = max(0.0, sub - paid0)
            # payment amounts: partial, exact, over, plus boundary garbage
            if due0 > 0:
                AMTS = [due0 / 3, due0 / 2, due0, due0 + 1, due0 + 500,
                        sub + 1000, 0, -1, -9999]
            else:
                AMTS = [1, 100, 0, -5]
            for amt in AMTS:
                rid = t.make_receipt(sub=sub, paid=paid0, with_results=False)
                base_credit, base_cnt = _ledger_state(t, rid)
                base_audit = _audit_count(t)
                res = t.db.receive_due(t.con, rid, amt, "tester")
                row = t.con.execute(
                    "SELECT lab_no, net_amount, paid, due FROM receipts WHERE id=?",
                    (rid,)).fetchone()
                cur_credit, cur_cnt = _ledger_state(t, rid)
                cur_audit = _audit_count(t)

                should_apply = due0 > 0 and amt > 0
                if not should_apply:
                    # guard path: nothing changes anywhere
                    t.check(res is None,
                            f"no-op returns None sub={sub} paid={paid0} amt={amt}")
                    t.eq(row["paid"], paid0,
                         f"no-op leaves paid sub={sub} paid={paid0} amt={amt}")
                    t.eq(row["due"], due0,
                         f"no-op leaves due sub={sub} paid={paid0} amt={amt}")
                    t.eq(cur_cnt, base_cnt,
                         f"no-op writes no ledger sub={sub} amt={amt}")
                    t.eq(cur_audit, base_audit,
                         f"no-op writes no audit sub={sub} amt={amt}")
                    continue

                # applied path -------------------------------------------------
                exp_paid = round(paid0 + amt, 2)
                exp_due = round(max(0.0, sub - exp_paid), 2)
                t.check(res is not None,
                        f"applied returns tuple sub={sub} paid={paid0} amt={amt}")
                t.eq(res[0], row["lab_no"],
                     f"returns lab_no sub={sub} amt={amt}")
                t.near(res[1], exp_paid,
                       f"returns new_paid sub={sub} paid={paid0} amt={amt}")
                t.near(res[2], exp_due,
                       f"returns new_due sub={sub} paid={paid0} amt={amt}")
                t.near(row["paid"], exp_paid,
                       f"paid accumulated sub={sub} paid={paid0} amt={amt}")
                t.near(row["due"], exp_due,
                       f"due recomputed sub={sub} paid={paid0} amt={amt}")
                # core invariant: due never negative
                t.check(row["due"] >= -1e-9,
                        f"due>=0 sub={sub} paid={paid0} amt={amt}")
                # paid grew to round(paid0 + amt, 2)
                t.near(row["paid"], round(paid0 + amt, 2),
                       f"paid delta == amt sub={sub} paid={paid0} amt={amt}")
                # over/exact payment clamps due to zero
                if amt >= due0 - 1e-9:
                    t.near(row["due"], 0.0,
                           f"overpay clamps due to 0 sub={sub} paid={paid0} amt={amt}")
                    if amt > due0 + 1e-9:
                        t.check(row["paid"] > sub - 1e-9,
                                f"overpay paid exceeds net sub={sub} amt={amt}")
                else:
                    t.check(row["due"] > 0,
                            f"partial leaves due sub={sub} paid={paid0} amt={amt}")
                # exactly one ledger credit of `amt`
                t.eq(cur_cnt, base_cnt + 1,
                     f"one ledger row sub={sub} amt={amt}")
                # ledger stores the RAW amount (no rounding in receive_due)
                t.near(cur_credit - base_credit, amt,
                       f"ledger credit == amt sub={sub} amt={amt}", tol=1e-6)
                # exactly one audit row appended
                t.eq(cur_audit, base_audit + 1,
                     f"one audit row sub={sub} amt={amt}")
                # audit references this lab_no
                t.check(_audit_count(t, row["lab_no"]) >= 1,
                        f"audit names lab_no sub={sub} amt={amt}")

    # ---- sequential partial payments converge ----------------------------
    t.section("due recovery: sequential partial payments converge")
    SEQ_SUBS = [100, 1000, 1250, 4999, 99999]
    SPLITS = [
        [10, 10, 10],            # leaves a due
        [100, 100, 100],         # exact-ish across rounds
        [250, 250, 250, 250],    # exact for 1000
        [333.33, 333.33, 333.34],
        [500, 600],              # overshoot on last
        [1, 1, 1, 1, 1],         # tiny dribbles
    ]
    for sub in SEQ_SUBS:
        for splits in SPLITS:
            rid = t.make_receipt(sub=sub, paid=0.0, with_results=False)
            running_paid = 0.0
            for amt in splits:
                row0 = t.con.execute(
                    "SELECT due FROM receipts WHERE id=?", (rid,)).fetchone()
                due_before = row0["due"]
                res = t.db.receive_due(t.con, rid, amt, "tester")
                row = t.con.execute(
                    "SELECT paid, due FROM receipts WHERE id=?", (rid,)).fetchone()
                if due_before <= 0 or amt <= 0:
                    t.check(res is None,
                            f"seq no-op None sub={sub} amt={amt}")
                    continue
                running_paid = round(running_paid + amt, 2)
                t.near(row["paid"], running_paid,
                       f"seq paid accumulates sub={sub} splits={splits} amt={amt}")
                t.near(row["due"], round(max(0.0, sub - running_paid), 2),
                       f"seq due tracks sub={sub} splits={splits} amt={amt}")
                t.check(row["due"] >= -1e-9,
                        f"seq due>=0 sub={sub} splits={splits} amt={amt}")
                # monotonic: due never increases across a payment
                t.check(row["due"] <= due_before + 1e-9,
                        f"seq due monotone sub={sub} splits={splits} amt={amt}")
            # after a sequence whose sum >= sub, due must be zero
            if sum(splits) >= sub:
                final = t.con.execute(
                    "SELECT due FROM receipts WHERE id=?", (rid,)).fetchone()["due"]
                t.near(final, 0.0,
                       f"seq fully paid -> due 0 sub={sub} splits={splits}")
            # ledger rows count == number of effective (applied) payments
            applied = 0
            d = sub
            for amt in splits:
                if d > 0 and amt > 0:
                    applied += 1
                    d = max(0.0, round(d - amt, 2))
            _, cnt = _ledger_state(t, rid)
            t.eq(cnt, applied,
                 f"seq ledger count == applied sub={sub} splits={splits}")

    # ---- guard paths: missing receipt / fully-paid receipt ---------------
    t.section("due recovery: guard paths")
    # garbage / nonexistent receipt ids
    for bad in [-1, 0, 999999999, 2 ** 31]:
        a0 = _audit_count(t)
        res = t.db.receive_due(t.con, bad, 100, "tester")
        t.check(res is None, f"missing receipt id={bad} -> None")
        t.eq(_audit_count(t), a0, f"missing receipt id={bad} writes no audit")

    # fully-paid receipt (due==0): every amount is a no-op
    for amt in [1, 100, 5000, 0, -10]:
        rid = t.make_receipt(sub=1000, paid=1000.0, with_results=False)
        _, c0 = _ledger_state(t, rid)
        res = t.db.receive_due(t.con, rid, amt, "tester")
        row = t.con.execute(
            "SELECT paid, due FROM receipts WHERE id=?", (rid,)).fetchone()
        t.check(res is None, f"paid-in-full no-op amt={amt}")
        t.eq(row["paid"], 1000.0, f"paid-in-full paid unchanged amt={amt}")
        t.eq(row["due"], 0.0, f"paid-in-full due stays 0 amt={amt}")
        _, c1 = _ledger_state(t, rid)
        t.eq(c1, c0, f"paid-in-full no ledger amt={amt}")

    # ---- extreme / fractional precision ----------------------------------
    t.section("due recovery: precision & extremes")
    PREC = [
        (100.0, 33.33), (100.0, 66.67), (0.01, 0.01), (0.03, 0.01),
        (1e6, 0.01), (1e9, 1e9 - 1), (12345.67, 12345.67),
        (1000.0, 999.99), (1000.0, 1000.01),
    ]
    for sub, amt in PREC:
        rid = t.make_receipt(sub=sub, paid=0.0, with_results=False)
        res = t.db.receive_due(t.con, rid, amt, "tester")
        row = t.con.execute(
            "SELECT paid, due FROM receipts WHERE id=?", (rid,)).fetchone()
        if sub <= 0 or amt <= 0:
            t.check(res is None, f"prec no-op sub={sub} amt={amt}")
            continue
        exp_paid = round(amt, 2)
        exp_due = round(max(0.0, sub - exp_paid), 2)
        t.near(row["paid"], exp_paid, f"prec paid sub={sub} amt={amt}")
        t.near(row["due"], exp_due, f"prec due sub={sub} amt={amt}")
        t.check(row["due"] >= -1e-9, f"prec due>=0 sub={sub} amt={amt}")
        # rounding to 2dp keeps values stable
        t.near(round(row["paid"], 2), row["paid"],
               f"prec paid 2dp sub={sub} amt={amt}")
        t.near(round(row["due"], 2), row["due"],
               f"prec due 2dp sub={sub} amt={amt}")
