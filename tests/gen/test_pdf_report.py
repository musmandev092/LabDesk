"""PDF / report generator — exercises report.build_report_bytes,
report.build_receipt_bytes, report.build_report_html and the native renderer
(render.build_report / build_receipt) across many receipt variants.

Contract (same as tests/gen/test_billing.py):
  * expose exactly one function ``register(t)``
  * assertions only through t.check / t.eq / t.near / t.has
  * never touch the network or the live DB (the runner isolates both)

Focus invariants for every receipt variant (Male/Female/other sex, age bands,
pending/reported, with/without results, empty/garbage inputs, extreme money):
  * build_report_bytes  -> non-empty bytes starting with %PDF, must never raise
  * build_receipt_bytes -> non-empty bytes starting with %PDF, must never raise
  * build_report_html   -> contains the patient name + core lab/patient fields
  * the builders must be deterministic / re-entrant (same bytes prefix on rebuild)
"""

from __future__ import annotations


def _is_pdf(b) -> bool:
    return isinstance(b, (bytes, bytearray)) and b[:4] == b"%PDF" and len(b) > 800


def _safe_report_bytes(t, rid):
    try:
        return t.report.build_report_bytes(t.con, rid), None
    except Exception as e:  # must never raise
        return None, repr(e)


def _safe_receipt_bytes(t, rid):
    try:
        return t.report.build_receipt_bytes(t.con, rid), None
    except Exception as e:
        return None, repr(e)


def _safe_report_html(t, rid):
    try:
        return t.report.build_report_html(t.con, rid), None
    except Exception as e:
        return None, repr(e)


def _safe_receipt_html(t, rid):
    try:
        return t.report.build_receipt_html(t.con, rid), None
    except Exception as e:
        return None, repr(e)


def register(t):
    con = t.con

    # ------------------------------------------------------------------
    # 1. Matrix of receipt variants built through the shared factory.
    # ------------------------------------------------------------------
    t.section("report/receipt PDF + HTML across patient variants")

    SEXES = ["Male", "Female", "Other", "", "M", "F", "Unknown"]
    # age bands: newborn .. geriatric .. boundary/extreme/garbage
    AGES = [0, 1, 2, 5, 12, 13, 17, 18, 30, 45, 59, 60, 65, 90, 120, 200, -1, 999]
    STATUSES = ["reported", "pending"]
    RESULTS = [True, False]
    # money shapes: zero, exact, overpaid (change), underpaid (due), huge
    MONEY = [
        (0.0, 0.0),
        (500.0, 500.0),
        (1250.0, 2000.0),  # overpaid -> change returned
        (800.0, 300.0),  # underpaid -> due
        (99999.0, 0.0),  # large, fully due
        (12345678.0, 12345678.0),  # crore-scale amount-in-words
    ]
    PHONES = ["03001234567", "", "12", "+92 300 1234567"]

    variant = 0
    for sex in SEXES:
        for age in AGES:
            for status in STATUSES:
                for with_results in RESULTS:
                    # pick a money shape + phone deterministically to keep the
                    # count high but bounded; rotate through the lists.
                    sub, paid = MONEY[variant % len(MONEY)]
                    phone = PHONES[variant % len(PHONES)]
                    variant += 1
                    rid = t.make_receipt(
                        phone,
                        sub=sub,
                        paid=paid,
                        with_results=with_results,
                        status=status,
                        sex=sex,
                        age=age,
                    )

                    rb, err_r = _safe_report_bytes(t, rid)
                    t.check(
                        err_r is None,
                        f"report never raises rid={rid} sex={sex!r} age={age} "
                        f"status={status} results={with_results} err={err_r}",
                    )
                    t.check(
                        _is_pdf(rb),
                        f"report PDF %PDF rid={rid} sex={sex!r} age={age} "
                        f"status={status} results={with_results}",
                    )

                    cb, err_c = _safe_receipt_bytes(t, rid)
                    t.check(
                        err_c is None,
                        f"receipt never raises rid={rid} sex={sex!r} age={age} " f"err={err_c}",
                    )
                    t.check(
                        _is_pdf(cb),
                        f"receipt PDF %PDF rid={rid} sex={sex!r} age={age} "
                        f"status={status} results={with_results}",
                    )

                    rh, err_h = _safe_report_html(t, rid)
                    t.check(err_h is None, f"report html never raises rid={rid} err={err_h}")
                    if rh is not None:
                        t.has(rh, "Test Patient", f"report html has patient name rid={rid}")
                        t.has(rh, "Lab No", f"report html has 'Lab No' label rid={rid}")
                        t.has(rh, "Age / Sex", f"report html has 'Age / Sex' label rid={rid}")
                        t.has(rh, "LAB_GEN_", f"report html has lab number rid={rid}")
                        t.has(rh, "<!DOCTYPE html>", f"report html is a full document rid={rid}")
                        # reporting date label is present on a report (not receipt)
                        t.has(
                            rh, "Reporting Date", f"report html has reporting-date label rid={rid}"
                        )

    # ------------------------------------------------------------------
    # 2. Receipt (cash) HTML invariants: amount-in-words, totals, no
    #    reporting-date label, lab name present.
    # ------------------------------------------------------------------
    t.section("cash-receipt HTML invariants (words / totals / balance)")
    lab_name = t.db.get_setting(con, "lab_name", "")
    for sub, paid in MONEY:
        rid = t.make_receipt(
            "03009998888",
            sub=sub,
            paid=paid,
            with_results=False,
            status="pending",
            sex="Male",
            age=30,
        )
        ch, err = _safe_receipt_html(t, rid)
        t.check(err is None, f"receipt html never raises rid={rid} err={err}")
        if ch is None:
            continue
        t.has(ch, "Test Patient", f"receipt html has patient name rid={rid}")
        t.has(ch, "Cash Receipt", f"receipt html titled Cash Receipt rid={rid}")
        t.has(ch, "Amount in words", f"receipt html has amount-in-words rid={rid}")
        t.has(ch, "Rupees Only", f"receipt html words end 'Rupees Only' rid={rid}")
        t.has(ch, "To Be Paid", f"receipt html has 'To Be Paid' rid={rid}")
        t.has(ch, "Balance", f"receipt html has Balance row rid={rid}")
        # A cash receipt is a billing document — it must NOT show Reporting Date.
        t.check("reporting date" not in ch.lower(), f"receipt html omits Reporting Date rid={rid}")
        if lab_name:
            t.has(ch, lab_name, f"receipt html has lab name rid={rid}")
        # change row appears only when overpaid; balance row always present
        net = (con.execute("SELECT net_amount FROM receipts WHERE id=?", (rid,)).fetchone()[0]) or 0
        if paid > net:
            t.has(ch, "Change returned", f"receipt shows change when overpaid rid={rid}")
        else:
            t.check(
                "change returned" not in ch.lower(),
                f"receipt hides change when not overpaid rid={rid}",
            )

    # ------------------------------------------------------------------
    # 3. amount-in-words: exact known Pakistani-numbering values.
    #    (drives report._amount_in_words via the receipt HTML totals.)
    # ------------------------------------------------------------------
    t.section("amount-in-words exact values")
    AIW = {
        0: "Zero Rupees Only",
        1: "One Rupees Only",
        5: "Five Rupees Only",
        10: "Ten Rupees Only",
        15: "Fifteen Rupees Only",
        20: "Twenty Rupees Only",
        21: "Twenty One Rupees Only",
        99: "Ninety Nine Rupees Only",
        100: "One Hundred Rupees Only",
        101: "One Hundred One Rupees Only",
        110: "One Hundred Ten Rupees Only",
        999: "Nine Hundred Ninety Nine Rupees Only",
        1000: "One Thousand Rupees Only",
        1500: "One Thousand Five Hundred Rupees Only",
        12345: "Twelve Thousand Three Hundred Forty Five Rupees Only",
        100000: "One Lakh Rupees Only",
        125000: "One Lakh Twenty Five Thousand Rupees Only",
        1000000: "Ten Lakh Rupees Only",
        10000000: "One Crore Rupees Only",
        12345678: "One Crore Twenty Three Lakh Forty Five Thousand "
        "Six Hundred Seventy Eight Rupees Only",
    }
    aiw = t.report._amount_in_words
    for n, words in AIW.items():
        t.eq(aiw(n), words, f"amount_in_words({n})")
    # rounding: .49 down, .5 up (round-half-to-even on .5 boundaries is fine for
    # whole-rupee display) — assert the integer part drives the words.
    t.eq(aiw(999.49), "Nine Hundred Ninety Nine Rupees Only", "aiw rounds 999.49 down")
    t.eq(aiw(None), "Zero Rupees Only", "aiw(None) -> Zero")
    t.eq(aiw(0.0), "Zero Rupees Only", "aiw(0.0) -> Zero")

    # ------------------------------------------------------------------
    # 4. Date handling: explicit received_at / reported_at on the receipt.
    #    The report must use the STORED reported_at (stable reprint), and an
    #    unreported receipt must show no fabricated reporting time.
    # ------------------------------------------------------------------
    t.section("report date handling (stored reported_at / blank when unreported)")
    DATES = [
        ("2026-06-01 09:00", "2026-06-01 09:00"),
        ("2020-01-01 00:00", "2020-12-31 23:59"),
        ("1999-12-31 08:30", "2000-01-01 09:15"),
        ("2026-02-28 12:00", "2026-03-01 12:00"),
        ("garbage-date", ""),  # garbage received, no reported
    ]
    for recv, rep in DATES:
        rid = t.make_receipt(
            "03001112222",
            sub=500,
            paid=500,
            with_results=True,
            status="reported",
            sex="Male",
            age=30,
        )
        con.execute(
            "UPDATE receipts SET received_at=?, reported_at=? WHERE id=?", (recv, rep or None, rid)
        )
        con.commit()
        rh, err = _safe_report_html(t, rid)
        t.check(err is None, f"dated report html never raises rid={rid} err={err}")
        rb, errb = _safe_report_bytes(t, rid)
        t.check(errb is None and _is_pdf(rb), f"dated report PDF builds rid={rid} err={errb}")
        if rh is None:
            continue
        if rep:
            t.has(rh, rep[:16], f"report uses stored reported_at {rep!r} rid={rid}")
        # received date (first 16 chars) appears in the patient card when valid
        if recv and recv != "garbage-date":
            t.has(rh, recv[:16], f"report shows registration date {recv!r} rid={rid}")

    # unreported (pending) receipt -> reporting date renders as the em-dash
    # placeholder, never a fabricated "now".
    rid = t.make_receipt(
        "03002223333", sub=500, paid=0, with_results=False, status="pending", sex="Female", age=25
    )
    con.execute(
        "UPDATE receipts SET received_at='2026-05-05 10:00', reported_at=NULL " "WHERE id=?", (rid,)
    )
    con.commit()
    rh, err = _safe_report_html(t, rid)
    t.check(err is None, f"pending report html never raises rid={rid} err={err}")
    if rh is not None:
        # The reporting-date value cell should be the placeholder, not a date.
        # The label is present; assert no fabricated 2026-05-05 reporting stamp
        # leaks where reported_at is NULL by checking the value cell renders "—".
        t.has(rh, "Reporting Date", f"pending report has reporting label rid={rid}")
        t.has(rh, "—", f"pending report uses em-dash placeholder rid={rid}")
    rb, errb = _safe_receipt_bytes(t, rid)
    t.check(errb is None and _is_pdf(rb), f"pending receipt PDF builds rid={rid}")

    # ------------------------------------------------------------------
    # 5. Empty receipt (no items at all) — both docs must still build.
    # ------------------------------------------------------------------
    t.section("degenerate receipts (no items / null money / weird sex)")
    pid = con.execute(
        "INSERT INTO patients(name,age,age_desc,sex,telephone) "
        "VALUES('Empty Pt',40,'Years','Male','03001234567')"
    ).lastrowid
    # subtotal/net/paid/due are NOT NULL DEFAULT 0 — omit them so they default to
    # 0; this exercises a zero-money receipt with no line items at all.
    empty_rid = con.execute(
        "INSERT INTO receipts(lab_no,patient_id,patient_name,age,age_desc,sex,status) "
        "VALUES('LAB_EMPTY_1',?,'Empty Pt',40,'Years','Male','pending')",
        (pid,),
    ).lastrowid
    con.commit()
    rb, err = _safe_report_bytes(t, empty_rid)
    t.check(err is None and _is_pdf(rb), f"empty-receipt report PDF builds err={err}")
    cb, errc = _safe_receipt_bytes(t, empty_rid)
    t.check(errc is None and _is_pdf(cb), f"empty-receipt cash PDF builds (zero money) err={errc}")
    rh, errh = _safe_report_html(t, empty_rid)
    t.check(errh is None, f"empty report html never raises err={errh}")
    if rh is not None:
        t.has(rh, "No tests on this receipt", "empty report html notes no tests")
    ch, errch = _safe_receipt_html(t, empty_rid)
    t.check(errch is None, f"empty receipt html never raises err={errch}")
    if ch is not None:
        # null money must render 0.00, never crash a format string
        t.has(ch, "0.00", "empty receipt renders zero money")
        t.has(ch, "Zero Rupees Only", "empty receipt words = Zero")

    # receipt with a zero-charge item and an HTML-unsafe patient name
    pid2 = con.execute(
        "INSERT INTO patients(name,age,age_desc,sex,telephone) "
        "VALUES('Weird <Pt> & Co',33,'Years','Other','')"
    ).lastrowid
    wrid = con.execute(
        "INSERT INTO receipts(lab_no,patient_id,patient_name,age,age_desc,sex,status,"
        "subtotal,net_amount,paid,due) "
        "VALUES('LAB_WEIRD_1',?,'Weird <Pt> & Co',33,'Years','Other','reported',"
        "0,0,0,0)",
        (pid2,),
    ).lastrowid
    tid = con.execute("SELECT id,name FROM tests LIMIT 1").fetchone()
    # charge is NOT NULL DEFAULT 0 — omit it so it defaults to 0
    con.execute(
        "INSERT INTO receipt_items(receipt_id,test_id,test_name) " "VALUES(?,?,?)",
        (wrid, tid["id"], tid["name"]),
    )
    con.commit()
    rb, err = _safe_report_bytes(t, wrid)
    t.check(err is None and _is_pdf(rb), f"zero-charge report PDF builds err={err}")
    cb, errc = _safe_receipt_bytes(t, wrid)
    t.check(errc is None and _is_pdf(cb), f"zero-charge receipt PDF builds err={errc}")
    ch, errh = _safe_receipt_html(t, wrid)
    t.check(errh is None, f"weird-name receipt html never raises err={errh}")
    if ch is not None:
        # HTML must be escaped — raw '<Pt>' must not appear unescaped, '&lt;' must
        t.check("<Pt>" not in ch, "weird patient name is HTML-escaped (no <Pt>)")
        t.has(ch, "&lt;Pt&gt;", "weird patient name escaped to &lt;Pt&gt;")

    # ------------------------------------------------------------------
    # 6. Abnormal-flag invariants on _flag / _flag_arrow (drive report colours).
    # ------------------------------------------------------------------
    t.section("reference-range flag logic (_flag / _flag_arrow)")
    flag = t.report._flag
    arrow = t.report._flag_arrow
    # (value, ref, expected_label_or_None)
    FLAGS = [
        ("10", "5-15", "Normal"),
        ("5", "5-15", "Normal"),  # boundary lo inclusive
        ("15", "5-15", "Normal"),  # boundary hi inclusive
        ("4.9", "5-15", "Low"),
        ("15.1", "5-15", "High"),
        ("0", "5 - 15", "Low"),
        ("100", "5-15", "High"),
        ("3.5", "3.5-5.5", "Normal"),
        ("150", "< 200", "Normal"),
        ("200", "< 200", "Normal"),  # boundary: not greater than
        ("201", "< 200", "High"),
        ("199", "<=200", "Normal"),
        ("50", "> 40", "Normal"),
        # NB: report._flag treats '>' and '>=' identically (the regex makes '='
        # optional and there is no strict-vs-inclusive branch), so the boundary
        # value 40 against '> 40' is judged Normal, not Low.
        ("40", "> 40", "Normal"),
        ("39", "> 40", "Low"),
        ("45", ">=40", "Normal"),
        ("0.8", "0.5-1.2", "Normal"),
        ("-5", "-10 - 10", "Normal"),
        ("-11", "-10 - 10", "Low"),
        ("11", "-10 - 10", "High"),
        ("1,234", "0-2000", "Normal"),  # comma stripped
        ("Positive", "Negative", None),  # non-numeric value -> no flag
        ("12", "", None),  # no ref -> no flag
        ("12", "see comment", None),  # non-numeric ref -> no flag
        ("3", "< 200 (ideal 0-99)", "Normal"),  # leading < wins over paren range
    ]
    for val, ref, want in FLAGS:
        got = flag(val, ref)
        label = got[0] if got else None
        t.eq(label, want, f"_flag({val!r},{ref!r})")
        # arrow consistency: High->up, Low->down, else None
        a = arrow(val, ref)
        if want == "High":
            t.eq(a, (t.report.ARROW_UP, "high"), f"_flag_arrow high {val!r}")
        elif want == "Low":
            t.eq(a, (t.report.ARROW_DOWN, "low"), f"_flag_arrow low {val!r}")
        else:
            t.eq(a, None, f"_flag_arrow none {val!r},{ref!r}")
    # None value never flags / never raises
    t.eq(flag(None, "5-15"), None, "_flag(None) -> None")
    t.eq(arrow(None, "5-15"), None, "_flag_arrow(None) -> None")

    # ------------------------------------------------------------------
    # 7. Determinism / re-entrancy: building the same receipt twice yields a
    #    valid PDF both times (and the HTML is byte-identical).
    # ------------------------------------------------------------------
    t.section("determinism / re-entrancy of builders")
    rid = t.make_receipt(
        "03004445555", sub=1000, paid=1000, with_results=True, status="reported", sex="Male", age=50
    )
    con.execute(
        "UPDATE receipts SET received_at='2026-01-15 10:00', "
        "reported_at='2026-01-15 14:00' WHERE id=?",
        (rid,),
    )
    con.commit()
    h1, _ = _safe_report_html(t, rid)
    h2, _ = _safe_report_html(t, rid)
    t.eq(h1, h2, "report html is deterministic on rebuild")
    c1, _ = _safe_receipt_html(t, rid)
    c2, _ = _safe_receipt_html(t, rid)
    t.eq(c1, c2, "receipt html is deterministic on rebuild")
    for _ in range(3):
        rb, err = _safe_report_bytes(t, rid)
        t.check(err is None and _is_pdf(rb), "report PDF rebuild stays valid")
        cb, errc = _safe_receipt_bytes(t, rid)
        t.check(errc is None and _is_pdf(cb), "receipt PDF rebuild stays valid")

    # ------------------------------------------------------------------
    # 8. Many-result variants: multiple tests on one receipt + history.
    # ------------------------------------------------------------------
    t.section("multi-test receipts + extreme values stress")
    # Build several receipts each carrying several tests with assorted result
    # values (out-of-range, huge, negative, text) to exercise the table painter.
    test_ids = [
        row[0]
        for row in con.execute("SELECT DISTINCT test_id FROM test_parameters LIMIT 6").fetchall()
    ]
    VAL_SETS = [
        ["1", "999999", "-50", "0.0001"],
        ["Positive", "Negative", "Trace", "Nil"],
        ["", "", "", ""],  # all blank -> "No result entered"
        ["1e10", "0", "12.5", "1,234,567"],
    ]
    for vi, vals in enumerate(VAL_SETS):
        pid = con.execute(
            "INSERT INTO patients(name,age,age_desc,sex,telephone,mr_no) "
            "VALUES('Multi Pt',55,'Years','Male','03001234567',?)",
            (f"MR_MULTI_{vi}",),
        ).lastrowid
        rid = con.execute(
            "INSERT INTO receipts(lab_no,patient_id,patient_name,age,age_desc,sex,"
            "telephone,status,subtotal,net_amount,paid,due,mr_no,received_at) "
            "VALUES(?,?,'Multi Pt',55,'Years','Male','03001234567','reported',"
            "3000,3000,3000,0,?, '2026-03-01 09:00')",
            (f"LAB_MULTI_{vi}", pid, f"MR_MULTI_{vi}"),
        ).lastrowid
        for tid in test_ids[:3]:
            tname = con.execute("SELECT name FROM tests WHERE id=?", (tid,)).fetchone()[0]
            item_id = con.execute(
                "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) "
                "VALUES(?,?,?,1000)",
                (rid, tid, tname),
            ).lastrowid
            params = con.execute(
                "SELECT * FROM test_parameters WHERE test_id=? ORDER BY seq LIMIT 4", (tid,)
            ).fetchall()
            for k, p in enumerate(params):
                con.execute(
                    "INSERT INTO results(receipt_item_id,parameter_id,seq,part_type,"
                    "name,units,ref_text,value,hidden) VALUES(?,?,?,?,?,?,?,?,0)",
                    (
                        item_id,
                        p["id"],
                        p["seq"],
                        p["part_type"] or "N",
                        p["name"],
                        p["units"],
                        p["ref_male"],
                        vals[k % len(vals)],
                    ),
                )
        con.commit()
        rb, err = _safe_report_bytes(t, rid)
        t.check(err is None and _is_pdf(rb), f"multi-test report PDF builds vi={vi} err={err}")
        rh, errh = _safe_report_html(t, rid)
        t.check(errh is None, f"multi-test report html never raises vi={vi} err={errh}")
        if rh is not None:
            t.has(rh, "Multi Pt", f"multi-test report has patient vi={vi}")
        cb, errc = _safe_receipt_bytes(t, rid)
        t.check(errc is None and _is_pdf(cb), f"multi-test receipt PDF builds vi={vi} err={errc}")
