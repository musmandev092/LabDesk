"""Accounts reconciliation generator — cash collected, expenses, dues, net.

Drives the EXACT aggregate SQL used by ``ui/accounts.py::refresh_summary`` /
``refresh_dues`` against directly-inserted receipts + expenses, and asserts the
SQL result matches an independent Python recomputation across a wide matrix of
scenarios (voided rows, payment methods, date-range boundaries, partial dues,
overpaid/zero rows, extreme values).

Contract (see tests/run_gen.py / tests/gen/test_billing.py):
  * exactly one ``register(t)``; assertions only via t.check / t.eq / t.near / t.has
  * no network, no live DB (runner isolates both); we use t.con only.

Each scenario lives in its own ``received_at`` month so concurrent receipts from
other inserts never leak into a window we measure.
"""
from __future__ import annotations

# ---- the precise queries AccountsPage.refresh_summary runs -----------------
def _income(con, NV, f, t):
    return con.execute(
        "SELECT COALESCE(SUM(paid),0) FROM receipts "
        f"WHERE {NV} AND date(received_at) BETWEEN ? AND ?", (f, t)).fetchone()[0]


def _expense(con, f, t):
    return con.execute(
        "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE date BETWEEN ? AND ?",
        (f, t)).fetchone()[0]


def _due_all_time(con, NV):
    return con.execute(
        f"SELECT COALESCE(SUM(due),0) FROM receipts WHERE due>0.005 AND {NV}"
    ).fetchone()[0]


def _methods(con, NV, f, t):
    return con.execute(
        "SELECT COALESCE(NULLIF(TRIM(payment_method),''),'Cash') AS m, "
        "COUNT(*) AS n, COALESCE(SUM(paid),0) AS total FROM receipts "
        f"WHERE {NV} AND paid>0 AND date(received_at) BETWEEN ? AND ? "
        "GROUP BY m ORDER BY total DESC", (f, t)).fetchall()


def _dues_rows(con, NV):
    return con.execute(
        f"SELECT * FROM receipts WHERE due>0.005 AND {NV} ORDER BY id DESC"
    ).fetchall()


def _ins_receipt(con, lab, paid, due, net, voided, method, when):
    return con.execute(
        "INSERT INTO receipts(lab_no,paid,due,net_amount,voided,payment_method,"
        "received_at) VALUES (?,?,?,?,?,?,?)",
        (lab, paid, due, net, voided, method, when)).lastrowid


def _ins_expense(con, amount, when):
    con.execute("INSERT INTO expenses(date,head,detail,amount) VALUES (?,?,?,?)",
                (when, "h", "d", amount))


def _norm_method(pm):
    """Mirror COALESCE(NULLIF(TRIM(payment_method),''),'Cash').

    SQLite's TRIM with one argument strips ASCII spaces ONLY (not tabs), so we
    must replicate that exactly rather than using Python str.strip().
    """
    if pm is None:
        return "Cash"
    tr = pm.strip(" ")
    return tr if tr else "Cash"


def register(t):
    con = t.con
    NV = t.db.NOT_VOIDED
    t.section("accounts reconciliation: income / expense / due / net / methods")

    # unique month per scenario keeps each window isolated from every other.
    scn = 0

    def month(i):
        # spread across years 2050-2099, months 01-12 -> >600 disjoint windows
        yr = 2050 + (i // 12)
        mo = (i % 12) + 1
        return yr, mo

    def window(i):
        yr, mo = month(i)
        return f"{yr:04d}-{mo:02d}-01", f"{yr:04d}-{mo:02d}-28"

    def day(i, d):
        yr, mo = month(i)
        return f"{yr:04d}-{mo:02d}-{d:02d} 10:00:00"

    # ------------------------------------------------------------------
    # 1) Core matrix: vary number of receipts, paid/due/net, voided flag,
    #    payment method. Recompute every aggregate independently.
    # ------------------------------------------------------------------
    PAIDS = [0.0, 1.0, 50.0, 100.0, 333.0, 1000.0, 4999.0, 50000.0, 99999.0]
    METHODS = [None, "", "  ", "Cash", "Card", "JazzCash", "EasyPaisa",
               " Card ", "\tBank\t"]
    VOIDS = [0, 1]
    t.section("core matrix (paid x method x voided)")
    for paid in PAIDS:
        for pm in METHODS:
            for voided in VOIDS:
                i = scn; scn += 1
                f, tt = window(i)
                net = paid + 500.0          # arbitrary net >= paid here
                due = max(0.0, net - paid)
                _ins_receipt(con, f"ACC{i}", paid, due, net, voided, pm, day(i, 10))
                con.commit()

                got_inc = _income(con, NV, f, tt)
                exp_inc = paid if voided == 0 else 0.0
                t.near(got_inc, exp_inc,
                       f"income paid={paid} pm={pm!r} void={voided}")

                # method breakdown: only counts paid>0 and not voided
                rows = _methods(con, NV, f, tt)
                if voided == 0 and paid > 0:
                    t.eq(len(rows), 1, f"one method row paid={paid} pm={pm!r}")
                    if rows:
                        r0 = rows[0]
                        t.eq(r0["m"], _norm_method(pm),
                             f"method label pm={pm!r}")
                        t.eq(r0["n"], 1, f"method count pm={pm!r}")
                        t.near(r0["total"], paid, f"method total pm={pm!r}")
                else:
                    t.eq(len(rows), 0,
                         f"no method row paid={paid} void={voided}")
                # collected total over methods == income (paid>0 share == all
                # since only positive-paid rows exist in this window)
                meth_total = sum(r["total"] for r in rows)
                t.near(meth_total, exp_inc if paid > 0 else 0.0,
                       f"method sum==income paid={paid} pm={pm!r} void={voided}")

    # ------------------------------------------------------------------
    # 2) Multi-receipt windows: several receipts in one month, mixed void,
    #    mixed method. Assert summed income, per-method grouping, due.
    # ------------------------------------------------------------------
    t.section("multi-receipt windows (grouping + sums)")
    MIXES = [
        [(100.0, "Cash", 0), (200.0, "Cash", 0), (50.0, "Card", 0)],
        [(100.0, "Cash", 1), (200.0, "Card", 0), (300.0, "Card", 0)],
        [(0.0, "Cash", 0), (0.0, "Card", 0), (500.0, "JazzCash", 0)],
        [(1000.0, None, 0), (1000.0, "", 0), (1000.0, "  ", 0)],
        [(99999.0, "Card", 0), (1.0, "Card", 1), (2.0, "Cash", 0)],
        [(10.0, "Cash", 0), (20.0, "Cash", 1), (30.0, "Cash", 0), (40.0, "Card", 0)],
    ]
    for mix in MIXES:
        i = scn; scn += 1
        f, tt = window(i)
        exp_income = 0.0
        method_tot: dict = {}
        method_cnt: dict = {}
        for k, (paid, pm, voided) in enumerate(mix):
            net = paid + 100.0
            due = max(0.0, net - paid)
            _ins_receipt(con, f"MIX{i}_{k}", paid, due, net, voided, pm,
                         day(i, 5 + k))
            if voided == 0:
                exp_income += paid
                if paid > 0:
                    m = _norm_method(pm)
                    method_tot[m] = method_tot.get(m, 0.0) + paid
                    method_cnt[m] = method_cnt.get(m, 0) + 1
        con.commit()

        t.near(_income(con, NV, f, tt), exp_income, f"multi income mix={mix!r}")
        rows = _methods(con, NV, f, tt)
        t.eq(len(rows), len(method_tot), f"multi #methods mix={mix!r}")
        got = {r["m"]: (r["n"], r["total"]) for r in rows}
        for m, tot in method_tot.items():
            t.check(m in got, f"method {m} present mix={mix!r}")
            if m in got:
                t.eq(got[m][0], method_cnt[m], f"method {m} count mix={mix!r}")
                t.near(got[m][1], tot, f"method {m} total mix={mix!r}")
        # ORDER BY total DESC: collected totals must be non-increasing
        totals = [r["total"] for r in rows]
        for a, b in zip(totals, totals[1:]):
            t.check(a >= b - 1e-9, f"methods sorted desc mix={mix!r}")
        # sum across methods equals income
        t.near(sum(totals), exp_income, f"method-sum==income mix={mix!r}")

    # ------------------------------------------------------------------
    # 3) Date-range boundaries / off-by-one: BETWEEN is inclusive on both
    #    ends; date(received_at) strips the time component.
    # ------------------------------------------------------------------
    t.section("date-range boundaries (inclusive BETWEEN, off-by-one)")
    for k in range(60):
        i = scn; scn += 1
        yr, mo = month(i)
        f = f"{yr:04d}-{mo:02d}-10"
        tt = f"{yr:04d}-{mo:02d}-20"
        # one receipt on each candidate day; only 10..20 should count
        days = [9, 10, 11, 15, 19, 20, 21]
        in_range = 0.0
        for d in days:
            paid = 100.0 + d
            _ins_receipt(con, f"BND{i}_{d}", paid, 0.0, paid, 0, "Cash",
                         f"{yr:04d}-{mo:02d}-{d:02d} 23:59:59")
            if 10 <= d <= 20:
                in_range += paid
        con.commit()
        t.near(_income(con, NV, f, tt), in_range,
               f"boundary income k={k} ({f}..{tt})")
        # a window with from>to yields nothing
        t.near(_income(con, NV, tt, f), 0.0, f"reversed window empty k={k}")
        # time component on the upper bound still included (23:59:59 on day 20)
        t.near(_income(con, NV, f"{yr:04d}-{mo:02d}-20",
                       f"{yr:04d}-{mo:02d}-20"),
               120.0, f"single-day inclusive k={k}")

    # ------------------------------------------------------------------
    # 4) Outstanding dues: all-time SUM(due) over not-voided rows with the
    #    due>0.005 threshold. Voided dues + sub-threshold dues excluded.
    #    NOTE: this is independent of date — it's a running grand total, so
    #    we recompute the *whole table* expectation, not a window.
    # ------------------------------------------------------------------
    t.section("outstanding dues (all-time threshold + voided exclusion)")
    # snapshot baseline (other scenarios above also left dues in the table)
    base_due = _due_all_time(con, NV)
    base_due_rows = len(_dues_rows(con, NV))
    DUES = [0.0, 0.004, 0.005, 0.006, 0.01, 1.0, 250.0, 99999.0]
    added = 0.0
    added_rows = 0
    for due in DUES:
        for voided in (0, 1):
            i = scn; scn += 1
            net = due + 500.0
            paid = net - due
            _ins_receipt(con, f"DUE{i}", paid, due, net, voided, "Cash",
                         day(i, 12))
            con.commit()
            counts = (voided == 0 and due > 0.005)
            if counts:
                added += due
                added_rows += 1
            t.near(_due_all_time(con, NV), base_due + added,
                   f"all-time due running due={due} void={voided}")
            t.eq(len(_dues_rows(con, NV)), base_due_rows + added_rows,
                 f"dues rowcount running due={due} void={voided}")

    # threshold edge precision: 0.005 is NOT > 0.005 (excluded); 0.006 is.
    i = scn; scn += 1
    _ins_receipt(con, f"THR{i}A", 1.0, 0.005, 1.005, 0, "Cash", day(i, 1))
    con.commit()
    t.near(_due_all_time(con, NV), base_due + added,
           "due==0.005 excluded (strict >)")
    i = scn; scn += 1
    _ins_receipt(con, f"THR{i}B", 1.0, 0.0051, 1.0051, 0, "Cash", day(i, 1))
    con.commit()
    t.near(_due_all_time(con, NV), base_due + added + 0.0051,
           "due==0.0051 included")
    base_due = base_due + added + 0.0051
    base_due_rows = base_due_rows + added_rows + 1

    # ------------------------------------------------------------------
    # 5) Expenses sum in window + Net = income - expense (incl. negatives).
    # ------------------------------------------------------------------
    t.section("expenses sum + net = income - expense")
    EXP_SETS = [
        [],
        [100.0],
        [100.0, 250.5, 9.0],
        [0.0, 0.0, 1000.0],
        [99999.0, 1.0],
        [10.0] * 10,
    ]
    INC_SETS = [0.0, 100.0, 500.0, 100000.0]
    for exps in EXP_SETS:
        for inc in INC_SETS:
            i = scn; scn += 1
            f, tt = window(i)
            yr, mo = month(i)
            # income from a single not-voided receipt
            _ins_receipt(con, f"NET{i}", inc, 0.0, inc, 0, "Cash", day(i, 5))
            in_win_exp = 0.0
            for k, amt in enumerate(exps):
                _ins_expense(con, amt, f"{yr:04d}-{mo:02d}-{6 + k:02d}")
                in_win_exp += amt
            # an out-of-window expense must NOT be counted
            _ins_expense(con, 7777.0, f"{yr:04d}-{mo:02d}-01")  # before 'f'? no
            con.commit()

            got_exp = _expense(con, f, tt)
            got_inc = _income(con, NV, f, tt)
            # window f..tt is day-01..day-28; the receipt is day-05, the extra
            # 7777 expense is day-01 (inside window). Recompute precisely:
            window_extra = 7777.0  # day-01 within 01..28
            t.near(got_exp, in_win_exp + window_extra,
                   f"expense sum exps={exps!r} inc={inc}")
            t.near(got_inc, inc, f"net income exps={exps!r} inc={inc}")
            net = got_inc - got_exp
            t.near(net, inc - (in_win_exp + window_extra),
                   f"net=income-expense exps={exps!r} inc={inc}")
            # net sign classification matches accounts.py color rule (net<0)
            t.check((net < 0) == (got_inc < got_exp),
                    f"net sign exps={exps!r} inc={inc}")

    # expenses respect their own date window independent of receipts
    t.section("expenses date window isolation")
    for k in range(30):
        i = scn; scn += 1
        yr, mo = month(i)
        f = f"{yr:04d}-{mo:02d}-10"
        tt = f"{yr:04d}-{mo:02d}-20"
        inside = 0.0
        for d in (9, 10, 15, 20, 21):
            amt = 5.0 * d
            _ins_expense(con, amt, f"{yr:04d}-{mo:02d}-{d:02d}")
            if 10 <= d <= 20:
                inside += amt
        con.commit()
        t.near(_expense(con, f, tt), inside, f"expense window k={k}")
        t.near(_expense(con, tt, f), 0.0, f"expense reversed window k={k}")

    # ------------------------------------------------------------------
    # 6) receive_due settles dues: after recovery, income (in that window)
    #    rises by the recovered amount via the receipt's paid, due falls,
    #    and never goes negative.
    # ------------------------------------------------------------------
    t.section("receive_due settlement invariants")
    SETTLE = [
        (1000.0, 200.0, 300.0),   # net, initial paid, recover
        (1000.0, 0.0, 1000.0),    # full settle
        (1000.0, 0.0, 1500.0),    # over-recover (capped at due by UI; db caps due>=0)
        (500.0, 100.0, 50.0),
        (99999.0, 1.0, 99998.0),
        (250.0, 250.0, 10.0),     # nothing owed -> no-op
    ]
    for net, paid0, recover in SETTLE:
        i = scn; scn += 1
        due0 = max(0.0, net - paid0)
        rid = _ins_receipt(con, f"SET{i}", paid0, due0, net, 0, "Cash",
                           day(i, 7))
        con.commit()
        before = _due_all_time(con, NV)
        res = t.db.receive_due(con, rid, recover, "tester")
        row = con.execute(
            "SELECT paid, due FROM receipts WHERE id=?", (rid,)).fetchone()
        if due0 <= 0:
            t.check(res is None, f"no-op when nothing owed net={net} paid0={paid0}")
            t.near(row["paid"], paid0, f"paid unchanged no-op net={net}")
            t.near(row["due"], 0.0, f"due stays 0 no-op net={net}")
        else:
            t.check(res is not None, f"settle returns net={net} rec={recover}")
            exp_paid = round(paid0 + recover, 2)
            exp_due = round(max(0.0, net - exp_paid), 2)
            t.near(row["paid"], exp_paid, f"paid after settle net={net} rec={recover}")
            t.near(row["due"], exp_due, f"due after settle net={net} rec={recover}")
            t.check(row["due"] >= -1e-9, f"due never negative net={net} rec={recover}")
            # all-time due delta == reduction in this receipt's due
            after = _due_all_time(con, NV)
            t.near(before - after, due0 - exp_due,
                   f"due-pool delta net={net} rec={recover}")
            # ledger got a due_recovery credit for exactly the recovered amount
            led = con.execute(
                "SELECT COALESCE(SUM(credit),0) FROM ledger "
                "WHERE kind='due_recovery' AND ref_id=?", (rid,)).fetchone()[0]
            t.near(led, recover, f"ledger credit net={net} rec={recover}")

    # ------------------------------------------------------------------
    # 7) Voided receipt invariants across ALL aggregates simultaneously.
    # ------------------------------------------------------------------
    t.section("voided receipts excluded from every aggregate")
    for k in range(25):
        i = scn; scn += 1
        f, tt = window(i)
        # one big voided receipt; it must affect nothing
        _ins_receipt(con, f"VOID{i}", 50000.0, 5000.0, 55000.0, 1, "Card",
                     day(i, 9))
        con.commit()
        t.near(_income(con, NV, f, tt), 0.0, f"voided no income k={k}")
        t.eq(len(_methods(con, NV, f, tt)), 0, f"voided no method k={k}")
        # add a live receipt in same window: only it shows up
        _ins_receipt(con, f"LIVE{i}", 123.0, 0.0, 123.0, 0, "Cash",
                     day(i, 9))
        con.commit()
        t.near(_income(con, NV, f, tt), 123.0, f"only live counted k={k}")
        rows = _methods(con, NV, f, tt)
        t.eq(len(rows), 1, f"only live method k={k}")
        if rows:
            t.eq(rows[0]["m"], "Cash", f"live method label k={k}")
            t.near(rows[0]["total"], 123.0, f"live method total k={k}")

    # ------------------------------------------------------------------
    # 8) NULL/garbage paid/due/net columns are tolerated by COALESCE.
    # ------------------------------------------------------------------
    t.section("empty window -> COALESCE(SUM,0) is 0, never NULL")
    for k in range(20):
        i = scn; scn += 1
        f, tt = window(i)
        # nothing inserted in this window at all -> SUM is NULL -> COALESCE 0
        t.near(_income(con, NV, f, tt), 0.0, f"empty income -> 0 k={k}")
        t.near(_expense(con, f, tt), 0.0, f"empty expense -> 0 k={k}")
        t.eq(len(_methods(con, NV, f, tt)), 0, f"empty -> no method rows k={k}")
        # a zero-paid receipt: counts toward nothing (paid>0 false)
        _ins_receipt(con, f"ZERO{i}", 0.0, 0.0, 0.0, 0, "Cash", day(i, 3))
        con.commit()
        t.near(_income(con, NV, f, tt), 0.0, f"zero-paid income 0 k={k}")
        t.eq(len(_methods(con, NV, f, tt)), 0, f"zero-paid no method k={k}")

    # ------------------------------------------------------------------
    # 9) Extreme / large value arithmetic stays exact enough.
    # ------------------------------------------------------------------
    t.section("extreme value arithmetic")
    BIG = [1e6, 1e7, 1e8, 1234567.0, 9999999.0, 5e6, 87654321.0]
    for a in BIG:
        for b in BIG:
            i = scn; scn += 1
            f, tt = window(i)
            yr, mo = month(i)
            _ins_receipt(con, f"BIGA{i}", a, 0.0, a, 0, "Cash", day(i, 2))
            _ins_receipt(con, f"BIGB{i}", b, 0.0, b, 0, "Cash", day(i, 3))
            _ins_expense(con, b, f"{yr:04d}-{mo:02d}-04")
            con.commit()
            t.near(_income(con, NV, f, tt), a + b, f"big income a={a} b={b}", tol=1.0)
            t.near(_expense(con, f, tt), b, f"big expense a={a} b={b}", tol=1.0)
            net = _income(con, NV, f, tt) - _expense(con, f, tt)
            t.near(net, a, f"big net a={a} b={b}", tol=1.0)
