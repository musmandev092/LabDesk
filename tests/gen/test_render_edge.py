"""Generator — render.py edge cases.

Focus: src/labdesk/render.py
  * unit conversions mm() and px() over many values + their algebraic invariants
  * page builders build_receipt / build_report / build_test_page / render_pages
    return real content for valid receipts without raising.

Contract (see tests/gen/test_billing.py):
  * expose exactly one register(t)
  * emit assertions only via t.check / t.eq / t.near / t.has
  * never touch the network or the live DB (runner isolates both)
"""
from __future__ import annotations


def register(t):
    R = t.render
    DPI = 300
    MM_PER_IN = 25.4

    # ====================================================================
    # 1. mm(): millimetres -> device units at 300 dpi.  mm(v) = v/25.4*300
    # ====================================================================
    t.section("mm() unit conversion")
    # exact anchor values
    t.near(R.mm(0.0), 0.0, "mm(0)")
    t.near(R.mm(25.4), 300.0, "mm(25.4)=300 (1 inch)")
    t.near(R.mm(210.0), 210.0 / MM_PER_IN * DPI, "mm(A4 width)")
    t.near(R.mm(297.0), 297.0 / MM_PER_IN * DPI, "mm(A4 height)")

    MM_VALUES = [v / 4.0 for v in range(-40, 1600)]  # -10mm .. ~400mm in 0.25 steps
    for v in MM_VALUES:
        got = R.mm(v)
        want = v / MM_PER_IN * DPI
        t.near(got, want, f"mm({v}) value", tol=1e-6)
        # sign is preserved
        if v > 0:
            t.check(got > 0, f"mm({v})>0")
        elif v < 0:
            t.check(got < 0, f"mm({v})<0")
        else:
            t.near(got, 0.0, "mm(0)==0")
        # linearity / monotonicity: mm is strictly increasing
        t.check(R.mm(v + 1.0) > got, f"mm monotonic at {v}")

    # linearity: mm(a+b) == mm(a)+mm(b), mm(k*v)==k*mm(v)
    t.section("mm() linearity")
    for a in [0.0, 1.0, 7.5, 25.4, 100.0, 210.0]:
        for b in [0.0, 0.5, 3.3, 25.4, 99.0]:
            t.near(R.mm(a + b), R.mm(a) + R.mm(b), f"mm additive a={a} b={b}", tol=1e-6)
        for k in [0, 1, 2, 3, 10, -1, -4]:
            t.near(R.mm(k * a), k * R.mm(a), f"mm scalar k={k} a={a}", tol=1e-6)

    # ====================================================================
    # 2. px(): CSS px@96 -> mm.  px(v) = v/96*25.4
    # ====================================================================
    t.section("px() unit conversion")
    t.near(R.px(0.0), 0.0, "px(0)")
    t.near(R.px(96.0), 25.4, "px(96)=25.4 (1 inch)")
    t.near(R.px(48.0), 12.7, "px(48)=half inch")
    t.near(R.px(1.0), 25.4 / 96.0, "px(1)")

    PX_VALUES = [v / 2.0 for v in range(-20, 1200)]  # -10 .. ~600 px in 0.5 steps
    for v in PX_VALUES:
        got = R.px(v)
        want = v / 96.0 * MM_PER_IN
        t.near(got, want, f"px({v}) value", tol=1e-9)
        if v > 0:
            t.check(got > 0, f"px({v})>0")
        elif v < 0:
            t.check(got < 0, f"px({v})<0")
        t.check(R.px(v + 1.0) > got, f"px monotonic at {v}")

    t.section("px() linearity")
    for a in [0.0, 1.0, 12.0, 96.0, 300.0]:
        for b in [0.0, 0.5, 3.0, 96.0]:
            t.near(R.px(a + b), R.px(a) + R.px(b), f"px additive a={a} b={b}", tol=1e-9)
        for k in [0, 1, 2, 8, -1, -3]:
            t.near(R.px(k * a), k * R.px(a), f"px scalar k={k} a={a}", tol=1e-9)

    # ====================================================================
    # 3. round-trip / cross relations between mm and px
    #    px maps CSS-px to mm; mm maps mm to device-units. So
    #    mm(px(96)) should equal one inch in device units == 300.
    # ====================================================================
    t.section("mm/px composition")
    for v in [0.0, 1.0, 24.0, 48.0, 96.0, 192.0, 300.0, 768.0]:
        # mm(px(v)) = v/96*25.4/25.4*300 = v/96*300 = v*3.125
        t.near(R.mm(R.px(v)), v / 96.0 * DPI, f"mm(px({v}))", tol=1e-6)
        t.near(R.mm(R.px(v)), v * (DPI / 96.0), f"mm(px({v}))=v*3.125", tol=1e-6)
    # 96 css-px == 300 device-units (both one inch)
    t.near(R.mm(R.px(96.0)), 300.0, "one inch round trip")
    # module constants are the expected fixed design values
    t.eq(R.DPI, 300, "DPI constant")
    t.eq(R.A4_W_MM, 210.0, "A4 width mm")
    t.eq(R.A4_H_MM, 297.0, "A4 height mm")

    # ====================================================================
    # 4. Page builders return non-empty PDF bytes for valid receipts and
    #    never raise, across many receipt shapes (boundary/extreme).
    # ====================================================================
    t.section("build_receipt / build_report do not raise + emit content")
    con = t.con

    # build a matrix of receipts spanning boundaries
    SUBS = [0.0, 0.01, 1.0, 999.0, 1000.0, 99999.0, 1234567.0]
    PAIRS = []  # (sub, paid)
    for sub in SUBS:
        PAIRS.append((sub, 0.0))         # nothing paid
        PAIRS.append((sub, sub))         # exact
        PAIRS.append((sub, sub / 2.0))   # underpaid -> due
        PAIRS.append((sub, sub + 500.0))  # overpaid -> change
    PHONES = ["03001234567", "", "12", "+92 300 1234567"]
    SEXES = ["Male", "Female", "Other", ""]

    receipts = []
    for i, (sub, paid) in enumerate(PAIRS):
        phone = PHONES[i % len(PHONES)]
        sex = SEXES[i % len(SEXES)]
        with_results = (i % 2 == 0)
        status = "reported" if with_results else "pending"
        rid = t.make_receipt(phone, sub=sub, paid=paid, with_results=with_results,
                             status=status, sex=sex, age=(i * 7) % 110)
        receipts.append((rid, sub, paid))

    for rid, sub, paid in receipts:
        # build_receipt -> bytes
        raised = False
        out = None
        try:
            out = R.build_receipt(con, rid)
        except Exception as e:  # pragma: no cover - asserted below
            raised = True
            t.check(False, f"build_receipt rid={rid} raised {e!r}")
        if not raised:
            t.check(isinstance(out, (bytes, bytearray)), f"build_receipt rid={rid} -> bytes")
            t.check(out is not None and len(out) > 200, f"build_receipt rid={rid} non-trivial bytes")
            t.has(out[:8].decode("latin-1"), "%PDF", f"build_receipt rid={rid} PDF magic")

        # build_report -> bytes
        raised = False
        out = None
        try:
            out = R.build_report(con, rid)
        except Exception as e:
            raised = True
            t.check(False, f"build_report rid={rid} raised {e!r}")
        if not raised:
            t.check(isinstance(out, (bytes, bytearray)), f"build_report rid={rid} -> bytes")
            t.check(out is not None and len(out) > 200, f"build_report rid={rid} non-trivial bytes")
            t.has(out[:8].decode("latin-1"), "%PDF", f"build_report rid={rid} PDF magic")

    # ====================================================================
    # 5. render_pages: image-mode preview returns a non-empty list of pages,
    #    each an A4 QImage at 300 dpi.
    # ====================================================================
    t.section("render_pages image preview")
    A4_W_PX = int(R.mm(R.A4_W_MM))
    A4_H_PX = int(R.mm(R.A4_H_MM))
    for rid, sub, paid in receipts[:12]:
        for kind in ("receipt", "report"):
            raised = False
            pages = None
            try:
                pages = R.render_pages(con, rid, kind)
            except Exception as e:
                raised = True
                t.check(False, f"render_pages {kind} rid={rid} raised {e!r}")
            if not raised:
                t.check(isinstance(pages, list), f"render_pages {kind} rid={rid} list")
                t.check(len(pages) >= 1, f"render_pages {kind} rid={rid} >=1 page")
                for img in pages:
                    t.eq(img.width(), A4_W_PX, f"render_pages {kind} rid={rid} page width")
                    t.eq(img.height(), A4_H_PX, f"render_pages {kind} rid={rid} page height")
                    t.check(not img.isNull(), f"render_pages {kind} rid={rid} image not null")

    # unknown kind falls through to report (per render_pages source) — must not raise
    raised = False
    try:
        pages = R.render_pages(con, receipts[0][0], "totally-unknown-kind")
        t.check(isinstance(pages, list) and len(pages) >= 1,
                "render_pages unknown kind -> report list")
    except Exception as e:
        t.check(False, f"render_pages unknown kind raised {e!r}")

    # ====================================================================
    # 6. build_test_page: printer test page, with and without a name.
    # ====================================================================
    t.section("build_test_page")
    for name in ["", "Some Printer", "HP LaserJet ✓", "x" * 200]:
        raised = False
        out = None
        try:
            out = R.build_test_page(name)
        except Exception as e:
            raised = True
            t.check(False, f"build_test_page name={name!r} raised {e!r}")
        if not raised:
            t.check(isinstance(out, (bytes, bytearray)), f"build_test_page name={name!r} bytes")
            t.check(len(out) > 200, f"build_test_page name={name!r} non-trivial")
            t.has(out[:8].decode("latin-1"), "%PDF", f"build_test_page name={name!r} PDF magic")

    # ====================================================================
    # 7. A receipt with NO items / no results still renders (build_report
    #    has an explicit "No tests on this receipt." path).
    # ====================================================================
    t.section("empty receipt renders")
    empty_rid = con.execute(
        """INSERT INTO receipts(lab_no,patient_id,patient_name,age,age_desc,sex,telephone,
                                dr_name,specimen,subtotal,net_amount,paid,due,status,mr_no)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("LAB_RENDEREDGE_EMPTY", None, "Empty Patient", 0, "Years", "Male", "",
         "Dr. None", "", 0.0, 0.0, 0.0, 0.0, "pending", None),
    ).lastrowid
    con.commit()
    raised = False
    try:
        out = R.build_report(con, empty_rid)
        t.check(isinstance(out, (bytes, bytearray)) and len(out) > 200,
                "build_report empty receipt -> bytes")
        t.has(out[:8].decode("latin-1"), "%PDF", "build_report empty receipt PDF magic")
    except Exception as e:
        t.check(False, f"build_report empty receipt raised {e!r}")
    raised = False
    try:
        out = R.build_receipt(con, empty_rid)
        t.check(isinstance(out, (bytes, bytearray)) and len(out) > 200,
                "build_receipt empty receipt -> bytes")
    except Exception as e:
        t.check(False, f"build_receipt empty receipt raised {e!r}")
