"""Generator — amount-in-words (Indian/Pakistani numbering) invariants.

Focus: src/labdesk/report.py :: _amount_in_words(amount)
  * exhaustive 0..2000 against an independent reference
  * lakh / crore boundary phrasings
  * exact known phrasings for round / landmark numbers
  * every non-trivial output ends with " Rupees Only" and is non-empty
  * rounding of fractional rupees, None/garbage inputs, large/extreme values

Assertions only via t.check / t.eq / t.near / t.has.
"""
from __future__ import annotations

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
         "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
         "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n):
    # n in 0..99
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + ((" " + _ONES[n % 10]) if n % 10 else "")).strip()


def _three(n):
    # n in 0..999
    out = ""
    if n >= 100:
        out = _ONES[n // 100] + " Hundred"
        n %= 100
        if n:
            out += " "
    return (out + _two(n)).strip()


def _ref_words(amount):
    """Independent reference reimplementation of the intended algorithm
    (Indian numbering: crore / lakh / thousand / hundred)."""
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


def register(t):
    w = t.report._amount_in_words

    # ------------------------------------------------------------------ #
    # 1. Exhaustive 0..2000 vs independent reference + universal invariants
    # ------------------------------------------------------------------ #
    t.section("exhaustive 0..2000 vs reference")
    for v in range(0, 2001):
        got = w(v)
        t.eq(got, _ref_words(v), f"words({v})")
        t.check(bool(got), f"non-empty({v})")
        t.check(got.endswith("Rupees Only"), f"ends-with-Rupees-Only({v})")
        # exactly one trailing 'Rupees Only', no stray double spaces / leading space
        t.check("  " not in got, f"no-double-space({v})")
        t.check(not got.startswith(" "), f"no-leading-space({v})")

    # ------------------------------------------------------------------ #
    # 2. Exact known phrasings for landmark / round numbers
    # ------------------------------------------------------------------ #
    t.section("exact landmark phrasings")
    KNOWN = {
        0: "Zero Rupees Only",
        1: "One Rupees Only",
        9: "Nine Rupees Only",
        10: "Ten Rupees Only",
        11: "Eleven Rupees Only",
        15: "Fifteen Rupees Only",
        19: "Nineteen Rupees Only",
        20: "Twenty Rupees Only",
        21: "Twenty One Rupees Only",
        29: "Twenty Nine Rupees Only",
        50: "Fifty Rupees Only",
        99: "Ninety Nine Rupees Only",
        100: "One Hundred Rupees Only",
        101: "One Hundred One Rupees Only",
        110: "One Hundred Ten Rupees Only",
        111: "One Hundred Eleven Rupees Only",
        119: "One Hundred Nineteen Rupees Only",
        120: "One Hundred Twenty Rupees Only",
        199: "One Hundred Ninety Nine Rupees Only",
        200: "Two Hundred Rupees Only",
        500: "Five Hundred Rupees Only",
        999: "Nine Hundred Ninety Nine Rupees Only",
        1000: "One Thousand Rupees Only",
        1001: "One Thousand One Rupees Only",
        1100: "One Thousand One Hundred Rupees Only",
        1234: "One Thousand Two Hundred Thirty Four Rupees Only",
        2000: "Two Thousand Rupees Only",
        5000: "Five Thousand Rupees Only",
        10000: "Ten Thousand Rupees Only",
        10500: "Ten Thousand Five Hundred Rupees Only",
        99999: "Ninety Nine Thousand Nine Hundred Ninety Nine Rupees Only",
        100000: "One Lakh Rupees Only",
        100001: "One Lakh One Rupees Only",
        101000: "One Lakh One Thousand Rupees Only",
        123456: "One Lakh Twenty Three Thousand Four Hundred Fifty Six Rupees Only",
        150000: "One Lakh Fifty Thousand Rupees Only",
        1000000: "Ten Lakh Rupees Only",
        1500000: "Fifteen Lakh Rupees Only",
        9900000: "Ninety Nine Lakh Rupees Only",
        9999999: "Ninety Nine Lakh Ninety Nine Thousand Nine Hundred Ninety Nine Rupees Only",
        10000000: "One Crore Rupees Only",
        10000001: "One Crore One Rupees Only",
        10100000: "One Crore One Lakh Rupees Only",
        12345678: ("One Crore Twenty Three Lakh Forty Five Thousand "
                   "Six Hundred Seventy Eight Rupees Only"),
        99999999: ("Nine Crore Ninety Nine Lakh Ninety Nine Thousand "
                   "Nine Hundred Ninety Nine Rupees Only"),
        100000000: "Ten Crore Rupees Only",
        990000000: "Ninety Nine Crore Rupees Only",
    }
    for v, expected in KNOWN.items():
        t.eq(w(v), expected, f"landmark({v})")

    # ------------------------------------------------------------------ #
    # 3. Lakh / crore boundaries — every value straddling a unit boundary
    # ------------------------------------------------------------------ #
    t.section("lakh/crore boundaries")
    boundaries = []
    for base in (1000, 100_000, 10_000_000):           # thousand, lakh, crore
        for k in (1, 2, 9, 10, 11, 99):
            center = base * k
            for d in (-2, -1, 0, 1, 2):
                boundaries.append(center + d)
    # crore multiples up to 99 crore (within _two's valid 0..99 domain)
    for c in range(0, 100):
        boundaries.append(c * 10_000_000)
    # lakh multiples 0..99
    for lk in range(0, 100):
        boundaries.append(lk * 100_000)
    for v in sorted({b for b in boundaries if b >= 0}):
        got = w(v)
        t.eq(got, _ref_words(v), f"boundary({v})")
        t.check(got.endswith("Rupees Only") and bool(got), f"boundary-suffix({v})")

    # ------------------------------------------------------------------ #
    # 4. Component-name sanity (right unit word shows up; absent when zero)
    # ------------------------------------------------------------------ #
    t.section("component presence")
    t.has(w(10_000_000), "Crore", "crore-present")
    t.has(w(100_000), "Lakh", "lakh-present")
    t.has(w(1000), "Thousand", "thousand-present")
    t.has(w(100), "Hundred", "hundred-present")
    t.check("Crore" not in w(999_9999 % 999_9999 or 99_99_999), "no-crore-under-1cr")
    t.check("Crore" not in w(50), "no-crore-small")
    t.check("Lakh" not in w(999), "no-lakh-small")
    t.check("Thousand" not in w(999), "no-thousand-small")
    t.check("Hundred" not in w(99), "no-hundred-small")
    # 'Zero' only for the literal zero amount
    t.eq(w(0), "Zero Rupees Only", "zero-exact")
    t.check("Zero" not in w(105), "no-spurious-zero")

    # ------------------------------------------------------------------ #
    # 5. Rounding of fractional rupees (round() = banker's rounding)
    # ------------------------------------------------------------------ #
    t.section("fractional rounding")
    frac_cases = {
        0.0: "Zero Rupees Only",
        0.4: "Zero Rupees Only",
        0.5: "Zero Rupees Only",      # banker's: round(0.5)==0
        0.6: "One Rupees Only",
        1.5: "Two Rupees Only",       # banker's: round(1.5)==2
        2.5: "Two Rupees Only",       # banker's: round(2.5)==2
        99.49: "Ninety Nine Rupees Only",
        99.5: "One Hundred Rupees Only",   # round(99.5)==100
        999.6: "One Thousand Rupees Only",
        1000.49: "One Thousand Rupees Only",
    }
    for v, expected in frac_cases.items():
        t.eq(w(v), expected, f"frac({v})")
    # round-trip: words(x) == words(round(x)) for assorted fractions
    for v in [12.3, 45.7, 250.49, 250.51, 1234.5, 99999.49, 123456.8]:
        t.eq(w(v), w(round(v)), f"frac-roundtrip({v})")

    # ------------------------------------------------------------------ #
    # 6. None / falsy / garbage-ish numeric inputs
    # ------------------------------------------------------------------ #
    t.section("None / edge inputs")
    t.eq(w(None), "Zero Rupees Only", "none-is-zero")
    t.eq(w(0), "Zero Rupees Only", "int-zero")
    t.eq(w(0.0), "Zero Rupees Only", "float-zero")
    t.eq(w(-0.0), "Zero Rupees Only", "neg-zero")
    t.eq(w(False), "Zero Rupees Only", "bool-false")
    t.eq(w(True), "One Rupees Only", "bool-true-is-one")

    # ------------------------------------------------------------------ #
    # 7. Large / extreme values within the helper's valid domain (<100 crore)
    # ------------------------------------------------------------------ #
    t.section("large/extreme values")
    extremes = [
        25_00_00_000, 50_00_00_000, 75_00_00_000,
        98_76_54_321, 99_00_00_000, 99_99_99_999,   # 99,99,99,999 = max < 100cr
    ]
    for v in extremes:
        got = w(v)
        t.eq(got, _ref_words(v), f"extreme({v})")
        t.check(got.endswith("Rupees Only") and bool(got), f"extreme-suffix({v})")
    # densely sample a strip just below the 100-crore ceiling
    for v in range(99_99_99_900, 100_00_00_000):
        t.eq(w(v), _ref_words(v), f"ceiling({v})")

    # ------------------------------------------------------------------ #
    # 8. Structural invariants over a broad random-ish stride
    # ------------------------------------------------------------------ #
    t.section("structural invariants (broad stride)")
    for v in range(0, 99_99_99_999, 137_911):
        got = w(v)
        t.eq(got, _ref_words(v), f"stride({v})")
        t.check(got.endswith(" Rupees Only") or got == "Zero Rupees Only",
                f"stride-suffix({v})")
        t.check("  " not in got, f"stride-no-double-space({v})")
