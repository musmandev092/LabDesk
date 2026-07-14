"""Report page-packing (paper-saving): multiple tests share a page when they fit.

``build_report(images=True)`` returns one QImage per page, so ``len(pages)`` is the
page count — the assertions below check packing vs. the one-test-per-page option, plus
the pagination of oversized blocks (a long test / a big culture antibiotic panel).
"""

from __future__ import annotations

from factories import make_culture, make_item, make_receipt, make_sensitivity

from labdesk.render import report_doc


def _pages(con, rid, **kw):
    imgs = report_doc.build_report(con, rid, images=True, **kw)
    assert isinstance(imgs, list)
    return len(imgs)


def _add_small_qual(con, rid, n):
    """Add n single-line serology items (Typhidot IgG, seq0 = one 'Negative' row)."""
    for _ in range(n):
        iid = make_item(con, rid, test_id=597, test_name="Typhidot IgG")
        con.execute(
            "INSERT INTO results(receipt_item_id,parameter_id,seq,part_type,name,"
            "units,ref_text,value) VALUES (?,?,?,?,?,?,?,?)",
            (iid, None, 0, "N", "Typhidot IgG", "", "Negative", "Negative"),
        )
    con.commit()


def _add_numeric(con, rid, nrows, *, test_name="Panel"):
    """Add one numeric test with nrows result rows (forces a tall block when large)."""
    iid = make_item(con, rid, test_name=test_name)
    for i in range(nrows):
        con.execute(
            "INSERT INTO results(receipt_item_id,parameter_id,seq,part_type,name,"
            "units,ref_text,value) VALUES (?,?,?,?,?,?,?,?)",
            (iid, None, i, "N", f"Analyte {i}", "mg/dL", "1 - 10", "5"),
        )
    con.commit()
    return iid


def _add_culture(con, rid, n_antibiotics, *, growth="Growth of E. coli"):
    iid = make_item(con, rid, test_name="Urine Culture & Sensitivity")
    # route through the culture renderer
    con.execute("UPDATE tests SET is_culture=1 WHERE id=?", (_item_test(con, iid),))
    cid = make_culture(con, iid, specimen="Urine", growth=growth, organism="E. coli")
    abx = [
        "Amikacin",
        "Ceftriaxone",
        "Ciprofloxacin",
        "Meropenem",
        "Nitrofurantoin",
        "Gentamicin",
        "Cefixime",
        "Augmentin",
        "Piptaz",
        "Fosfomycin",
        "Levofloxacin",
        "Tazocin",
        "Colistin",
        "Tigecycline",
        "Doxycycline",
    ]
    for i in range(n_antibiotics):
        make_sensitivity(con, cid, antibiotic=abx[i % len(abx)], result="SIR"[i % 3])
    con.commit()
    return iid


def _item_test(con, iid):
    return con.execute(
        "SELECT test_id FROM receipt_items WHERE id=?", (iid,)
    ).fetchone()[0]


# ── packing basics ──────────────────────────────────────────────────────────


def test_many_small_tests_pack_onto_one_page(con):
    rid = make_receipt(con, status="reported")
    _add_small_qual(con, rid, 6)
    assert _pages(con, rid, pack=True) == 1


def test_one_per_page_option_gives_one_page_each(con):
    rid = make_receipt(con, status="reported")
    _add_small_qual(con, rid, 4)
    assert _pages(con, rid, pack=False) == 4


def test_packing_uses_fewer_pages_than_solo(con):
    rid = make_receipt(con, status="reported")
    _add_small_qual(con, rid, 5)
    assert _pages(con, rid, pack=True) < _pages(con, rid, pack=False)


def test_single_test_is_one_page_either_way(con):
    rid = make_receipt(con, status="reported")
    _add_small_qual(con, rid, 1)
    assert _pages(con, rid, pack=True) == 1
    assert _pages(con, rid, pack=False) == 1


def test_no_tests_still_one_page(con):
    rid = make_receipt(con, status="reported")
    assert _pages(con, rid, pack=True) == 1


# ── overflow / big blocks ───────────────────────────────────────────────────


def test_many_tests_flow_to_multiple_pages(con):
    rid = make_receipt(con, status="reported")
    _add_small_qual(con, rid, 40)
    n = _pages(con, rid, pack=True)
    assert 1 < n < 40  # packed across a few pages, nowhere near one-per-page


def test_tall_test_spills_across_pages_then_packing_resumes(con):
    rid = make_receipt(con, status="reported")
    _add_numeric(con, rid, 80, test_name="Huge Panel")  # taller than one page
    _add_small_qual(con, rid, 1)
    # the tall panel alone needs >1 page; the whole report must still render cleanly
    assert _pages(con, rid, pack=True) >= 2


def test_tall_table_with_remarks_does_not_overflow_footer(con):
    # a table that spills to the bottom of its last page PLUS a remarks block must
    # push the remarks onto a fresh page, not paint them over the footer (Finding 2).
    rid = make_receipt(con, status="reported")
    iid = _add_numeric(con, rid, 70, test_name="Spilling Panel")
    con.execute(
        "UPDATE receipt_items SET remarks=? WHERE id=?",
        ("Sample slightly haemolysed; correlate clinically. " * 4, iid),
    )
    con.commit()
    # must render across pages without raising; footer/remarks stay off each other
    assert _pages(con, rid, pack=True) >= 2


def test_mixed_categories_pack_together(con):
    rid = make_receipt(con, status="reported")
    _add_small_qual(con, rid, 2)  # serology
    _add_numeric(con, rid, 3, test_name="Mini Panel")  # numeric
    _add_culture(con, rid, 3, growth="No growth")  # small culture
    # a couple of small tests of different kinds comfortably share one page
    assert _pages(con, rid, pack=True) == 1


# ── culture pagination ──────────────────────────────────────────────────────


def test_small_culture_packs_with_serology(con):
    rid = make_receipt(con, status="reported")
    _add_culture(con, rid, 4)
    _add_small_qual(con, rid, 1)
    assert _pages(con, rid, pack=True) == 1


def test_large_antibiotic_panel_paginates_not_overflows(con):
    rid = make_receipt(con, status="reported")
    # a full antibiotic panel is taller than one page — it must span pages, not clip
    _add_culture(con, rid, 45)
    n = _pages(con, rid, pack=True)
    assert n >= 2


def test_no_growth_culture_is_one_page(con):
    rid = make_receipt(con, status="reported")
    iid = make_item(con, rid, test_name="Blood Culture")
    con.execute("UPDATE tests SET is_culture=1 WHERE id=?", (_item_test(con, iid),))
    make_culture(con, iid, specimen="Blood", growth="No growth after 48 hrs")
    con.commit()
    assert _pages(con, rid, pack=True) == 1


# ── oversized narrative (histopathology / biopsy free text) ────────────────


def _add_huge_narrative(con, rid):
    """Add a descriptive (histopathology) test whose single parameter-less
    narrative paragraph is far taller than one page."""
    iid = make_item(con, rid, test_name="Biopsy Large Specimen")
    con.execute(
        "UPDATE tests SET report_head='HISTOPATHOLOGY REPORT' WHERE id=?",
        (_item_test(con, iid),),
    )
    text = (
        "The specimen consists of multiple grey-white soft tissue fragments "
        "aggregating to 3 x 2 cm, showing features of chronic inflammation. "
    ) * 400
    con.execute(
        "INSERT INTO results(receipt_item_id,parameter_id,seq,part_type,name,"
        "units,ref_text,value) VALUES (?,?,?,?,?,?,?,?)",
        (iid, None, 0, "N", "", "", "", text),
    )
    con.commit()
    return iid


def test_huge_narrative_paragraph_splits_across_pages(con):
    # a single narrative row taller than a page must be split at word boundaries
    # and continue on following pages — not run off the bottom losing text.
    rid = make_receipt(con, status="reported")
    _add_huge_narrative(con, rid)
    n = _pages(con, rid, pack=True)
    assert n >= 2


def test_huge_narrative_packs_with_other_tests(con):
    # the spilled narrative must not derail pagination of the tests around it
    rid = make_receipt(con, status="reported")
    _add_small_qual(con, rid, 1)
    _add_huge_narrative(con, rid)
    _add_small_qual(con, rid, 1)
    assert _pages(con, rid, pack=True) >= 2


# ── two-pass page count (footer "Page X of Y") stays consistent ─────────────


def test_page_count_stable_across_successive_builds(con):
    # count pass + real pass must agree: two successive renders of a report
    # that spills to multiple pages give the identical page count.
    rid = make_receipt(con, status="reported")
    _add_numeric(con, rid, 80, test_name="Huge Panel")
    _add_small_qual(con, rid, 3)
    p1 = _pages(con, rid, pack=True)
    p2 = _pages(con, rid, pack=True)
    assert p1 == p2
    assert p1 >= 2


# ── method-note / after-block accounting (overlap regression) ───────────────


def test_method_note_counted_in_block_height(con):
    """Regression: a test's 'Method / Comments' note must be included in the measured
    block height, otherwise the next packed test draws its title bar over the note."""
    rid = make_receipt(con, status="reported")
    note = "Performed by an immunochromatographic method with high sensitivity. " * 4
    tid = con.execute(
        "INSERT INTO tests(name,charges,category,report_head,method_note,is_culture) "
        "VALUES ('HBsAg X',1,'Special','SCREENING REPORT',?,0)",
        (note,),
    ).lastrowid
    iid = make_item(con, rid, test_id=tid, test_name="HBsAg X")
    con.execute(
        "INSERT INTO results(receipt_item_id,parameter_id,seq,part_type,name,units,"
        "ref_text,value) VALUES (?,?,?,?,?,?,?,?)",
        (iid, None, 0, "N", "HBsAg X", "", "Non-Reactive", "Non-Reactive"),
    )
    con.commit()
    r = con.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone()
    items = con.execute(
        "SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY id", (rid,)
    ).fetchall()
    import contextlib

    from labdesk.render.primitives import Doc

    d = Doc(margin_mm=(8, 8, 8, 8))
    try:
        blocks = report_doc._measure_blocks(d, con, items, "M", r)
        after_h = blocks[0][4]
    finally:
        with contextlib.suppress(Exception):
            d.tobytes()  # finalise the measuring Doc's painter (else Qt aborts on GC)
    # a multi-line method note is ~3 lines tall — after-blocks height must reflect it
    assert after_h > 8, f"method note not counted in block height (after_h={after_h})"


def test_preview_half_scale_matches_full_page_count(con):
    """On-screen preview rasterises at reduced resolution (faster) but must produce the
    SAME layout/pagination as the full-resolution render."""
    from labdesk.render import preview

    rid = make_receipt(con, status="reported")
    _add_small_qual(con, rid, 8)
    full = report_doc.build_report(con, rid, images=True)
    prev = preview.render_pages(con, rid, "report")
    assert isinstance(full, list) and isinstance(prev, list)
    assert len(prev) == len(full)  # same pagination
    assert prev[0].width() < full[0].width()  # smaller pixel buffer


# ── letterfree (pre-printed pad) copy also packs ────────────────────────────


def test_letterfree_copy_packs(con):
    rid = make_receipt(con, status="reported")
    _add_small_qual(con, rid, 6)
    imgs = report_doc.build_report(con, rid, images=True, letterhead=False, pack=True)
    assert isinstance(imgs, list)
    assert len(imgs) == 1


def test_letterfree_one_per_page_option(con):
    rid = make_receipt(con, status="reported")
    _add_small_qual(con, rid, 3)
    imgs = report_doc.build_report(con, rid, images=True, letterhead=False, pack=False)
    assert isinstance(imgs, list)
    assert len(imgs) == 3


def _first_content_row(img):
    """Top-most pixel row that isn't white (where drawing begins)."""
    w, h = img.width(), img.height()
    for y in range(0, h, 3):
        for x in range(0, w, 11):
            if img.pixelColor(x, y).value() < 245:
                return y / h  # fraction down the page
    return 1.0


def test_letterfree_content_anchored_below_letterhead(con):
    """The 'print without header' copy starts content at a fixed top offset (clear of
    the pre-printed letterhead) and top-aligns — NOT floating in the page centre — so a
    short and a long report begin at the SAME position."""
    short = make_receipt(con, status="reported")
    _add_small_qual(con, short, 1)  # tiny report
    long = make_receipt(con, status="reported", lab_no="LAB-9")
    _add_small_qual(con, long, 6)  # taller report
    s = report_doc.build_report(con, short, images=True, letterhead=False)
    ln = report_doc.build_report(con, long, images=True, letterhead=False)
    assert len(s) == 1 and len(ln) == 1
    fs, fl = _first_content_row(s[0]), _first_content_row(ln[0])
    assert 0.08 < fs < 0.22  # anchored below the letterhead band, not centred/floating
    assert abs(fs - fl) < 0.03  # short and long start at the same top offset
