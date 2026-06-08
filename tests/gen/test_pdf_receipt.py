"""Generator — cash-receipt rendering (PDF bytes + HTML content).

Focus: src/labdesk/report.py
  * build_receipt_bytes(con, rid)  -> native QPdf bytes (must be a valid PDF)
  * build_receipt_html(con, rid)   -> HTML used for content tests

We drive many receipt variants (subtotal / discount→net / paid / due, item
counts, currency, NULL money columns, extreme values, multi-item charge sums)
and assert:
  * the PDF bytes start with %PDF and are non-trivially sized
  * the totals panel renders Total / Discount / To-Be-Paid / Paid / Balance with
    the exact ``:,.2f`` formatting of the stored amounts
  * "Change returned" appears iff paid > net, with the right value
  * the amount-in-words box reflects ``net`` (not subtotal), rounded
  * each per-item Rate cell carries the formatted charge

These are real INVARIANTS keyed off independently-computed expected strings, so a
regression in the receipt builder makes them FAIL.

Assertions only via t.check / t.eq / t.near / t.has.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Independent reference for amount-in-words (mirrors report._amount_in_words'
# *intended* Pakistani numbering). Used to confirm the words box value.
# ---------------------------------------------------------------------------
_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
         "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
         "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n):
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + ((" " + _ONES[n % 10]) if n % 10 else "")).strip()


def _three(n):
    out = ""
    if n >= 100:
        out = _ONES[n // 100] + " Hundred"
        n %= 100
        if n:
            out += " "
    return (out + _two(n)).strip()


def _ref_words(amount):
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


def _money(x):
    """Exactly how report.py formats a money cell: ``f'{x:,.2f}'``."""
    return f"{(x or 0):,.2f}"


def register(t):
    con = t.con
    _seq = [0]

    def _lab():
        _seq[0] += 1
        return f"L_GEN_{_seq[0]:06d}"

    def mk(sub, net, paid, due=None, *, charges=None, status="reported",
           created_by=None, cur=None):
        """Insert a self-contained receipt with explicit money columns and item
        charges, so net != subtotal (real discounts) can be exercised — which
        t.make_receipt cannot do (it forces net == subtotal)."""
        if due is None:
            due = max(0.0, (net or 0) - (paid or 0))
        if charges is None:
            charges = [sub]
        pid = con.execute(
            "INSERT INTO patients(name,age,age_desc,sex,telephone) "
            "VALUES ('Pt',30,'Years','Male','03001234567')"
        ).lastrowid
        rid = con.execute(
            """INSERT INTO receipts(lab_no,patient_id,patient_name,age,age_desc,sex,
                                    telephone,dr_name,specimen,subtotal,net_amount,paid,
                                    due,status,created_by)
               VALUES (?,?,'Pt',30,'Years','Male','03001234567','Dr','S',
                       ?,?,?,?,?,?)""",
            (_lab(), pid, sub, net, paid, due, status, created_by),
        ).lastrowid
        tid = con.execute(
            "SELECT test_id FROM test_parameters GROUP BY test_id LIMIT 1"
        ).fetchone()[0]
        tname = con.execute("SELECT name FROM tests WHERE id=?", (tid,)).fetchone()[0]
        for j, ch in enumerate(charges):
            con.execute(
                "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) "
                "VALUES (?,?,?,?)",
                (rid, tid, f"{tname} #{j+1}" if len(charges) > 1 else tname, ch),
            )
        con.commit()
        return rid

    def assert_totals(rid, sub, net, paid, due, *, label):
        """Core panel assertions against independently-computed expected text."""
        h = t.report.build_receipt_html(con, rid)
        b = t.report.build_receipt_bytes(con, rid)
        # --- PDF validity ---
        t.check(b[:4] == b"%PDF", f"{label}: PDF magic")
        t.check(len(b) > 1000, f"{label}: PDF size>1k ({len(b)}B)")
        # --- totals panel exact text ---
        discount = (sub or 0) - (net or 0)
        change = max(0.0, (paid or 0) - (net or 0))
        t.has(h, f"Total:</td><td class='val'>{_money(sub)}", f"{label}: Total cell")
        t.has(h, f"Discount:</td><td class='val'>{_money(discount)}",
              f"{label}: Discount cell")
        t.has(h, f"To Be Paid:</td><td class='val'>Rs. {_money(net)}",
              f"{label}: ToBePaid cell")
        t.has(h, f"Paid:</td><td class='val'>{_money(paid)}", f"{label}: Paid cell")
        t.has(h, f"Balance:</td>", f"{label}: Balance row")
        t.check(f"Rs. {_money(due)}" in h, f"{label}: Balance value {_money(due)}")
        # --- change returned: present iff overpaid ---
        if change > 0:
            t.has(h, "Change returned", f"{label}: change shown")
            t.check(f"Change returned:</td><td class='val' style='color:#059669;'>"
                    f"Rs. {_money(change)}" in h, f"{label}: change value {_money(change)}")
        else:
            t.check("Change returned" not in h, f"{label}: no change line")
        # --- amount in words = net (rounded), not subtotal ---
        t.has(h, f"<i>{t.report._amount_in_words(net)}</i>", f"{label}: words=net")
        t.eq(t.report._amount_in_words(net), _ref_words(net), f"{label}: words ref-match")
        # words must NOT be of subtotal when net differs by enough to change words
        if _ref_words(net) != _ref_words(sub):
            t.check(f"<i>{_ref_words(sub)}</i>" not in h,
                    f"{label}: words not subtotal")
        # --- structural ---
        t.has(h, "Cash Receipt", f"{label}: title")
        t.check(h.startswith("<!DOCTYPE html>"), f"{label}: doctype")
        t.check(h.rstrip().endswith("</html>"), f"{label}: closes html")
        t.has(h, "Amount in words", f"{label}: words label")

    # =====================================================================
    # 1) Discount / net / paid / due matrix (the heart of the panel)
    # =====================================================================
    t.section("totals panel: discount / net / paid / due matrix")
    SUBS = [0, 50, 100, 250, 333, 800, 1250, 4999, 5000, 99999]
    DISCS = [0, 5, 10, 12.5, 20, 33, 50, 100]
    n = 0
    for sub in SUBS:
        for disc in DISCS:
            net = round(max(0.0, sub - sub * disc / 100.0), 2)
            for paid in [0, round(net / 2, 2), net, net + 1, net + 500]:
                due = max(0.0, net - paid)
                assert_totals(mk(sub, net, paid, due), sub, net, paid, due,
                              label=f"matrix sub={sub} disc={disc} paid={paid}")
                n += 1
    t.section(f"  (matrix emitted {n} receipts)")

    # =====================================================================
    # 2) Exact balance vs change boundary (paid around net)
    # =====================================================================
    t.section("balance / change boundary around net")
    for net in [0, 1, 100, 999.99, 1000, 1234.56, 50000]:
        for d in [-2, -1, -0.01, 0, 0.01, 1, 2, 500]:
            paid = round(max(0.0, net + d), 2)
            due = max(0.0, net - paid)
            change = max(0.0, paid - net)
            rid = mk(net, net, paid, due)
            h = t.report.build_receipt_html(con, rid)
            # exactly one of due / change is positive (never both)
            t.check(not (due > 1e-6 and change > 1e-6),
                    f"boundary not both net={net} d={d}")
            if change > 0:
                t.has(h, "Change returned", f"boundary change net={net} d={d}")
            else:
                t.check("Change returned" not in h,
                        f"boundary no-change net={net} d={d}")

    # =====================================================================
    # 3) Amount-in-words tracks NET across landmark values
    # =====================================================================
    t.section("amount-in-words box reflects net")
    WORD_NETS = [0, 1, 19, 20, 100, 101, 1000, 1500, 99999, 100000,
                 123456, 1000000, 9999999, 10000000, 12345678]
    for net in WORD_NETS:
        rid = mk(net, net, net, 0.0)
        h = t.report.build_receipt_html(con, rid)
        t.has(h, f"<i>{_ref_words(net)}</i>", f"words-box net={net}")
        t.eq(t.report._amount_in_words(net), _ref_words(net), f"words-fn net={net}")
    # fractional net rounds in the words box (round() banker's)
    for net, words in [(99.5, "One Hundred"), (1000.49, "One Thousand"),
                       (0.6, "One Rupees"), (0.4, "Zero Rupees")]:
        rid = mk(net, net, net, 0.0)
        h = t.report.build_receipt_html(con, rid)
        t.has(h, words, f"words-frac net={net}")

    # =====================================================================
    # 4) Multi-item receipts: each charge rendered, Sr. numbering, count
    # =====================================================================
    t.section("multi-item charge cells")
    ITEM_SETS = [
        [100.0],
        [100.0, 250.0],
        [0.0, 0.0, 0.0],
        [12.5, 999.99, 5000.0, 33.0],
        [50.0] * 10,
        [123456.78, 1.0],
    ]
    for charges in ITEM_SETS:
        total = round(sum(charges), 2)
        rid = mk(total, total, total, 0.0, charges=charges)
        h = t.report.build_receipt_html(con, rid)
        b = t.report.build_receipt_bytes(con, rid)
        t.check(b[:4] == b"%PDF", f"multi PDF n={len(charges)}")
        # every charge appears formatted in a right-aligned rate cell
        for ch in charges:
            t.has(h, f"class='tr'>{_money(ch)}</td>", f"multi rate {ch} n={len(charges)}")
        # Sr. numbers 1..N present
        for i in range(len(charges)):
            t.has(h, f"class='tc'>{i+1}</td>", f"multi sr {i+1} n={len(charges)}")
        # one <tr> per item in the items table region
        body = h[h.find("class='items'"):h.find("class='summary'")]
        t.eq(body.count("<tr>"), len(charges) + 1,  # +1 for header row
             f"multi row count n={len(charges)}")

    # =====================================================================
    # 5) NULL / missing money columns must render as 0.00 (never crash)
    # =====================================================================
    t.section("NULL money columns -> 0.00")
    rid = con.execute(
        "INSERT INTO receipts(lab_no,patient_name,status) VALUES(?,'P','pending')",
        (_lab(),),
    ).lastrowid
    con.commit()
    h = t.report.build_receipt_html(con, rid)
    b = t.report.build_receipt_bytes(con, rid)
    t.check(b[:4] == b"%PDF" and len(b) > 1000, "null-money PDF builds")
    t.has(h, "Total:</td><td class='val'>0.00", "null Total=0.00")
    t.has(h, "To Be Paid:</td><td class='val'>Rs. 0.00", "null ToBePaid=0.00")
    t.has(h, "Balance:</td>", "null Balance row")
    t.has(h, _ref_words(0), "null words=Zero")
    t.check("Change returned" not in h, "null no-change")
    # a receipt with NO items at all still builds and shows empty items body
    no_items_body = h[h.find("class='items'"):h.find("class='summary'")]
    t.eq(no_items_body.count("<tr>"), 1, "null no item rows (header only)")

    # =====================================================================
    # 6) Currency setting flows into the panel and rate header
    # =====================================================================
    t.section("currency setting")
    for cur in ["Rs.", "PKR", "₨", "$"]:
        t.db.set_setting(con, "currency", cur)
        rid = mk(1000.0, 900.0, 1000.0, 0.0)
        h = t.report.build_receipt_html(con, rid)
        b = t.report.build_receipt_bytes(con, rid)
        t.check(b[:4] == b"%PDF", f"cur PDF {cur}")
        from labdesk.report import _esc
        ec = _esc(cur)
        t.has(h, f"Rate ({ec})", f"cur rate header {cur}")
        t.has(h, f"To Be Paid:</td><td class='val'>{ec} 900.00", f"cur ToBePaid {cur}")
        t.has(h, f"Balance:</td><td class='val' style='color:#059669;'>{ec} 0.00",
              f"cur Balance {cur}")
    t.db.set_setting(con, "currency", "Rs.")   # restore default

    # =====================================================================
    # 7) Extreme / large values still format and build
    # =====================================================================
    t.section("extreme values")
    for sub in [99_999_999, 12_345_678, 9_999_999, 1_000_000_000 - 1]:
        net = round(sub * 0.9)
        rid = mk(float(sub), float(net), float(net), 0.0)
        h = t.report.build_receipt_html(con, rid)
        b = t.report.build_receipt_bytes(con, rid)
        t.check(b[:4] == b"%PDF" and len(b) > 1000, f"extreme PDF sub={sub}")
        t.has(h, f"Total:</td><td class='val'>{_money(float(sub))}",
              f"extreme Total sub={sub}")
        if net < 1_000_000_000:   # within words helper's sensible domain
            t.has(h, f"<i>{_ref_words(net)}</i>", f"extreme words sub={sub}")

    # =====================================================================
    # 8) created_by flows to "Registered by" (full name fallback to username)
    # =====================================================================
    t.section("registered-by line")
    rid = mk(500.0, 500.0, 500.0, 0.0, created_by=None)
    h = t.report.build_receipt_html(con, rid)
    t.check("Registered by:" not in h, "no created_by -> no reg line")
    # unknown username -> shown verbatim (no users row)
    rid = mk(500.0, 500.0, 500.0, 0.0, created_by="ghost_user")
    h = t.report.build_receipt_html(con, rid)
    t.has(h, "Registered by:", "created_by -> reg line")
    t.has(h, "ghost_user", "unknown user shown verbatim")

    # =====================================================================
    # 9) Idempotency — building twice yields identical HTML + same-size PDF
    # =====================================================================
    t.section("idempotent rebuild")
    for sub, net, paid in [(1000, 900, 1000), (2500, 2500, 1000), (0, 0, 0)]:
        rid = mk(float(sub), float(net), float(paid))
        h1 = t.report.build_receipt_html(con, rid)
        h2 = t.report.build_receipt_html(con, rid)
        t.eq(h1, h2, f"html idempotent sub={sub}")
        b1 = t.report.build_receipt_bytes(con, rid)
        b2 = t.report.build_receipt_bytes(con, rid)
        t.check(b1[:4] == b"%PDF" and b2[:4] == b"%PDF", f"pdf idempotent magic sub={sub}")
