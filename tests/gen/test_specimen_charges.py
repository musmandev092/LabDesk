"""Generator — specimen list + charge aggregation invariants.

Focus: a receipt's printed/stored subtotal must equal the sum of its line-item
charges (``sum(receipt_items.charge)``), and net/discount/paid/due must stay
internally consistent.  We build *multi-test* receipts (the shared
``t.make_receipt`` only makes single-item ones), then assert:

  * subtotal == sum(charge) over the items we inserted
  * net <= subtotal, discount == subtotal - net, due/change never both > 0
  * the rendered cash receipt (report.build_receipt_html) prints the same
    subtotal / discount / net / paid / due figures
  * specimen string handling: None/empty render as the em-dash placeholder,
    real / unicode / HTML-injection / very-long strings are escaped & present
  * amount-in-words tracks the *net* (rounded)

Contract: one register(t); assertions only via t.check/t.eq/t.near/t.has.
Network + DB are isolated by run_gen.py.  ~1500+ cases.
"""
from __future__ import annotations

import html
import re


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _two(n):
    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
            "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
            "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy",
            "Eighty", "Ninety"]
    if n < 20:
        return ones[n]
    return (tens[n // 10] + ((" " + ones[n % 10]) if n % 10 else "")).strip()


def _three(n):
    h, r = divmod(n, 100)
    out = ""
    if h:
        out = _two(h) + " Hundred"
    if r:
        out = (out + " " + _two(r)).strip()
    return out.strip()


def _words(amount):
    """Independent reimplementation of report._amount_in_words for cross-check."""
    n = round(amount or 0)
    if n == 0:
        return "Zero Rupees Only"
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    if crore:
        parts.append(_two(crore) + " Crore")
    if lakh:
        parts.append(_two(lakh) + " Lakh")
    if thousand:
        parts.append(_two(thousand) + " Thousand")
    if n:
        parts.append(_three(n))
    return " ".join(parts).strip() + " Rupees Only"


_PID = [0]


def _build(con, *, charges, specimen, disc_pct=0.0, paid=None, status="reported",
           sex="Male", age=30, phone="03001234567"):
    """Insert a multi-item receipt; return (rid, subtotal, net, paid, due).

    subtotal is stored as the true sum of the supplied charges (the invariant
    under test).  net = subtotal*(1-disc/100).  paid defaults to net.
    """
    _PID[0] += 1
    pid = con.execute(
        "INSERT INTO patients(name,age,age_desc,sex,telephone) VALUES (?,?,?,?,?)",
        ("Agg Patient", age, "Years", sex, phone),
    ).lastrowid
    subtotal = round(sum(charges), 2)
    net = round(max(0.0, subtotal - subtotal * disc_pct / 100.0), 2)
    if paid is None:
        paid = net
    due = round(max(0.0, net - paid), 2)
    rid = con.execute(
        """INSERT INTO receipts(lab_no,patient_id,patient_name,age,age_desc,sex,
                                telephone,dr_name,specimen,subtotal,discount_pct,
                                net_amount,paid,due,status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (f"LAB_AGG_{_PID[0]:05d}", pid, "Agg Patient", age, "Years", sex, phone,
         "Dr. Agg", specimen, subtotal, disc_pct, net, paid, due, status),
    ).lastrowid
    tid = con.execute(
        "SELECT id FROM tests WHERE active=1 ORDER BY id LIMIT 1"
    ).fetchone()[0]
    for i, ch in enumerate(charges):
        con.execute(
            "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) VALUES (?,?,?,?)",
            (rid, tid, f"Test {i+1}", ch),
        )
    con.commit()
    return rid, subtotal, net, paid, due


def _sum_charges(con, rid):
    row = con.execute(
        "SELECT COALESCE(SUM(charge),0) FROM receipt_items WHERE receipt_id=?", (rid,)
    ).fetchone()
    return row[0]


def _money(x):
    return f"{x:,.2f}"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def register(t):
    con = t.con

    # =====================================================================
    # 1. subtotal == sum(receipt_items.charge) over many multi-test receipts
    # =====================================================================
    t.section("subtotal == sum(charge) for multi-test receipts")
    CHARGE_SETS = [
        [0.0],
        [100.0],
        [100.0, 250.0],
        [100.0, 250.0, 500.0],
        [50.0, 50.0, 50.0, 50.0],
        [0.0, 0.0, 1000.0],
        [333.33, 666.67],
        [12.5, 12.5, 75.0],
        [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
        [99999.99, 0.01],
        [1234567.89],
        [250.0] * 8,
        [0.0, 0.0, 0.0],
        [5000.0, 2500.0, 1250.0, 625.0],
        [10.10, 20.20, 30.30],
    ]
    DISCS = [0.0, 10.0, 25.0, 50.0, 100.0]
    for charges in CHARGE_SETS:
        for disc in DISCS:
            rid, sub, net, paid, due = _build(con, charges=charges,
                                              specimen="Whole Blood", disc_pct=disc)
            got = _sum_charges(con, rid)
            t.near(got, sub, f"sum(charge)==subtotal charges={charges} disc={disc}")
            t.eq(con.execute("SELECT COUNT(*) FROM receipt_items WHERE receipt_id=?",
                             (rid,)).fetchone()[0], len(charges),
                 f"item count charges={charges}")
            # core money invariants
            t.check(net <= sub + 1e-9, f"net<=sub charges={charges} disc={disc}")
            # half-cent rounding (banker's rounding on .5) can differ by 0.01
            t.near(round(sub - net, 2), round(sub * disc / 100.0, 2),
                   f"discount==sub-net charges={charges} disc={disc}", tol=0.011)
            t.check(due >= -1e-9, f"due>=0 charges={charges} disc={disc}")
            t.check(0.0 <= net <= sub + 1e-9, f"net bounds charges={charges} disc={disc}")

    # =====================================================================
    # 2. net / paid / due / change consistency across payment levels
    # =====================================================================
    t.section("net / paid / due / change consistency")
    for charges in CHARGE_SETS[:10]:
        sub_true = round(sum(charges), 2)
        for disc in [0.0, 20.0, 50.0]:
            net_true = round(max(0.0, sub_true - sub_true * disc / 100.0), 2)
            for paid in [0.0, net_true / 2 if net_true else 0.0, net_true,
                         net_true + 100.0, net_true + 1000.0]:
                rid, sub, net, p, due = _build(con, charges=charges,
                                              specimen="Serum", disc_pct=disc, paid=paid)
                change = round(max(0.0, p - net), 2)
                t.near(_sum_charges(con, rid), sub,
                       f"sum==sub paid={paid} charges={charges}")
                t.check(not (due > 1e-6 and change > 1e-6),
                        f"never due AND change paid={paid} disc={disc}")
                if paid >= net:
                    t.check(due < 1e-6,
                            f"no due when paid>=net paid={paid} net={net}")
                    t.near(change, round(paid - net, 2),
                           f"change paid={paid} net={net}", tol=0.01)
                else:
                    t.near(due, round(net - paid, 2),
                           f"due paid={paid} net={net}", tol=0.01)
                    t.check(change < 1e-6,
                            f"no change when underpaid paid={paid} net={net}")

    # =====================================================================
    # 3. rendered cash receipt prints subtotal / discount / net / paid / due
    # =====================================================================
    t.section("build_receipt_html prints aggregated money")
    for charges in CHARGE_SETS:
        for disc in [0.0, 15.0, 100.0]:
            for paid_mode in ("exact", "over", "under"):
                rid, sub, net, _, _ = _build(con, charges=charges,
                                            specimen="Plasma", disc_pct=disc)
                if paid_mode == "exact":
                    paid = net
                elif paid_mode == "over":
                    paid = net + 500.0
                else:
                    paid = round(net / 2, 2)
                due = round(max(0.0, net - paid), 2)
                con.execute("UPDATE receipts SET paid=?, due=? WHERE id=?",
                            (paid, due, rid))
                con.commit()
                html_doc = t.report.build_receipt_html(con, rid)
                discount = round(sub - net, 2)
                # every line item charge must appear in the rendered table
                for ch in charges:
                    t.has(html_doc, _money(ch),
                          f"charge {ch} in receipt charges={charges}")
                # totals block figures
                t.has(html_doc, f"Total:</td><td class='val'>{_money(sub)}",
                      f"Total line sub={sub} disc={disc}")
                t.has(html_doc, f"Discount:</td><td class='val'>{_money(discount)}",
                      f"Discount line disc={disc} sub={sub}")
                t.has(html_doc, f"{_money(net)}</td>",
                      f"net printed net={net} sub={sub}")
                t.has(html_doc, f"Paid:</td><td class='val'>{_money(paid)}",
                      f"Paid line paid={paid}")
                # amount-in-words tracks the NET, not subtotal
                t.has(html_doc, html.escape(_words(net)),
                      f"amount-in-words(net) net={net}")
                # change line only appears when overpaid
                change = round(max(0.0, paid - net), 2)
                if change > 0:
                    t.has(html_doc, "Change returned",
                          f"change row present paid={paid} net={net}")
                else:
                    t.check("Change returned" not in html_doc,
                            f"no change row paid={paid} net={net}")

    # =====================================================================
    # 4. specimen string handling
    # =====================================================================
    t.section("specimen string handling (escape / None / unicode / long)")
    SPECIMENS = [
        ("Whole Blood", True),
        ("3cc EDTA", True),
        ("Serum / Plasma", True),
        ("Urine (24h)", True),
        ("CSF", True),
        ("Stool – random", True),         # en-dash unicode
        ("نمونہ خون", True),               # urdu unicode
        ("Swab #1 & #2", True),           # ampersand -> must be escaped
        ("<b>blood</b>", True),           # html injection -> must be escaped
        ("A" * 300, True),                # very long
        ("  Sputum  ", True),
        ("Blood\nClot", True),
        ("Tissue \"biopsy\"", True),
        ("100% specimen", True),
    ]
    for spec, present in SPECIMENS:
        rid, *_ = _build(con, charges=[200.0, 300.0], specimen=spec)
        # stored verbatim
        stored = con.execute("SELECT specimen FROM receipts WHERE id=?",
                             (rid,)).fetchone()[0]
        t.eq(stored, spec, f"specimen stored verbatim spec={spec[:20]!r}")
        # rendered (lab report carries the Specimen patient-card field)
        rep = t.report.build_report_html(con, rid)
        t.has(rep, "Specimen", f"Specimen label present spec={spec[:20]!r}")
        if present:
            esc = html.escape(spec)
            t.has(rep, esc, f"specimen escaped&present spec={spec[:20]!r}")
        # raw < / > / & must never leak unescaped into the report
        t.check("<b>blood</b>" not in rep if spec == "<b>blood</b>" else True,
                "html-injected specimen is escaped")
        t.check("Swab #1 & #2" not in rep if spec == "Swab #1 & #2" else True,
                "ampersand specimen is escaped (&amp;)")

    # None / empty specimen -> em-dash placeholder, never a crash
    t.section("specimen None/empty -> em-dash placeholder")
    for spec in [None, "", "   "]:
        rid, *_ = _build(con, charges=[150.0], specimen=spec)
        rep = t.report.build_report_html(con, rid)
        rcpt = t.report.build_receipt_html(con, rid)
        t.has(rep, "Specimen", f"Specimen label present even when blank spec={spec!r}")
        # blank values render as the placeholder em-dash in the patient card
        if spec is None or spec == "":
            t.has(rep, "—", f"em-dash placeholder for blank specimen spec={spec!r}")
        t.check(len(rcpt) > 0, f"receipt builds with blank specimen spec={spec!r}")

    # =====================================================================
    # 5. boundary / extreme charge aggregation
    # =====================================================================
    t.section("boundary & extreme charges")
    # empty receipt: no items -> subtotal must equal 0 sum, receipt still builds
    rid, sub, net, paid, due = _build(con, charges=[], specimen="None")
    t.near(_sum_charges(con, rid), 0.0, "empty receipt sum(charge)==0")
    t.eq(con.execute("SELECT COUNT(*) FROM receipt_items WHERE receipt_id=?",
                     (rid,)).fetchone()[0], 0, "empty receipt has 0 items")
    rcpt = t.report.build_receipt_html(con, rid)
    t.check(len(rcpt) > 0, "empty receipt renders")
    rep = t.report.build_report_html(con, rid)
    t.has(rep, "No tests on this receipt", "empty report shows no-tests note")

    # single huge charge & many tiny charges sum exactly
    BIG = [
        [10_000_000.0],
        [1e6, 1e6, 1e6],
        [0.01] * 100,
        [9_999_999.99, 0.01],
        list(range(1, 51)),            # 1..50 -> sum 1275
        [7.77] * 13,
    ]
    for charges in BIG:
        charges = [float(c) for c in charges]
        rid, sub, *_ = _build(con, charges=charges, specimen="Bulk")
        t.near(_sum_charges(con, rid), round(sum(charges), 2),
               f"big-sum charges n={len(charges)} sum={sum(charges)}", tol=0.5)
        t.eq(con.execute("SELECT COUNT(*) FROM receipt_items WHERE receipt_id=?",
                         (rid,)).fetchone()[0], len(charges),
             f"big item count n={len(charges)}")

    # adding/removing items keeps the sum invariant tracked by re-query
    t.section("incremental add keeps sum(charge) == running total")
    rid, sub, *_ = _build(con, charges=[100.0], specimen="Inc")
    tid = con.execute("SELECT id FROM tests WHERE active=1 ORDER BY id LIMIT 1").fetchone()[0]
    running = 100.0
    for extra in [50.0, 0.0, 250.5, 999.99, 1.0, 0.01]:
        con.execute(
            "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) VALUES (?,?,?,?)",
            (rid, tid, "Extra", extra),
        )
        con.commit()
        running = round(running + extra, 2)
        t.near(_sum_charges(con, rid), running,
               f"running sum after +{extra} -> {running}", tol=0.01)

    # removing items decrements the sum
    items = con.execute("SELECT id,charge FROM receipt_items WHERE receipt_id=? ORDER BY id DESC",
                        (rid,)).fetchall()
    for it in items:
        con.execute("DELETE FROM receipt_items WHERE id=?", (it["id"],))
        con.commit()
        running = round(running - it["charge"], 2)
        t.near(_sum_charges(con, rid), running,
               f"running sum after delete -> {running}", tol=0.01)
    t.near(_sum_charges(con, rid), 0.0, "all items removed -> sum 0")

    # =====================================================================
    # 6. amount-in-words tracks net (rounded) for a spread of nets
    # =====================================================================
    t.section("amount-in-words(net) on rendered receipt")
    for charges in [[0.0], [1.0], [99.0], [100.0], [999.0], [1000.0], [1500.0],
                    [12345.0], [100000.0], [9999999.0], [250.0, 250.0],
                    [333.0, 333.0, 334.0]]:
        rid, sub, net, *_ = _build(con, charges=charges, specimen="Words")
        rcpt = t.report.build_receipt_html(con, rid)
        t.has(rcpt, html.escape(_words(net)),
              f"words(net) net={net} charges={charges}")
        # never the subtotal's words when discount differs (here disc=0 so equal,
        # but the rounding path must use net)
        t.has(rcpt, "Rupees Only", f"words suffix present net={net}")
