"""Date / age handling generator — exercises age_desc rendering, the
report._fmt_date date helper, and reported_at stamping semantics across
src/labdesk/db.py and src/labdesk/report.py.

Contract (same as tests/gen/test_billing.py):
  * expose exactly one function ``register(t)``
  * assertions only through t.check / t.eq / t.near / t.has
  * never touch the network or the live DB (the runner isolates both)

Invariants asserted here:
  * report._fmt_date(iso) -> "%d %b<br>%Y" for valid ISO dates (date-only or
    with a time tail), falls back to the (HTML-escaped) raw string on a bad date,
    and is idempotent (formatting a formatted date is a no-op pass-through only
    when invalid).
  * The patient card's "Age / Sex" line renders exactly "{age} {age_desc} / {sex}"
    for every Years/Months/Days band — newborn (0), boundary, extreme, garbage.
  * reported_at is stamped (datetime('now','localtime'), a well-formed
    'YYYY-MM-DD HH:MM:SS' timestamp) ONLY on the pending/in_progress -> reported
    transition, and a reprint keeps the original stamp (the UPDATE no-ops once
    already reported). An unreported receipt shows the em-dash, never a "now".
  * The receipt builders never fabricate a reporting time, and never raise on
    None / garbage dates.
"""
from __future__ import annotations

import re
from datetime import datetime

# Canonical timestamp shape produced by SQLite datetime('now','localtime').
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_AGE_LINE_RE = re.compile(
    r'Age / Sex</span><span class="v">([^<]*)</span>')


def _safe_report_html(t, rid):
    try:
        return t.report.build_report_html(t.con, rid), None
    except Exception as e:  # must never raise
        return None, repr(e)


def _safe_receipt_html(t, rid):
    try:
        return t.report.build_receipt_html(t.con, rid), None
    except Exception as e:
        return None, repr(e)


def _is_pdf(b) -> bool:
    return isinstance(b, (bytes, bytearray)) and b[:4] == b"%PDF" and len(b) > 800


def _age_line(html):
    """Pull the rendered 'Age / Sex' value cell from a report HTML."""
    m = _AGE_LINE_RE.search(html or "")
    return m.group(1) if m else None


def register(t):
    con = t.con
    fmt = t.report._fmt_date

    # =====================================================================
    # 1. report._fmt_date — exact expected values for valid dates.
    # =====================================================================
    t.section("_fmt_date: valid ISO dates -> 'dd Mon<br>yyyy'")
    # (iso_input, expected) — note _fmt_date takes only the first 10 chars.
    GOOD = [
        ("2026-06-01", "01 Jun<br>2026"),
        ("2026-06-01 09:00", "01 Jun<br>2026"),
        ("2026-06-01 09:00:55", "01 Jun<br>2026"),
        ("2026-01-15", "15 Jan<br>2026"),
        ("2026-12-31", "31 Dec<br>2026"),
        ("2026-01-01", "01 Jan<br>2026"),
        ("1999-12-31", "31 Dec<br>1999"),
        ("2000-01-01", "01 Jan<br>2000"),
        ("2000-02-29", "29 Feb<br>2000"),   # leap year
        ("2024-02-29", "29 Feb<br>2024"),   # leap year
        ("2020-02-29", "29 Feb<br>2020"),
        ("2026-02-28", "28 Feb<br>2026"),
        ("2026-03-01", "01 Mar<br>2026"),
        ("2026-07-04", "04 Jul<br>2026"),
        ("2026-10-10", "10 Oct<br>2026"),
        ("2026-11-30", "30 Nov<br>2026"),
        ("1900-01-01", "01 Jan<br>1900"),
        ("2100-12-25", "25 Dec<br>2100"),
        ("9999-12-31", "31 Dec<br>9999"),
    ]
    for iso, want in GOOD:
        t.eq(fmt(iso), want, f"_fmt_date({iso!r})")
        # every month abbreviation must be the 3-letter English form
        t.check("<br>" in fmt(iso), f"_fmt_date has <br> separator {iso!r}")
        t.check(fmt(iso).endswith(iso[:4]), f"_fmt_date ends with year {iso!r}")

    # Cross-check _fmt_date against Python's own strftime over a dense date grid
    # (every month, several days, across many years) — the helper must agree with
    # the stdlib formatter for every valid ISO date.
    t.section("_fmt_date: agrees with strftime over a dense date grid")
    for year in range(1990, 2031):
        for month in range(1, 13):
            for day in (1, 14, 28):
                iso = f"{year:04d}-{month:02d}-{day:02d}"
                want = datetime.strptime(iso, "%Y-%m-%d").strftime("%d %b<br>%Y")
                t.eq(fmt(iso), want, f"_fmt_date grid {iso}")
                # with a time tail the result is identical (only [:10] is used).
                t.eq(fmt(iso + " 13:37:09"), want, f"_fmt_date grid+time {iso}")

    # Each calendar month maps to its correct 3-letter abbreviation.
    t.section("_fmt_date: every month abbreviation")
    MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    for mi, abbr in enumerate(MONTHS, start=1):
        iso = f"2026-{mi:02d}-15"
        t.eq(fmt(iso), f"15 {abbr}<br>2026", f"_fmt_date month {mi}")

    # Every day-of-month 01..28 is zero-padded and preserved.
    t.section("_fmt_date: day-of-month padding 01..28")
    for d in range(1, 29):
        iso = f"2026-06-{d:02d}"
        t.eq(fmt(iso), f"{d:02d} Jun<br>2026", f"_fmt_date day {d}")

    # =====================================================================
    # 2. report._fmt_date — garbage / invalid dates fall back to escaped raw.
    # =====================================================================
    t.section("_fmt_date: invalid input falls back to escaped raw (first 10)")
    # _fmt_date slices [:10] then strptime; on ValueError it returns _esc(s).
    BAD = [
        ("", ""),
        ("garbage", "garbage"),
        ("not-a-date", "not-a-date"),      # exactly 10 chars, kept whole
        ("not-a-dates", "not-a-date"),     # sliced to 10 chars
        ("2026/06/01", "2026/06/01"),      # wrong separators
        ("2026-13-01", "2026-13-01"),      # month 13
        ("2026-00-01", "2026-00-01"),      # month 0
        ("2026-06-32", "2026-06-32"),      # day 32
        ("2026-02-30", "2026-02-30"),      # impossible day
        ("2025-02-29", "2025-02-29"),      # non-leap year Feb 29
        ("06-01-2026", "06-01-2026"),      # US order
        ("01 Jun 2026", "01 Jun 202"),     # already-formatted-ish, 10-char slice
        ("Jun 1, 202", "Jun 1, 202"),
    ]
    for iso, want in BAD:
        t.eq(fmt(iso), want, f"_fmt_date invalid {iso!r}")
        t.check("<br>" not in fmt(iso), f"_fmt_date invalid has no <br> {iso!r}")

    # HTML escaping of a bad date: angle brackets / ampersand must be escaped.
    t.section("_fmt_date: bad dates are HTML-escaped on fallback")
    ESC = [
        ("<script>x</script>", "&lt;script&gt;"),
        ("a&b<c>", "a&amp;b&lt;c&gt;"),
        ('"quote"x', "&quot;quote"),
    ]
    for raw, frag in ESC:
        out = fmt(raw)
        t.has(out, frag, f"_fmt_date escapes {raw!r}")
        t.check("<script>" not in out, f"_fmt_date no raw <script> {raw!r}")

    # None must not raise (slices "" via the `(iso or '')` guard).
    t.eq(fmt(None), "", "_fmt_date(None) -> ''")

    # Idempotence-ish: a valid date formats the same on repeat calls.
    t.section("_fmt_date: deterministic across repeats")
    for iso, want in GOOD:
        t.eq(fmt(iso), fmt(iso), f"_fmt_date deterministic {iso!r}")

    # =====================================================================
    # 3. Age string rendering: "{age} {age_desc} / {sex}" across all bands.
    # =====================================================================
    t.section("age_desc rendering on the report patient card")
    AGE_UNITS = ["Years", "Months", "Days"]      # constants.AGE_UNITS
    # Cross check the picklist is exactly these three (single source of truth).
    from labdesk.constants import AGE_UNITS as _CONST_AGE_UNITS
    t.eq(list(_CONST_AGE_UNITS), AGE_UNITS,
         "constants.AGE_UNITS == [Years,Months,Days]")

    SEXES = ["Male", "Female", "Other"]
    # newborn (0 days), boundary (1), typical, geriatric, extreme, large.
    AGES = [0, 1, 2, 6, 11, 12, 13, 17, 18, 29, 30, 45, 59, 60, 65, 89, 90,
            99, 100, 119, 120, 200, 365, 999]

    for unit in AGE_UNITS:
        for sex in SEXES:
            for age in AGES:
                rid = t.make_receipt("03001234567", sub=500, paid=500,
                                     with_results=False, status="reported",
                                     sex=sex, age=age)
                # the factory hard-codes age_desc='Years'; override to this band.
                con.execute("UPDATE receipts SET age_desc=?, received_at=? WHERE id=?",
                            (unit, "2026-06-01 09:00", rid))
                con.commit()
                rh, err = _safe_report_html(t, rid)
                t.check(err is None,
                        f"report html never raises age={age} {unit} sex={sex} err={err}")
                if rh is None:
                    continue
                want = f"{age} {unit} / {sex}"
                line = _age_line(rh)
                t.eq(line, want,
                     f"age line age={age} unit={unit} sex={sex}")
                # the exact composed string must be present in the document.
                t.has(rh, want, f"report contains '{want}'")

    # =====================================================================
    # 4. age_desc edge cases: None / empty / garbage units must not crash and
    #    render the literal f-string value (documents real app behavior).
    # =====================================================================
    t.section("age_desc edge cases (None / empty / garbage)")
    EDGE_UNITS = [
        (None, "None"),        # f-string of None -> 'None' (current behavior)
        ("", ""),
        ("Weeks", "Weeks"),    # not in picklist but stored verbatim
        ("yrs", "yrs"),
        ("YEARS", "YEARS"),
        ("Year", "Year"),
    ]
    for stored, shown in EDGE_UNITS:
        rid = t.make_receipt("03001234567", sub=100, paid=100,
                             with_results=False, status="reported",
                             sex="Male", age=33)
        con.execute("UPDATE receipts SET age_desc=?, received_at='2026-06-01 09:00' "
                    "WHERE id=?", (stored, rid))
        con.commit()
        rh, err = _safe_report_html(t, rid)
        t.check(err is None, f"report html never raises age_desc={stored!r} err={err}")
        if rh is None:
            continue
        line = _age_line(rh)
        t.eq(line, f"33 {shown} / Male", f"age line age_desc={stored!r}")

    # Extreme / negative / garbage AGE values must not crash the builder.
    t.section("extreme & garbage age values")
    AGE_EXTREMES = [-1, -99, 0, 1000000, 2147483647]
    for age in AGE_EXTREMES:
        rid = t.make_receipt("03001234567", sub=100, paid=100,
                             with_results=False, status="reported",
                             sex="Male", age=age)
        con.execute("UPDATE receipts SET received_at='2026-06-01 09:00' WHERE id=?", (rid,))
        con.commit()
        rh, err = _safe_report_html(t, rid)
        t.check(err is None, f"report html never raises age={age} err={err}")
        if rh is not None:
            t.eq(_age_line(rh), f"{age} Years / Male", f"age line extreme age={age}")
    # PDF byte check for extremes in its own loop.
    for age in AGE_EXTREMES:
        rid = t.make_receipt("03001234567", sub=100, paid=100,
                             with_results=True, status="reported",
                             sex="Female", age=age)
        try:
            rb = t.report.build_report_bytes(con, rid)
            errb = None
        except Exception as e:
            rb, errb = None, repr(e)
        t.check(errb is None and _is_pdf(rb),
                f"report PDF builds for extreme age={age} err={errb}")

    # =====================================================================
    # 5. reported_at stamping semantics (mirrors worklist.py finalisation).
    #    UPDATE ... reported_at=datetime('now','localtime')
    #             WHERE id=? AND status IN ('pending','in_progress')
    # =====================================================================
    t.section("reported_at stamped only on pending/in_progress -> reported")

    def _stamp(rid):
        """Replicate the exact finalisation UPDATE used in worklist.py:382."""
        con.execute(
            "UPDATE receipts SET status='reported', "
            "reported_at=datetime('now','localtime') "
            "WHERE id=? AND status IN ('pending','in_progress')", (rid,))
        con.commit()

    def _get(rid):
        return con.execute(
            "SELECT status, reported_at FROM receipts WHERE id=?", (rid,)).fetchone()

    # 5a. A pending receipt gets a well-formed reported_at on finalisation.
    for i in range(40):
        pid = con.execute(
            "INSERT INTO patients(name,age,age_desc,sex,telephone) "
            "VALUES('Pend',30,'Years','Male','03001234567')").lastrowid
        rid = con.execute(
            "INSERT INTO receipts(lab_no,patient_id,patient_name,age,age_desc,sex,"
            "subtotal,net_amount,paid,due,status,received_at) "
            "VALUES(?,?,'Pend',30,'Years','Male',100,100,100,0,'pending',"
            "'2026-06-01 09:00')", (f"LAB_STAMP_{i:04d}", pid)).lastrowid
        con.commit()
        before = _get(rid)
        t.check(before["reported_at"] is None, f"pending has no reported_at i={i}")
        _stamp(rid)
        after = _get(rid)
        t.eq(after["status"], "reported", f"status reported after stamp i={i}")
        t.check(after["reported_at"] is not None, f"reported_at set after stamp i={i}")
        t.check(bool(_TS_RE.match(after["reported_at"] or "")),
                f"reported_at well-formed i={i}: {after['reported_at']!r}")
        # reported_at >= received_at (the stamp is 'now', received was in the past)
        t.check((after["reported_at"] or "") >= "2026-06-01 09:00",
                f"reported_at not before received i={i}")
        # 5b. A reprint (re-running the stamp) must NOT change the timestamp,
        # because status is now 'reported' and the WHERE clause no longer matches.
        first_stamp = after["reported_at"]
        _stamp(rid)
        again = _get(rid)
        t.eq(again["reported_at"], first_stamp,
             f"reprint keeps original reported_at i={i}")
        t.eq(again["status"], "reported", f"reprint status stays reported i={i}")

    # 5c. An in_progress receipt is also stampable (it is in the WHERE set).
    for i in range(15):
        pid = con.execute(
            "INSERT INTO patients(name,age,age_desc,sex,telephone) "
            "VALUES('Prog',30,'Years','Male','03001234567')").lastrowid
        rid = con.execute(
            "INSERT INTO receipts(lab_no,patient_id,patient_name,age,age_desc,sex,"
            "subtotal,net_amount,paid,due,status,received_at) "
            "VALUES(?,?,'Prog',30,'Years','Male',100,100,100,0,'in_progress',"
            "'2026-06-01 09:00')", (f"LAB_PROG_{i:04d}", pid)).lastrowid
        con.commit()
        _stamp(rid)
        after = _get(rid)
        t.eq(after["status"], "reported", f"in_progress -> reported i={i}")
        t.check(bool(_TS_RE.match(after["reported_at"] or "")),
                f"in_progress stamp well-formed i={i}")

    # 5d. A receipt in another status (e.g. already 'reported' or 'delivered')
    # must NOT be (re)stamped by the finalisation UPDATE.
    for status in ("reported", "delivered", "voided", "cancelled"):
        pid = con.execute(
            "INSERT INTO patients(name,age,age_desc,sex,telephone) "
            "VALUES('Other',30,'Years','Male','03001234567')").lastrowid
        rid = con.execute(
            "INSERT INTO receipts(lab_no,patient_id,patient_name,age,age_desc,sex,"
            "subtotal,net_amount,paid,due,status,received_at,reported_at) "
            "VALUES(?,?,'Other',30,'Years','Male',100,100,100,0,?,"
            "'2026-06-01 09:00','2026-06-02 10:00')",
            (f"LAB_OTH_{status}", pid, status)).lastrowid
        con.commit()
        _stamp(rid)
        after = _get(rid)
        t.eq(after["reported_at"], "2026-06-02 10:00",
             f"non-pending status '{status}' keeps reported_at untouched")
        t.eq(after["status"], status,
             f"non-pending status '{status}' unchanged by finalisation")

    # =====================================================================
    # 6. The report uses the STORED reported_at (stable reprint) and shows the
    #    em-dash placeholder when reported_at is NULL — never a fabricated now.
    # =====================================================================
    t.section("report shows stored reported_at / em-dash when unreported")
    REP_DATES = [
        ("2026-06-01 09:00", "2026-06-01 09:00"),
        ("2020-01-01 00:00", "2020-12-31 23:59"),
        ("1999-12-31 08:30", "2000-01-01 09:15"),
        ("2026-02-28 12:00", "2026-03-01 12:00"),
        ("2024-02-29 23:59", "2024-03-01 00:00"),
    ]
    for recv, rep in REP_DATES:
        rid = t.make_receipt("03001112222", sub=500, paid=500,
                             with_results=True, status="reported", sex="Male", age=30)
        con.execute("UPDATE receipts SET received_at=?, reported_at=? WHERE id=?",
                    (recv, rep, rid))
        con.commit()
        rh, err = _safe_report_html(t, rid)
        t.check(err is None, f"dated report never raises recv={recv} err={err}")
        if rh is None:
            continue
        # reported_at shown truncated to first 16 chars in the patient card.
        t.has(rh, rep[:16], f"report shows stored reported_at {rep!r}")
        t.has(rh, recv[:16], f"report shows registration date {recv!r}")
        t.has(rh, "Reporting Date", f"report has Reporting Date label {rep!r}")
        # reprint determinism: same reported_at on a second build.
        rh2, _ = _safe_report_html(t, rid)
        t.eq(rh, rh2, f"dated report deterministic reprint recv={recv}")

    # Unreported (reported_at NULL) -> em-dash, no fabricated 'now'.
    for recv in ["2026-05-05 10:00", "2020-01-01 00:00", "garbage-date", ""]:
        rid = t.make_receipt("03002223333", sub=500, paid=0,
                             with_results=False, status="pending", sex="Female", age=25)
        con.execute("UPDATE receipts SET received_at=?, reported_at=NULL WHERE id=?",
                    (recv, rid))
        con.commit()
        rh, err = _safe_report_html(t, rid)
        t.check(err is None, f"pending report never raises recv={recv!r} err={err}")
        if rh is None:
            continue
        t.has(rh, "Reporting Date", f"pending report has Reporting Date label recv={recv!r}")
        t.has(rh, "—", f"pending report uses em-dash placeholder recv={recv!r}")
        # No fabricated 'now' year stamp leaks where reported_at is NULL: the
        # current real year must not appear as a Reporting Date value. We assert
        # the report does not contain a today-stamped reporting time by checking
        # the Reporting Date value cell is the em-dash (already covered) and that
        # building 'now' was avoided — i.e. the received date may show but not a
        # second timestamp claiming to be a report time.
        today = datetime.now().strftime("%Y-%m-%d %H:%M")
        if recv[:16] != today:
            # the fabricated 'now' minute should not appear unless it is the
            # registration date (which it isn't here).
            t.check(today not in rh,
                    f"pending report does not fabricate now reporting time recv={recv!r}")

    # =====================================================================
    # 7. Cash receipt: it is a billing doc — NO reporting date, ever, even when
    #    reported_at is set; and it must not raise on garbage dates.
    # =====================================================================
    t.section("cash receipt omits reporting date / survives garbage dates")
    for recv, rep in [("2026-06-01 09:00", "2026-06-02 10:00"),
                      ("garbage", "also-garbage"),
                      ("", ""),
                      ("2026-13-99 99:99", "2026-13-99 99:99")]:
        rid = t.make_receipt("03004445555", sub=1000, paid=1000,
                             with_results=False, status="reported", sex="Male", age=40)
        con.execute("UPDATE receipts SET received_at=?, reported_at=? WHERE id=?",
                    (recv, rep or None, rid))
        con.commit()
        ch, err = _safe_receipt_html(t, rid)
        t.check(err is None, f"receipt html never raises recv={recv!r} err={err}")
        if ch is None:
            continue
        t.check("reporting date" not in ch.lower(),
                f"cash receipt omits Reporting Date recv={recv!r}")
        # the receipt 'Date:' meta uses received_at[:16]; for a valid date it
        # appears, for garbage it just renders whatever the slice is (no crash).
        if recv and recv != "garbage" and _TS_RE.match(recv) is None and \
                len(recv) >= 16 and recv[:4].isdigit():
            pass  # mixed validity; only assert no-crash above
        # receipt PDF must build regardless of date validity.
        try:
            cb = t.report.build_receipt_bytes(con, rid)
            errc = None
        except Exception as e:
            cb, errc = None, repr(e)
        t.check(errc is None and _is_pdf(cb),
                f"cash receipt PDF builds recv={recv!r} err={errc}")

    # The receipt 'year' falls back to received_at[:4] (or now's year if blank).
    t.section("receipt copyright year derives from received_at")
    for recv, year in [("2026-06-01 09:00", "2026"), ("2019-01-01 00:00", "2019"),
                       ("1999-12-31 23:59", "1999"), ("2100-05-05 05:05", "2100")]:
        rid = t.make_receipt("03004445555", sub=200, paid=200,
                             with_results=False, status="reported", sex="Male", age=40)
        con.execute("UPDATE receipts SET received_at=? WHERE id=?", (recv, rid))
        con.commit()
        ch, err = _safe_receipt_html(t, rid)
        t.check(err is None, f"receipt year html never raises recv={recv} err={err}")
        if ch is not None:
            t.has(ch, f"© {year}", f"receipt copyright year {year} from {recv}")

    # =====================================================================
    # 8. received_at -> column header date on the report (_fmt_date driven).
    # =====================================================================
    t.section("report Current column header date (received_at via _fmt_date)")
    for recv, frag in [("2026-06-01 09:00", "01 Jun"),
                       ("2024-02-29 10:00", "29 Feb"),
                       ("1999-12-31 08:00", "31 Dec"),
                       ("2026-01-01 00:00", "01 Jan")]:
        rid = t.make_receipt("03001234567", sub=300, paid=300,
                             with_results=True, status="reported", sex="Male", age=30)
        con.execute("UPDATE receipts SET received_at=? WHERE id=?", (recv, rid))
        con.commit()
        rh, err = _safe_report_html(t, rid)
        t.check(err is None, f"current-col report never raises recv={recv} err={err}")
        if rh is not None:
            # the Current column header carries the formatted received date.
            t.has(rh, frag, f"current column shows formatted date {recv}")
            t.has(rh, recv[:4], f"current column shows year {recv}")
