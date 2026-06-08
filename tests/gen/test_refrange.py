"""Generator — reference-range flagging invariants for report._flag.

Covers every textual ref form _flag understands:
  * "lo - hi" closed range            -> Low / Normal / High
  * "<= n" and "< n" upper open bound -> Normal / High   (both strict v>n)
  * ">= n" and "> n" lower open bound  -> Normal / Low    (both strict v<n)
  * non-numeric / empty / garbage values -> None (must never crash)

Boundary behaviour is asserted against the REAL implementation contract:
  - range: v<lo -> Low, v>hi -> High, lo<=v<=hi -> Normal
  - upper open: v>n -> High else Normal   (NOTE: at v==n both "<" and "<=" -> Normal)
  - lower open: v<n -> Low  else Normal   (NOTE: at v==n both ">" and ">=" -> Normal)

Colours: GREEN=#059669 (Normal), AMBER=#d97706 (Low), RED=#dc2626 (High).
This module alone emits well over 5,000 cases.
"""

from __future__ import annotations

GREEN = "#059669"
AMBER = "#d97706"
RED = "#dc2626"

LOW = ("Low", AMBER)
NORMAL = ("Normal", GREEN)
HIGH = ("High", RED)


def register(t):
    flag = t.report._flag

    # ------------------------------------------------------------------
    # 1. Closed range "lo - hi": fine steps at and around both boundaries
    # ------------------------------------------------------------------
    t.section("closed range lo - hi (Low/Normal/High, fine steps)")
    RANGES = [
        (0.0, 100.0),
        (3.5, 5.5),
        (12.0, 16.0),
        (70.0, 110.0),
        (0.5, 1.2),
        (135.0, 145.0),
        (-5.0, 5.0),  # negative lower bound
        (10.0, 10.0),  # degenerate lo==hi
        (40.0, 60.0),
        (1.0, 9.0),
    ]

    # textual presentations of the same range that must behave identically
    def range_texts(lo, hi):
        return [
            f"{lo} - {hi}",
            f"{lo}-{hi}",
            f"{lo} - {hi}",
            f"  {lo}   -   {hi}  ",
            f"{lo}–{hi}",  # en-dash normalised to '-'
            f"Normal: {lo} - {hi} mg/dL",  # surrounding text, search finds range
        ]

    for lo, hi in RANGES:
        span = hi - lo
        step = max(span / 20.0, 0.05)
        # sample values from below lo to above hi
        vals = []
        x = lo - 3 * step
        while x <= hi + 3 * step + 1e-9:
            vals.append(round(x, 6))
            x += step
        # plus exact boundaries and tiny offsets
        eps = 1e-6
        vals += [lo, hi, lo - eps, lo + eps, hi - eps, hi + eps, lo - 1e-9, hi + 1e-9]
        for ref in range_texts(lo, hi):
            for v in vals:
                if v < lo:
                    want = LOW
                elif v > hi:
                    want = HIGH
                else:
                    want = NORMAL
                got = flag(v, ref)
                t.eq(got, want, f"range '{ref}' v={v}")
                # string-form value must agree with float-form value
                t.eq(flag(str(v), ref), want, f"range str '{ref}' v={v}")

    # exact-boundary contract spelled out explicitly
    for lo, hi in RANGES:
        ref = f"{lo} - {hi}"
        t.eq(flag(lo, ref), NORMAL, f"v==lo Normal '{ref}'")
        t.eq(flag(hi, ref), NORMAL, f"v==hi Normal '{ref}'")

    # ------------------------------------------------------------------
    # 2. Upper open bound "< n" and "<= n"  -> Normal / High
    #    contract: High iff v > n  (strict, for BOTH operators)
    # ------------------------------------------------------------------
    t.section("upper open bound (< n / <= n)")
    BOUNDS = [0.0, 1.0, 5.5, 99.0, 100.0, 150.0, 200.0, -10.0, 7.25]
    for n in BOUNDS:
        step = 0.5
        vals = []
        x = n - 5 * step
        while x <= n + 5 * step + 1e-9:
            vals.append(round(x, 6))
            x += step
        eps = 1e-6
        vals += [n, n - eps, n + eps, n - 1e-9, n + 1e-9]
        for op in ("<", "<="):
            for sp in ("", " "):
                ref = f"{op}{sp}{n}"
                for v in vals:
                    want = HIGH if v > n else NORMAL
                    t.eq(flag(v, ref), want, f"upper '{ref}' v={v}")
        # the ≤ unicode form normalises to '<=' -> identical contract
        ref_uni = f"≤ {n}"
        for v in vals:
            want = HIGH if v > n else NORMAL
            t.eq(flag(v, ref_uni), want, f"upper uni '{ref_uni}' v={v}")
        # exact boundary: v==n is Normal for both '<' and '<='
        t.eq(flag(n, f"< {n}"), NORMAL, f"v==n Normal '< {n}'")
        t.eq(flag(n, f"<= {n}"), NORMAL, f"v==n Normal '<= {n}'")

    # leading-operator-wins: "< 200 (ideal 0-99)" judged on <200 not the range
    t.eq(flag(150, "< 200 (ideal 0-99)"), NORMAL, "leading < beats parenthetical range")
    t.eq(flag(250, "< 200 (ideal 0-99)"), HIGH, "leading < High beats parenthetical")
    t.eq(flag(50, "<= 200 (ideal 0-99)"), NORMAL, "leading <= beats parenthetical range")

    # ------------------------------------------------------------------
    # 3. Lower open bound "> n" and ">= n"  -> Normal / Low
    #    contract: Low iff v < n (strict, for BOTH operators)
    # ------------------------------------------------------------------
    t.section("lower open bound (> n / >= n)")
    for n in BOUNDS:
        step = 0.5
        vals = []
        x = n - 5 * step
        while x <= n + 5 * step + 1e-9:
            vals.append(round(x, 6))
            x += step
        eps = 1e-6
        vals += [n, n - eps, n + eps, n - 1e-9, n + 1e-9]
        for op in (">", ">="):
            for sp in ("", " "):
                ref = f"{op}{sp}{n}"
                for v in vals:
                    want = LOW if v < n else NORMAL
                    t.eq(flag(v, ref), want, f"lower '{ref}' v={v}")
        ref_uni = f"≥ {n}"
        for v in vals:
            want = LOW if v < n else NORMAL
            t.eq(flag(v, ref_uni), want, f"lower uni '{ref_uni}' v={v}")
        t.eq(flag(n, f"> {n}"), NORMAL, f"v==n Normal '> {n}'")
        t.eq(flag(n, f">= {n}"), NORMAL, f"v==n Normal '>= {n}'")

    # leading ">" wins over a trailing range
    t.eq(flag(20, "> 10 (panic <5)"), NORMAL, "leading > beats parenthetical")
    t.eq(flag(2, "> 10 (panic <5)"), LOW, "leading > Low beats parenthetical")

    # ------------------------------------------------------------------
    # 4. Comma-stripping in the VALUE: "1,234" parses as 1234
    # ------------------------------------------------------------------
    t.section("comma stripping in value")
    t.eq(flag("1,234", "0 - 1000"), HIGH, "comma value 1,234 High")
    t.eq(flag("1,234", "0 - 2000"), NORMAL, "comma value 1,234 Normal")
    t.eq(flag("12,000", "> 5000"), NORMAL, "comma value 12,000 normal lower")
    t.eq(flag("1,000,000", "< 999999"), HIGH, "multi comma High")
    t.eq(flag(" 4,500 ", "0 - 5000"), NORMAL, "comma + spaces Normal")

    # ------------------------------------------------------------------
    # 5. Non-numeric / empty / None values -> None, never crash
    # ------------------------------------------------------------------
    t.section("non-numeric / empty / None values -> None")
    BAD_VALUES = [
        None,
        "",
        "   ",
        "abc",
        "Positive",
        "Negative",
        "Trace",
        "Nil",
        "N/A",
        "-",
        "+",
        "++",
        "+++",
        "see note",
        "pending",
        "TNTC",
        "1.2.3",
        "1-2",
        "<5",
        ">5",
        "5%",
        "10^3",
        "e",
        "nan%",
        "..",
        ",",
        "1..2",
        "++/-",
        "?",
        "*",
        "1 2",
        "0x10",
        "10mg",
        "yes",
        "no",
        "reactive",
        "non-reactive",
        "  positive  ",
    ]
    GOOD_REFS = ["0 - 100", "< 50", "> 5", "<= 10", ">= 1", "3.5 - 5.5"]
    for bv in BAD_VALUES:
        for ref in GOOD_REFS:
            got = flag(bv, ref)
            t.eq(got, None, f"non-numeric value {bv!r} ref {ref!r} -> None")

    # python float() DOES accept these special tokens — they are numeric.
    # Verify they don't crash and produce a defined label (real behaviour).
    t.section("float-parsable edge tokens (inf / nan / sci / signs)")
    for ref in GOOD_REFS:
        for tok in ["inf", "-inf", "+1", "  3.0  ", "1e2", ".5", "5.", "00"]:
            got = flag(tok, ref)
            # must not crash; result is None only if float() rejected it
            t.check(
                got is None or (isinstance(got, tuple) and len(got) == 2),
                f"edge token {tok!r} ref {ref!r} well-formed result",
            )
    # specific numeric checks for scientific / signed / leading-zero forms
    t.eq(flag("1e2", "0 - 50"), HIGH, "sci 1e2=100 High")
    t.eq(flag("1e2", "0 - 1000"), NORMAL, "sci 1e2=100 Normal")
    t.eq(flag(".5", "1 - 2"), LOW, "dot5 Low")
    t.eq(flag("5.", "1 - 2"), HIGH, "5dot High")
    t.eq(flag("+1", "0 - 2"), NORMAL, "+1 Normal")
    t.eq(flag("inf", "0 - 100"), HIGH, "inf above range High")
    t.eq(flag("-inf", "0 - 100"), LOW, "-inf below range Low")

    # ------------------------------------------------------------------
    # 6. Empty / unparsable REF -> None (no numeric pattern found)
    # ------------------------------------------------------------------
    t.section("empty / non-numeric ref -> None")
    BAD_REFS = [
        None,
        "",
        "   ",
        "normal",
        "see comment",
        "Negative",
        "refer clinician",
        "varies",
        "N/A",
        "--",
        "abc - def",
        "low to high",
        "x-y",
    ]
    for ref in BAD_REFS:
        for v in [0, 1, 5, 50, 100, -3, 99999]:
            t.eq(flag(v, ref), None, f"unparsable ref {ref!r} v={v} -> None")

    # ------------------------------------------------------------------
    # 7. Large / extreme magnitudes
    # ------------------------------------------------------------------
    t.section("large / extreme magnitudes")
    # Values formatted into the ref MUST avoid scientific notation, because the
    # numeric regex only matches plain decimal digits (mantissa+exponent would be
    # mis-parsed). Keep ref-side magnitudes where repr() has no 'e'.
    BIG = [1e6, 1e9, 1e12, 1e15]
    for b in BIG:
        assert "e" not in repr(b / 2) and "e" not in repr(b * 2)
        t.eq(flag(b, f"0 - {b/2:.0f}"), HIGH, f"big {b} High in 0-{b/2}")
        t.eq(flag(b, f"0 - {b*2:.0f}"), NORMAL, f"big {b} Normal in 0-{b*2}")
        t.eq(flag(-b, "0 - 100"), LOW, f"big-neg {-b} Low")
        t.eq(flag(b, f"< {b*2:.0f}"), NORMAL, f"big {b} Normal < {b*2}")
        t.eq(flag(b, f"< {b/2:.0f}"), HIGH, f"big {b} High < {b/2}")
        t.eq(flag(b, f"> {b*2:.0f}"), LOW, f"big {b} Low > {b*2}")
    # value-side scientific notation IS accepted by float() and judged correctly
    for tok, ref, want in [
        ("1e6", "0 - 5000000", NORMAL),
        ("1e6", "0 - 100", HIGH),
        ("1e9", "> 1000000000000", LOW),
        ("1e12", "< 1000000000", HIGH),
    ]:
        t.eq(flag(tok, ref), want, f"sci value {tok} ref {ref}")

    # ------------------------------------------------------------------
    # 8. Negative numbers in ranges and bounds
    # ------------------------------------------------------------------
    t.section("negative bounds / ranges")
    t.eq(flag(-3, "-5 - 5"), NORMAL, "neg in neg range Normal")
    t.eq(flag(-6, "-5 - 5"), LOW, "below neg range Low")
    t.eq(flag(6, "-5 - 5"), HIGH, "above neg range High")
    t.eq(flag(-5, "-5 - 5"), NORMAL, "at neg lower bound Normal")
    t.eq(flag(-10, "> -5"), LOW, "below neg lower bound Low")
    t.eq(flag(-1, "> -5"), NORMAL, "above neg lower bound Normal")
    t.eq(flag(-10, "< -5"), NORMAL, "below neg upper bound Normal")
    t.eq(flag(-1, "< -5"), HIGH, "above neg upper bound High")
