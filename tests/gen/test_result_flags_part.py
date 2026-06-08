"""Generator — report.py / render.py result rendering invariants.

Focus: report.build_report_html + the helpers it drives (_resolve_ref, _flag,
_flag_arrow, _report_section):
  * part_type handling      — 'H' rows become subheads, 'N' rows are result lines
  * hidden results excluded  — results.hidden=1 rows never appear in the report
  * ref_male vs ref_female selection by the patient's sex
  * abnormal up/down (↑/↓) flags judged against the SELECTED gender range only,
    and never flagged when the report shows BOTH M and F ranges (sex unknown).

Everything is built from scratch (own tests / test_parameters / patient /
receipt / item / results) so the gender ranges, values, part_type and hidden
flags are fully controlled and the expected html is known-correct.

This module emits well over 1,500 cases.
"""

from __future__ import annotations

import itertools

# colours used for inline arrows (mirrors report.py constants)
ARROW_UP = "↑"  # ↑ High / above range
ARROW_DOWN = "↓"  # ↓ Low / below range


def _builder(t):
    """Return a build(...) closure bound to the isolated connection.

    build(sex, params, vals, hiddens=None) -> rendered report html
      params: list of (part_type, name, units, ref_male, ref_female)
      vals:   list of entered result strings (parallel to params)
      hiddens:list of 0/1 (parallel to params); default all 0
    """
    con = t.con
    counter = itertools.count()

    def build(sex, params, vals, hiddens=None):
        n = next(counter)
        tid = con.execute(
            "INSERT INTO tests(name,charges) VALUES(?,100)", (f"RFPART_{n}",)
        ).lastrowid
        pids = []
        for seq, (pt, nm, un, rm, rf) in enumerate(params):
            pid = con.execute(
                "INSERT INTO test_parameters(test_id,seq,part_type,name,units,"
                "ref_male,ref_female) VALUES(?,?,?,?,?,?,?)",
                (tid, seq, pt, nm, un, rm, rf),
            ).lastrowid
            pids.append(pid)
        patid = con.execute(
            "INSERT INTO patients(name,age,age_desc,sex) VALUES('P',30,'Years',?)",
            (sex,),
        ).lastrowid
        rid = con.execute(
            "INSERT INTO receipts(lab_no,patient_id,patient_name,age,age_desc,sex,"
            "status,net_amount,paid,due) "
            "VALUES(?,?,'P',30,'Years',?,'reported',100,100,0)",
            (f"RFP_{n:06d}", patid, sex),
        ).lastrowid
        item = con.execute(
            "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) " "VALUES(?,?,?,100)",
            (rid, tid, f"RFPART_{n}"),
        ).lastrowid
        hiddens = hiddens or [0] * len(params)
        for seq, (pt, nm, un, rm, rf) in enumerate(params):
            # ref_text snapshot is deliberately the male range; build_report_html
            # joins test_parameters for p_male/p_female, so the gender pick comes
            # from there — ref_text only matters when both M and F are empty.
            con.execute(
                "INSERT INTO results(receipt_item_id,parameter_id,seq,part_type,"
                "name,units,ref_text,value,hidden) VALUES(?,?,?,?,?,?,?,?,?)",
                (item, pids[seq], seq, pt, nm, un, rm, vals[seq], hiddens[seq]),
            )
        con.commit()
        return t.report.build_report_html(con, rid)

    return build


def register(t):
    build = _builder(t)

    # =====================================================================
    # 1. ref_male vs ref_female selection + flag judged on the chosen range
    # =====================================================================
    t.section("gender range selection + numeric flags")
    # (ref_male, ref_female): different ranges so we can prove the right one
    # is shown and the value flagged against THAT one only.
    RANGES = [
        ("13-17", "12-15"),  # classic Hb split
        ("0-4", "0-1"),  # PSA-ish, female narrower
        ("60-80", "50-70"),  # arbitrary
        ("4.5-6.5", "3.8-5.8"),  # decimals
        ("100-200", "90-180"),
        ("36-46", "38-48"),  # haematocrit-ish, female higher
        ("4.5-11", "4.0-10"),  # WBC
        ("0.5-2.0", "0.4-1.5"),  # creatinine
        ("150-450", "140-400"),  # platelets
        ("200-400", "150-350"),  # fibrinogen
        ("7-9", "6-8"),
        ("20-30", "10-25"),
    ]
    # values chosen to probe below / lo-bound / mid / hi-bound / above
    for rm, rf in RANGES:
        mlo, mhi = (float(x) for x in rm.split("-"))
        flo, fhi = (float(x) for x in rf.split("-"))
        for sex, (lo, hi, shown, hidden) in [
            ("Male", (mlo, mhi, rm, rf)),
            ("Female", (flo, fhi, rf, rm)),
            ("male", (mlo, mhi, rm, rf)),  # lowercase still selects male
            ("female", (flo, fhi, rf, rm)),
        ]:
            mid = (lo + hi) / 2
            below = lo - max(1.0, (hi - lo) * 0.5)
            above = hi + max(1.0, (hi - lo) * 0.5)
            tag = f"{sex} {rm}|{rf}"
            # below range -> low arrow ↓, never high
            h = build(sex, [("N", "P", "u", rm, rf)], [str(below)])
            t.check(ARROW_DOWN in h, f"below->down {tag} v={below}")
            t.check(ARROW_UP not in h, f"below not up {tag} v={below}")
            t.has(h, shown, f"shows selected range {tag}")
            t.check(
                hidden != shown and hidden not in h or hidden == shown,
                f"other-sex range hidden {tag}",
            )
            # lower bound is Normal (inclusive)
            h = build(sex, [("N", "P", "u", rm, rf)], [str(lo)])
            t.check(ARROW_DOWN not in h and ARROW_UP not in h, f"lo-bound normal {tag} v={lo}")
            # mid is Normal
            h = build(sex, [("N", "P", "u", rm, rf)], [str(mid)])
            t.check(ARROW_DOWN not in h and ARROW_UP not in h, f"mid normal {tag} v={mid}")
            # upper bound is Normal (inclusive)
            h = build(sex, [("N", "P", "u", rm, rf)], [str(hi)])
            t.check(ARROW_DOWN not in h and ARROW_UP not in h, f"hi-bound normal {tag} v={hi}")
            # above range -> high arrow ↑, never low
            h = build(sex, [("N", "P", "u", rm, rf)], [str(above)])
            t.check(ARROW_UP in h, f"above->up {tag} v={above}")
            t.check(ARROW_DOWN not in h, f"above not down {tag} v={above}")

    # The cross-sex proof: a value that is in-range for one sex but out-of-range
    # for the other must flag according to the PATIENT's sex, not the other.
    t.section("cross-sex flag direction (value differs by sex)")
    # Hb 12.5: normal for Male(13-17)? no, below 13 -> low. For Female(12-15) -> normal.
    for sex, expect_down in [("Male", True), ("Female", False)]:
        h = build(sex, [("N", "Hb", "g/dL", "13-17", "12-15")], ["12.5"])
        if expect_down:
            t.check(ARROW_DOWN in h, f"Hb12.5 {sex} low (below male 13)")
        else:
            t.check(
                ARROW_DOWN not in h and ARROW_UP not in h, f"Hb12.5 {sex} normal (in female 12-15)"
            )
    # value 15.5: male(13-17)=normal, female(12-15)=high
    for sex, expect_up in [("Male", False), ("Female", True)]:
        h = build(sex, [("N", "Hb", "g/dL", "13-17", "12-15")], ["15.5"])
        if expect_up:
            t.check(ARROW_UP in h, f"Hb15.5 {sex} high (above female 15)")
        else:
            t.check(
                ARROW_UP not in h and ARROW_DOWN not in h, f"Hb15.5 {sex} normal (in male 13-17)"
            )

    # =====================================================================
    # 2. Unknown / ambiguous sex: show BOTH ranges, never flag.
    # =====================================================================
    t.section("ambiguous sex shows both ranges, no flag")
    AMBIG_SEX = ["", "Other", "Unknown", "X", "transgender", "n/a", "?", "  "]
    for sx in AMBIG_SEX:
        for rm, rf in RANGES:
            # a value far above BOTH ranges would normally flag high — must NOT.
            hi_val = max(float(rm.split("-")[1]), float(rf.split("-")[1])) + 100
            lo_val = min(float(rm.split("-")[0]), float(rf.split("-")[0])) - 100
            for v in (hi_val, lo_val):
                h = build(sx, [("N", "P", "u", rm, rf)], [str(v)])
                t.has(h, "M:", f"ambig shows M: sex={sx!r} {rm}|{rf}")
                t.has(h, "F:", f"ambig shows F: sex={sx!r} {rm}|{rf}")
                t.has(h, rm, f"ambig shows male range sex={sx!r}")
                t.has(h, rf, f"ambig shows female range sex={sx!r}")
                t.check(
                    ARROW_UP not in h and ARROW_DOWN not in h,
                    f"ambig never flags sex={sx!r} {rm}|{rf} v={v}",
                )

    # When the two ranges are IDENTICAL, even an unknown sex collapses to a
    # single range AND flags normally (no ambiguity to guard against).
    t.section("identical M==F ranges: single range + flags even when sex unknown")
    # (ref, value, expect_up) — 999999 is above the closed/upper-bound ranges
    # (-> high) but a '>40' lower bound is satisfied by it (-> Normal, no arrow).
    SAME = [
        ("70-100", "999999", True),
        ("0-5", "999999", True),
        ("3.5-5.0", "999999", True),
        ("<=200", "999999", True),
        (">40", "999999", False),
        (">40", "1", False),  # 1<40 -> low (no up)
        ("70-100", "1", False),
    ]  # 1 below 70 -> low (no up)
    for sx in ["", "Other", "Male", "Female", "Unknown"]:
        for ref, val, expect_up in SAME:
            h = build(sx, [("N", "P", "u", ref, ref)], [val])
            t.check("M:</span>" not in h, f"same range no M:/F: split sx={sx!r} ref={ref}")
            if expect_up:
                t.check(ARROW_UP in h, f"same range flags high sx={sx!r} ref={ref} v={val}")
            else:
                # value satisfies the open lower bound -> Normal, no arrow
                t.check(ARROW_UP not in h, f"same range no high sx={sx!r} ref={ref} v={val}")

    # =====================================================================
    # 3. Open-bound ranges (<= / >=) select per sex and flag correctly.
    # =====================================================================
    t.section("open-bound ranges per sex")
    OPEN = [
        ("<= 200", "<= 150"),  # cholesterol-style upper bound, female lower
        ("< 40", "< 35"),
        ("> 40", "> 50"),  # HDL-style lower bound
        (">= 13", ">= 12"),
    ]
    for rm, rf in OPEN:
        for sex, ref in [("Male", rm), ("Female", rf)]:
            import re as _re

            mlt = _re.match(r"^<\s*=?\s*(-?\d+\.?\d*)", ref.replace("≤", "<="))
            if mlt:
                bound = float(mlt.group(1))
                # above bound -> high
                h = build(sex, [("N", "P", "u", rm, rf)], [str(bound + 10)])
                t.check(ARROW_UP in h, f"open<= above high {sex} {ref}")
                t.check(ARROW_DOWN not in h, f"open<= above not low {sex} {ref}")
                # at/below bound -> normal
                h = build(sex, [("N", "P", "u", rm, rf)], [str(bound - 10)])
                t.check(
                    ARROW_UP not in h and ARROW_DOWN not in h, f"open<= below normal {sex} {ref}"
                )
            else:
                mgt = _re.match(r"^>\s*=?\s*(-?\d+\.?\d*)", ref)
                bound = float(mgt.group(1))
                # below bound -> low
                h = build(sex, [("N", "P", "u", rm, rf)], [str(bound - 10)])
                t.check(ARROW_DOWN in h, f"open> below low {sex} {ref}")
                t.check(ARROW_UP not in h, f"open> below not high {sex} {ref}")
                # above bound -> normal
                h = build(sex, [("N", "P", "u", rm, rf)], [str(bound + 10)])
                t.check(
                    ARROW_UP not in h and ARROW_DOWN not in h, f"open> above normal {sex} {ref}"
                )

    # =====================================================================
    # 4. hidden results excluded from the report.
    # =====================================================================
    t.section("hidden rows excluded")
    # A 3-param test: hide each subset; the hidden parameter's name must vanish
    # while the visible ones (and their values) remain.
    NAMES = ["AlphaName", "BetaName", "GammaName"]
    VALS = ["111", "222", "333"]
    for mask in itertools.product((0, 1), repeat=3):
        if all(mask):
            continue  # at least one visible row needed for a meaningful check
        params = [("N", NAMES[i], "u", "1-1000", "1-1000") for i in range(3)]
        h = build("Male", params, VALS, list(mask))
        for i in range(3):
            if mask[i]:
                t.check(NAMES[i] not in h, f"hidden[{mask}] hides {NAMES[i]}")
                t.check(VALS[i] not in h, f"hidden[{mask}] hides value {VALS[i]}")
            else:
                t.has(h, NAMES[i], f"hidden[{mask}] keeps {NAMES[i]}")
                t.has(h, VALS[i], f"hidden[{mask}] keeps value {VALS[i]}")

    # All-hidden -> report falls back to the "No result entered." placeholder.
    t.section("all-hidden -> placeholder")
    for k in range(1, 5):
        params = [("N", f"Z{j}", "u", "1-9", "1-9") for j in range(k)]
        h = build("Male", params, [str(j) for j in range(k)], [1] * k)
        t.has(h, "No result entered", f"all-hidden({k}) -> placeholder")
        for j in range(k):
            t.check(f"Z{j}" not in h, f"all-hidden({k}) hides Z{j}")

    # A hidden OUT-OF-RANGE row must not leak its arrow into the report either.
    t.section("hidden out-of-range leaks no arrow")
    for sex in ("Male", "Female"):
        # one visible in-range row + one hidden wildly-out-of-range row
        params = [("N", "Vis", "u", "1-10", "1-10"), ("N", "HidHigh", "u", "1-10", "1-10")]
        h = build(sex, params, ["5", "99999"], [0, 1])
        t.check(ARROW_UP not in h, f"hidden high row no up-arrow {sex}")
        t.check("HidHigh" not in h, f"hidden high row name gone {sex}")
        t.has(h, "Vis", f"visible normal row kept {sex}")

    # =====================================================================
    # 5. part_type handling: H heading -> subhead row; N -> result row.
    # =====================================================================
    t.section("part_type: H heading vs N result rows")
    for heading in ["COMPLETE BLOOD COUNT", "Lipid Profile", "URINE R/E", "X"]:
        params = [("H", heading, "", "", ""), ("N", "Result1", "u", "1-100", "1-100")]
        h = build("Male", params, ["", "50"], [0, 0])
        t.has(h, "subhead", f"H row -> subhead class ({heading})")
        t.has(h, heading, f"heading text shown ({heading})")
        t.has(h, "Result1", f"N result row shown under heading ({heading})")
        # lowercase 'h' part_type still treated as heading (.upper())
        h2 = build(
            "Male", [("h", heading, "", "", ""), ("N", "R", "u", "1-100", "1-100")], ["", "50"]
        )
        t.has(h2, "subhead", f"lowercase h -> subhead ({heading})")

    # A hidden heading row is dropped (hidden checked before part_type).
    t.section("hidden heading row dropped")
    for heading in ["HIDDEN_HEAD_A", "HIDDEN_HEAD_B"]:
        h = build(
            "Male",
            [("H", heading, "", "", ""), ("N", "R", "u", "1-100", "1-100")],
            ["", "50"],
            [1, 0],
        )
        t.check(heading not in h, f"hidden heading {heading} dropped")
        t.has(h, "R", f"sibling result kept when heading hidden ({heading})")

    # =====================================================================
    # 6. Value-cell placeholder: empty value -> em-dash, no flag.
    # =====================================================================
    t.section("empty value -> placeholder, no flag")
    for ref in ["13-17", "<=200", ">40", "1-1000"]:
        h = build("Male", [("N", "Empty", "u", ref, ref)], [""])
        # empty value renders the em-dash placeholder cell; never an arrow
        t.check(ARROW_UP not in h and ARROW_DOWN not in h, f"empty value no flag ref={ref}")
        t.has(h, "—", f"empty value placeholder em-dash ref={ref}")

    # =====================================================================
    # 7. Non-numeric values never flag (Positive/Negative/etc.).
    # =====================================================================
    t.section("non-numeric values never flag")
    for val in ["Positive", "Negative", "Reactive", "Nil", "Trace", "++", "N/A", "see note"]:
        for sex in ("Male", "Female", ""):
            h = build(sex, [("N", "Qual", "u", "13-17", "12-15")], [val])
            t.check(
                ARROW_UP not in h and ARROW_DOWN not in h,
                f"non-numeric {val!r} no flag sex={sex!r}",
            )
            t.has(h, val, f"non-numeric {val!r} value shown sex={sex!r}")

    # =====================================================================
    # 8. Direct helper checks: _resolve_ref / _flag / _flag_arrow boundaries.
    # =====================================================================
    t.section("helper _flag numeric boundaries")
    report = t.report
    FLAG_RANGES = ["13-17", "0-4", "70-100", "4.5-6.5", "100-200", "-5-5"]
    for ref in FLAG_RANGES:
        nums = ref.lstrip("-").split("-")
        # handle the negative-low "-5-5" case
        if ref.startswith("-"):
            lo, hi = -float(nums[0]), float(nums[1])
        else:
            lo, hi = float(nums[0]), float(nums[1])
        t.eq(report._flag(lo - 3, ref)[0], "Low", f"_flag below {ref}")
        t.eq(report._flag(lo, ref)[0], "Normal", f"_flag lo-bound {ref}")
        t.eq(report._flag((lo + hi) / 2, ref)[0], "Normal", f"_flag mid {ref}")
        t.eq(report._flag(hi, ref)[0], "Normal", f"_flag hi-bound {ref}")
        t.eq(report._flag(hi + 3, ref)[0], "High", f"_flag above {ref}")
    # open bounds
    for n in [40, 200, 0, -10, 5.5]:
        t.eq(report._flag(n + 5, f"<= {n}")[0], "High", f"_flag <= above {n}")
        t.eq(report._flag(n - 0.5, f"<= {n}")[0], "Normal", f"_flag <= at/below {n}")
        t.eq(report._flag(n - 5, f"> {n}")[0], "Low", f"_flag > below {n}")
        t.eq(report._flag(n + 0.5, f"> {n}")[0], "Normal", f"_flag > above {n}")
    # garbage / None / unparseable refs -> no flag
    for v in ["abc", None, "", "Positive", "12,000"]:
        t.check(
            report._flag(v, "10-20") is None or v == "12,000",
            f"_flag non-numeric value {v!r} -> None",
        )
    # comma-stripped numeric value still parses
    t.eq(report._flag("12,000", "0-5000")[0], "High", "_flag strips comma 12,000")
    # ref with no recognizable numbers -> None
    for ref in ["see comment", "Negative", "", None, "N/A"]:
        t.check(report._flag(10, ref) is None, f"_flag unparseable ref {ref!r} -> None")

    # _flag_arrow maps High->↑/high, Low->↓/low, Normal->None
    t.section("helper _flag_arrow mapping")
    t.eq(report._flag_arrow(99, "10-20"), (ARROW_UP, "high"), "arrow high")
    t.eq(report._flag_arrow(1, "10-20"), (ARROW_DOWN, "low"), "arrow low")
    t.check(report._flag_arrow(15, "10-20") is None, "arrow normal -> None")
    t.check(report._flag_arrow("Positive", "10-20") is None, "arrow non-numeric -> None")
    t.check(report._flag_arrow(None, "10-20") is None, "arrow None -> None")

    # _resolve_ref direct: gender pick + ambiguous guard + fallback.
    t.section("helper _resolve_ref selection")
    import sqlite3 as _sqlite3

    con = t.con

    def _row(p_male, p_female, ref_text=""):
        con.row_factory = _sqlite3.Row
        return con.execute(
            "SELECT ? AS p_male, ? AS p_female, ? AS ref_text",
            (p_male, p_female, ref_text),
        ).fetchone()

    PAIRS = [("13-17", "12-15"), ("0-4", "0-1"), ("A", "B"), ("5-9", "5-9")]
    for m, f in PAIRS:
        disp_m, flag_m = report._resolve_ref(_row(m, f), "Male")
        t.eq(flag_m, m, f"resolve male flag-range {m}|{f}")
        t.has(disp_m, m, f"resolve male shows {m}")
        disp_f, flag_f = report._resolve_ref(_row(m, f), "Female")
        t.eq(flag_f, f, f"resolve female flag-range {m}|{f}")
        disp_u, flag_u = report._resolve_ref(_row(m, f), "")
        if m != f:
            t.eq(flag_u, "", f"resolve unknown differing -> no flag {m}|{f}")
            t.has(disp_u, "M:", f"resolve unknown shows M: {m}|{f}")
            t.has(disp_u, "F:", f"resolve unknown shows F: {m}|{f}")
        else:
            t.eq(flag_u, m, f"resolve unknown identical -> single range {m}")
    # only one range present -> used regardless of sex / ambiguity
    for sex in ("Male", "Female", ""):
        d, fl = report._resolve_ref(_row("7-9", ""), sex)
        t.eq(fl, "7-9", f"resolve only-male used for sex={sex!r}")
        d2, fl2 = report._resolve_ref(_row("", "3-4"), sex)
        t.eq(fl2, "3-4", f"resolve only-female used for sex={sex!r}")
    # both empty -> ref_text fallback
    d, fl = report._resolve_ref(_row("", "", "fallback-range"), "Male")
    t.eq(fl, "fallback-range", "resolve falls back to ref_text")
    t.has(d, "fallback-range", "resolve fallback shown")

    # =====================================================================
    # 9. Extreme / large values still classify correctly.
    # =====================================================================
    t.section("extreme values")
    for sex, ref in [("Male", "13-17"), ("Female", "12-15")]:
        for v, want_up in [("1e9", True), ("0", False), ("999999999", True)]:
            h = build(sex, [("N", "Ext", "u", "13-17", "12-15")], [v])
            if v == "0":
                # 0 is below both ranges -> low for the selected range
                t.check(ARROW_DOWN in h, f"extreme 0 -> low {sex}")
            else:
                t.check(ARROW_UP in h, f"extreme {v} -> high {sex}")
