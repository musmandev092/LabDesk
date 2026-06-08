"""Phone normalization + WhatsApp recipient-id generator.

Sweeps src/labdesk/constants.py:normalize_phone and src/labdesk/whatsapp.py:wa_number
across every Pakistani operator code (300-349), many subscriber numbers, every
formatting variant (+92, 0092, 92, bare, dashed, spaced, messy whitespace), and a
large bank of invalid/garbage strings that must normalize/reject correctly.

Contract: expose exactly register(t); emit assertions only via t.check/t.eq/t.near/t.has.
This module alone emits well over 6,000 cases.
"""

from __future__ import annotations


def _expected_normalize(raw, cc="92"):
    """Pure-Python re-derivation of the documented invariant (NOT a copy of the
    implementation — derived from the spec in constants.py docstring) so a real
    regression in normalize_phone fails loudly instead of matching itself."""
    d = "".join(c for c in (raw or "") if c.isdigit())
    if not d:
        return ""
    if d.startswith("00"):
        d = d[2:]
    if d.startswith(cc) and len(d) >= len(cc) + 9:
        d = d[len(cc) :]
    d = d.lstrip("0")
    return ("0" + d) if d else ""


def register(t):
    nz = t.normalize_phone
    wa = t.whatsapp.wa_number

    # ----------------------------------------------------------------------
    # 1) Full operator x subscriber x formatting-variant sweep (cc = 92)
    # ----------------------------------------------------------------------
    t.section("operator 300-349 x subscribers x every formatting variant")
    operators = [f"3{a}{b}" for a in range(0, 5) for b in range(0, 10)]  # 300..349 (50)
    subs = [
        "1234567",
        "0000001",
        "9999999",
        "1122334",
        "7654321",
        "0001000",
        "5000005",
        "8675309",
    ]  # 8
    for op in operators:
        for sub in subs:
            canon = "0" + op + sub  # 03XXXXXXXXX  (11 digits)
            national = op + sub  # 3XXXXXXXXX   (10 digits)
            wanum = "92" + national  # 923XXXXXXXXX (12 digits)
            variants = [
                canon,  # 03001234567
                "+92" + national,  # +923001234567
                "0092" + national,  # 0092...
                "92" + national,  # 92...
                national,  # bare national (10 digits)
                f"0{op}-{sub}",  # dashed
                f"0{op} {sub}",  # spaced
                f" +92 {op} {sub} ",  # messy with +92 and outer spaces
                f"\t0{op}\n{sub}\r",  # tabs/newlines as separators
                f"(0{op}) {sub}",  # parenthesised area-ish
                f"+92-{op}-{sub}",  # +92 dashed
                f"0092 {op} {sub}",  # 0092 spaced
                f"92.{op}.{sub}",  # dotted with cc
            ]
            for v in variants:
                t.eq(nz(v), canon, f"normalize({v!r})")
                t.eq(wa(v, "92"), wanum, f"wa_number({v!r})")
            # idempotence: normalizing the canonical form is a fixed point
            t.eq(nz(canon), canon, f"idempotent normalize({canon})")
            # wa_number is derivable from normalize: 92 + national
            t.eq(wa(canon, "92"), "92" + canon.lstrip("0"), f"wa consistency {canon}")

    # ----------------------------------------------------------------------
    # 2) Invalid / garbage that wa_number MUST reject (None) for cc=92
    # ----------------------------------------------------------------------
    t.section("garbage + malformed phones rejected by wa_number (cc=92)")
    garbage = [
        "",
        "   ",
        "\t\n",
        "abc",
        "phone",
        "n/a",
        "null",
        "None",
        "-",
        "--",
        "()-",
        "....",
        "++",
        "+",
        "9-2",
        "0300abc",
        "call me",
        "0xFF",
        "0",
        "00",
        "000",
        "0000",
        "0000000",
        "0000000000",
        "1",
        "12",
        "123",
        "1234",
        "12345",
        "123456",
        "1234567",
        "92",
        "920",
        "9200",
        "0092",
        "+92",
        "+920",
        "300",
        "0300",
        "03001234",
        "0300123456",  # too short
        "030012345678",
        "0300123456789",
        "0300123456789012",  # too long
        "923001234",  # 92 + short national
        "92300123456789",  # 92 + too-long national
        "421234567",
        "0421234567",
        "+92421234567",  # landline (op '42')
        "2001234567",
        "0200123456",
        "1001234567",  # national not starting with 3
        "0350123456",
        "0299123456",  # out-of-range / wrong prefix shape
        "🙂📞",
        "phone:0300",
        "300x123",
    ]
    for bad in garbage:
        t.check(wa(bad, "92") is None, f"wa_number rejects {bad!r}")

    # garbage that contains NO digits → normalize must return "" exactly
    t.section("digit-free input normalizes to empty string")
    nodigits = [
        "",
        "   ",
        "abc",
        "phone",
        "+-+-",
        "()",
        "...",
        "\t\n\r",
        "hello world",
        "N/A",
        "----",
        "++++",
        "  +  ",
        "no number here",
    ]
    for s in nodigits:
        t.eq(nz(s), "", f"normalize empty for {s!r}")
        t.check(wa(s, "92") is None, f"wa_number None for digit-free {s!r}")

    # ----------------------------------------------------------------------
    # 3) Structural invariants over a broad random-ish digit sweep
    # ----------------------------------------------------------------------
    t.section("structural invariants: normalize output shape")
    # systematically vary national-number length to probe the wa_number gate
    for op in ["300", "315", "321", "333", "345", "349"]:
        for extra_len in range(0, 14):
            tail = "".join(str(d % 10) for d in range(extra_len))
            national = op + tail
            raw = "0" + national
            out = nz(raw)
            # normalize: always either "" or starts with single leading 0 and no extra zeros
            if out:
                t.check(out.startswith("0"), f"norm starts with 0 ({raw!r})")
                t.check(not out.startswith("00"), f"norm no double-zero ({raw!r})")
                t.check(
                    out[1:] == out[1:].lstrip("0") or out == "0",
                    f"norm core has no leading zero ({raw!r})",
                )
            w = wa(raw, "92")
            if w is not None:
                # only a clean 10-digit national starting with 3 is accepted
                t.eq(len(national), 10, f"wa accepted => national 10 digits ({raw!r})")
                t.check(national.startswith("3"), f"wa accepted => starts 3 ({raw!r})")
                t.eq(w, "92" + national, f"wa value ({raw!r})")
            else:
                # rejected => national is NOT a clean 10-digit 3-prefixed number
                t.check(
                    not (len(national) == 10 and national.startswith("3")),
                    f"wa rejected only when malformed ({raw!r})",
                )

    # ----------------------------------------------------------------------
    # 4) Equivalence: every formatting variant of one number maps identically
    # ----------------------------------------------------------------------
    t.section("formatting-variant equivalence classes")
    bases = ["3001234567", "3219876543", "3451122334", "3119998887", "3050000001"]
    for national in bases:
        op, sub = national[:3], national[3:]
        canon = "0" + national
        wanum = "92" + national
        forms = [
            canon,
            national,
            "+92" + national,
            "0092" + national,
            "92" + national,
            "  " + canon + "  ",
            "+92 " + national,
            "0092-" + national,
            f"0{op}-{sub}",
            f"0{op} {sub}",
            f"+92-{op}-{sub}",
            f"00 92 {national}",
            f"  92 {op} {sub} ",
        ]
        norms = {nz(f) for f in forms}
        t.eq(len(norms), 1, f"all variants of {national} agree on normalize")
        t.eq(next(iter(norms)), canon, f"variant class canon for {national}")
        wanums = {wa(f, "92") for f in forms}
        t.eq(len(wanums), 1, f"all variants of {national} agree on wa_number")
        t.eq(next(iter(wanums)), wanum, f"variant class wa for {national}")

    # ----------------------------------------------------------------------
    # 5) Re-derived expected normalize over a dense generated corpus
    # ----------------------------------------------------------------------
    t.section("normalize matches re-derived spec over dense corpus")
    corpus = []
    for op in operators[::3]:  # subsample operators
        for sub in ["1234567", "0007000", "9090909"]:
            national = op + sub
            corpus += [
                "0" + national,
                national,
                "+92" + national,
                "0092" + national,
                "92" + national,
                "  0" + national,
                "+92-" + national,
                "00 0 " + national,
            ]
    # plus pure structural oddities
    corpus += [
        "00",
        "000",
        "0092",
        "92",
        "920",
        "9200000000000",
        "0000003001234567",
        "0030000300",
        "12345",
        "9923001234567",
        "0092092",
        "00922",
        "0092 0 300 1234567",
    ]
    for raw in corpus:
        t.eq(nz(raw), _expected_normalize(raw, "92"), f"normalize spec match {raw!r}")

    # ----------------------------------------------------------------------
    # 6) Non-PK country codes: wa_number length gate (9..13 national digits)
    # ----------------------------------------------------------------------
    t.section("non-PK country codes: national length gate 9..13")
    for cc in ["1", "44", "971", "880"]:
        # national lengths 0..15, build from a leading 7 (generic mobile-ish)
        for ln in range(0, 16):
            national = ("7" + "1234567890123456"[: ln - 1]) if ln >= 1 else ""
            raw = national  # bare national, no leading 0
            local = nz(raw, cc)
            w = wa(raw, cc)
            if not local:
                t.check(w is None, f"cc={cc} empty-local => wa None ({raw!r})")
                continue
            nat2 = local.lstrip("0")
            if 9 <= len(nat2) <= 13:
                t.eq(w, cc + nat2, f"cc={cc} accept national len {len(nat2)}")
            else:
                t.check(w is None, f"cc={cc} reject national len {len(nat2)}")

    # a few explicit non-PK acceptances/rejections
    t.eq(wa("4477009001234", "44"), "4477009001234", "uk-ish strip-and-prefix")
    t.check(wa("712", "44") is None, "cc44 too-short rejected")
    t.check(wa("", "1") is None, "cc1 empty rejected")

    # ----------------------------------------------------------------------
    # 7) Boundary: exactly-at-threshold cc stripping (len == cc+9)
    # ----------------------------------------------------------------------
    t.section("cc-strip threshold boundaries")
    # "92" + national where national is exactly 9 vs 10 digits
    # len("92"+9digits)=11 == cc+9 -> strip cc -> 9-digit local (no leading 0 added beyond one)
    nine = "923456789"  # "92"+"3456789" actually 9 digits total
    # build precisely: cc='92', need total len 11 to trigger strip
    eleven = "92" + "300123456"  # 11 digits: strips -> "300123456" -> "0300123456" (10 long)
    twelve = "92" + "3001234567"  # 12 digits: strips -> national -> canon valid
    t.eq(nz(eleven, "92"), _expected_normalize(eleven, "92"), "strip at len==cc+9")
    t.eq(nz(twelve, "92"), "03001234567", "strip at len==cc+10 valid mobile")
    t.check(wa(twelve, "92") == "923001234567", "valid mobile via 92 prefix")
    # a 10-digit string starting with 92 is BELOW threshold -> cc NOT stripped
    ten92 = "9234567890"  # len 10 < 11, treated as national-ish, lstrip none
    t.eq(nz(ten92, "92"), "09234567890", "below-threshold 92 prefix not stripped")
    t.check(wa(ten92, "92") is None, "below-threshold 92 not a valid mobile")
