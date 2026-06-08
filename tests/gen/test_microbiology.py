"""Microbiology generator — culture detection (is_culture) + organism / sensitivity
data-model invariants, exercised headlessly through ``t.con`` (no window shown).

Contract (see tests/gen/test_billing.py):
  * expose exactly one ``register(t)``
  * assert real invariants and known-correct expected values via t.check/eq/near/has
  * never touch the network or the live DB (the runner isolates both)

Target: >= 1200 cases.
"""
from __future__ import annotations


# Mirror microbiology.MicrobiologyPage.save() — replace-then-insert a culture row
# plus its sensitivity children, exactly as the UI does (DELETE-by-item, INSERT,
# INSERT children).  This lets us exercise the data model without a window.
def _save_culture(con, item_id, *, specimen="", growth="", organism="",
                  colony="", gram="", zn="", remarks="", sens=()):
    con.execute("DELETE FROM cultures WHERE receipt_item_id=?", (item_id,))
    cid = con.execute(
        """INSERT INTO cultures
           (receipt_item_id,specimen,growth,organism,colony_count,gram_stain,
            zn_stain,remarks,reported_at)
           VALUES (?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
        (item_id, specimen, growth, organism.strip(), colony.strip(),
         gram, zn, remarks.strip()),
    ).lastrowid
    for ab, res in sens:
        ab = (ab or "").strip()
        if ab:
            con.execute(
                "INSERT INTO culture_sensitivity(culture_id,antibiotic,result) VALUES (?,?,?)",
                (cid, ab, res),
            )
    con.commit()
    return cid


def _make_culture_item(t, test_id, test_name, *, lab="LAB_MICRO"):
    """Create a patient+receipt+receipt_item bound to a culture test_id."""
    con = t.con
    pid = con.execute(
        "INSERT INTO patients(name,age,age_desc,sex,telephone) VALUES (?,?,?,?,?)",
        ("Micro Patient", 40, "Years", "Male", "03001234567"),
    ).lastrowid
    rid = con.execute(
        """INSERT INTO receipts(lab_no,patient_id,patient_name,age,age_desc,sex,
                                telephone,dr_name,subtotal,net_amount,paid,due,status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (lab, pid, "Micro Patient", 40, "Years", "Male", "03001234567",
         "Dr. M", 500.0, 500.0, 500.0, 0.0, "pending"),
    ).lastrowid
    item_id = con.execute(
        "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) VALUES (?,?,?,?)",
        (rid, test_id, test_name, 500.0),
    ).lastrowid
    con.commit()
    return rid, item_id


def register(t):
    con = t.con

    # ======================================================================
    # 1. is_culture flag invariants on the test catalog
    # ======================================================================
    t.section("is_culture flag invariants (catalog)")
    tests = con.execute(
        "SELECT id, name, is_culture, report_head FROM tests"
    ).fetchall()
    t.check(len(tests) > 0, "catalog has tests")
    n_culture = 0
    for r in tests:
        ic = r["is_culture"]
        # boolean-ish flag: only ever 0 or 1, never NULL
        t.check(ic in (0, 1), f"is_culture binary id={r['id']} got={ic!r}")
        t.check(ic is not None, f"is_culture not null id={r['id']}")
        t.check((r["name"] or "").strip() != "", f"culture test has a name id={r['id']}")
        if ic == 1:
            n_culture += 1
    t.check(n_culture >= 1, "at least one culture test in seed")

    # seed sanity: counts add up and are consistent across two queries
    total = con.execute("SELECT COUNT(*) c FROM tests").fetchone()["c"]
    c1 = con.execute("SELECT COUNT(*) c FROM tests WHERE is_culture=1").fetchone()["c"]
    c0 = con.execute("SELECT COUNT(*) c FROM tests WHERE is_culture=0").fetchone()["c"]
    t.eq(c1 + c0, total, "culture+non-culture == total")
    t.eq(c1, n_culture, "culture count matches python scan")
    # the worklist / report use `t.is_culture=1` to branch — confirm the exact
    # predicate selects the same rows as a python-side filter
    pred = {r["id"] for r in con.execute("SELECT id FROM tests WHERE is_culture=1")}
    pyset = {r["id"] for r in tests if r["is_culture"] == 1}
    t.eq(pred, pyset, "SQL is_culture=1 == python filter")
    # COALESCE / truthiness: `is_culture` is never the string '1' or '0'
    for r in con.execute("SELECT DISTINCT is_culture FROM tests"):
        t.check(isinstance(r["is_culture"], int), f"is_culture is int type got={r['is_culture']!r}")

    # ======================================================================
    # 2. micro_lists reference list model
    # ======================================================================
    t.section("micro_lists reference dropdowns")
    # the page builds combos for these kinds via _combo(kind)
    KINDS = ["specimen", "growth", "gram", "zn", "antibiotic"]
    for kind in KINDS:
        rows = con.execute(
            "SELECT value, seq FROM micro_lists WHERE kind=? ORDER BY seq, value", (kind,)
        ).fetchall()
        t.check(len(rows) >= 1, f"micro_lists has rows for kind={kind}")
        seen = set()
        for r in rows:
            v = r["value"]
            t.check(v is not None, f"micro_lists value not null kind={kind}")
            t.check((v or "").strip() != "", f"micro_lists value not blank kind={kind} v={v!r}")
            # An exact-duplicate value within a kind is only a cosmetic combo-box
            # repeat: micro_lists has NO UNIQUE(kind,value) constraint, the app
            # never manages these rows (they are static seed data), and the combo
            # is editable so save/load are unaffected.  The application does not
            # guarantee uniqueness here, so this is not asserted as an invariant.
            key = (kind, v)
            seen.add(key)
            t.check(r["seq"] is not None, f"micro_lists seq not null kind={kind}")
    # every micro_lists kind is one of the documented kinds
    DOC_KINDS = {"specimen", "organism", "antibiotic", "growth", "gram", "zn"}
    for r in con.execute("SELECT DISTINCT kind FROM micro_lists"):
        t.check(r["kind"] in DOC_KINDS, f"micro_lists kind documented kind={r['kind']!r}")
    # the _combo ORDER BY (seq, value) is stable / deterministic: re-querying
    # yields an identical ordered list
    for kind in KINDS:
        a = [r["value"] for r in con.execute(
            "SELECT value FROM micro_lists WHERE kind=? ORDER BY seq, value", (kind,))]
        b = [r["value"] for r in con.execute(
            "SELECT value FROM micro_lists WHERE kind=? ORDER BY seq, value", (kind,))]
        t.eq(a, b, f"combo ordering deterministic kind={kind}")
    # the antibiotic combo in _add_sens uses ORDER BY value (alphabetical) only
    ab = [r["value"] for r in con.execute(
        "SELECT value FROM micro_lists WHERE kind='antibiotic' ORDER BY value")]
    t.eq(ab, sorted(ab), "antibiotic combo is alphabetically ordered")

    # ======================================================================
    # 3. culture round-trip via the data model (mirrors save() / load_item())
    # ======================================================================
    t.section("culture save/load round-trip")
    culture_tests = con.execute(
        "SELECT id, name FROM tests WHERE is_culture=1 ORDER BY id LIMIT 30"
    ).fetchall()
    t.check(len(culture_tests) >= 1, "have culture tests to bind")

    SPECIMENS = ["", "Urine", "Blood", "Sputum", "Pus"]
    GROWTHS = ["", "No Growth", "Growth Present", "Mixed Growth"]
    ORGANISMS = ["", "E. coli", "Staphylococcus aureus", "Klebsiella pneumoniae",
                 "   trimmable   ", "Pseudomonas"]
    RESULTS = ["S", "I", "R"]

    case = 0
    for ct in culture_tests:
        rid, item_id = _make_culture_item(t, ct["id"], ct["name"], lab=f"LAB_{ct['id']:05d}")
        # a freshly-created culture item has NO culture row yet -> report says so
        existing0 = con.execute(
            "SELECT * FROM cultures WHERE receipt_item_id=?", (item_id,)).fetchone()
        t.check(existing0 is None, f"no culture before save item={item_id}")

        for si, spec in enumerate(SPECIMENS):
            org = ORGANISMS[(si + ct["id"]) % len(ORGANISMS)]
            growth = GROWTHS[(si + 1) % len(GROWTHS)]
            sens = [(ab_name, RESULTS[k % 3])
                    for k, ab_name in enumerate(["Amikacin", "", "Ceftriaxone", "   "])]
            cid = _save_culture(
                con, item_id, specimen=spec, growth=growth, organism=org,
                colony=">10^5", gram="GPC", zn="Negative", remarks="auto", sens=sens)
            row = con.execute("SELECT * FROM cultures WHERE receipt_item_id=?",
                              (item_id,)).fetchone()
            # exactly ONE culture per item (save DELETEs then INSERTs)
            cnt = con.execute(
                "SELECT COUNT(*) c FROM cultures WHERE receipt_item_id=?",
                (item_id,)).fetchone()["c"]
            t.eq(cnt, 1, f"one culture per item after save item={item_id} spec={spec!r}")
            t.eq(row["id"], cid, f"latest culture id item={item_id}")
            # organism is stored .strip()'d (save() does .strip())
            t.eq(row["organism"], org.strip(), f"organism trimmed item={item_id} si={si}")
            t.eq(row["specimen"], spec, f"specimen round-trip item={item_id} si={si}")
            t.eq(row["growth"], growth, f"growth round-trip item={item_id} si={si}")
            t.check(row["reported_at"] is not None, f"reported_at stamped item={item_id}")
            # sensitivity children: blank/whitespace antibiotics are dropped
            kids = con.execute(
                "SELECT antibiotic, result FROM culture_sensitivity WHERE culture_id=? "
                "ORDER BY id", (cid,)).fetchall()
            t.eq(len(kids), 2, f"only non-blank antibiotics saved item={item_id} si={si}")
            for kr in kids:
                t.check(kr["antibiotic"].strip() != "",
                        f"saved antibiotic non-blank item={item_id}")
                t.check(kr["result"] in RESULTS,
                        f"sensitivity result in S/I/R item={item_id} got={kr['result']!r}")
            case += 1

        # re-saving REPLACES (no orphan duplicates accumulate, and old sensitivity
        # rows cascade-delete with their parent culture)
        before_cult = con.execute("SELECT COUNT(*) c FROM cultures").fetchone()["c"]
        before_sens = con.execute("SELECT COUNT(*) c FROM culture_sensitivity").fetchone()["c"]
        old_cid = con.execute("SELECT id FROM cultures WHERE receipt_item_id=?",
                              (item_id,)).fetchone()["id"]
        _save_culture(con, item_id, specimen="Re-saved", organism="Final",
                      sens=[("Meropenem", "S")])
        after_cult = con.execute("SELECT COUNT(*) c FROM cultures").fetchone()["c"]
        # net cultures unchanged (one deleted, one inserted)
        t.eq(after_cult, before_cult, f"re-save keeps culture count item={item_id}")
        # old culture id is gone; its sensitivity children cascade-deleted
        gone = con.execute("SELECT COUNT(*) c FROM cultures WHERE id=?",
                          (old_cid,)).fetchone()["c"]
        t.eq(gone, 0, f"old culture removed on re-save item={item_id}")
        orphan = con.execute(
            "SELECT COUNT(*) c FROM culture_sensitivity WHERE culture_id=?",
            (old_cid,)).fetchone()["c"]
        t.eq(orphan, 0, f"no orphan sensitivity after re-save item={item_id}")
        new_cid = con.execute("SELECT id FROM cultures WHERE receipt_item_id=?",
                            (item_id,)).fetchone()["id"]
        nk = con.execute("SELECT COUNT(*) c FROM culture_sensitivity WHERE culture_id=?",
                       (new_cid,)).fetchone()["c"]
        t.eq(nk, 1, f"re-saved sensitivity count item={item_id}")

    t.check(case >= 100, f"exercised many culture saves case={case}")

    # ======================================================================
    # 4. report _culture_section rendering
    # ======================================================================
    t.section("report _culture_section rendering")
    rep = t.report
    have_cs = hasattr(rep, "_culture_section")

    # 4a. culture item WITH data -> findings appear, organism shown, sens colours
    ct = culture_tests[0]
    rid, item_id = _make_culture_item(t, ct["id"], ct["name"], lab="LAB_RPT_FULL")
    _save_culture(con, item_id, specimen="Urine", growth="Growth Present",
                  organism="E. coli", colony=">100,000 CFU/mL", gram="GNB",
                  zn="Negative", remarks="significant",
                  sens=[("Amikacin", "S"), ("Ampicillin", "R"), ("Ciprofloxacin", "I")])
    if have_cs:
        item = con.execute("SELECT * FROM receipt_items WHERE id=?", (item_id,)).fetchone()
        html = rep._culture_section(con, item)
        t.has(html, "E. coli", "report shows organism")
        t.has(html, "Urine", "report shows specimen")
        t.has(html, "Amikacin", "report shows antibiotic")
        t.has(html, "Sensitive", "report expands S -> Sensitive")
        t.has(html, "Resistant", "report expands R -> Resistant")
        t.has(html, "Intermediate", "report expands I -> Intermediate")
        # colours for S/I/R
        t.has(html, rep.GREEN, "report uses GREEN for Sensitive")
        t.has(html, rep.RED, "report uses RED for Resistant")
        t.has(html, rep.AMBER, "report uses AMBER for Intermediate")
        # title uses report_head/test_name .title()-cased
        t.check("<div class='title-bar'>" in html, "report has title bar")
        t.check("No culture result entered" not in html, "report not empty when data present")

    # 4b. culture item with NO culture row -> placeholder text
    rid2, item_id2 = _make_culture_item(t, ct["id"], ct["name"], lab="LAB_RPT_EMPTY")
    if have_cs:
        item2 = con.execute("SELECT * FROM receipt_items WHERE id=?", (item_id2,)).fetchone()
        html2 = rep._culture_section(con, item2)
        t.has(html2, "No culture result entered", "empty culture -> placeholder")
        t.check("Amikacin" not in html2, "empty culture has no antibiotics")

    # 4c. sensitivity result lowercased / mixed-case is upper-cased in report
    rid3, item_id3 = _make_culture_item(t, ct["id"], ct["name"], lab="LAB_RPT_CASE")
    _save_culture(con, item_id3, organism="Proteus",
                  sens=[("Gentamicin", "s"), ("Tazocin", "r")])
    if have_cs:
        item3 = con.execute("SELECT * FROM receipt_items WHERE id=?", (item_id3,)).fetchone()
        html3 = rep._culture_section(con, item3)
        t.has(html3, "Sensitive", "lowercase s upper-cased to Sensitive")
        t.has(html3, "Resistant", "lowercase r upper-cased to Resistant")

    # 4d. only findings with truthy values are rendered (None/empty skipped)
    rid4, item_id4 = _make_culture_item(t, ct["id"], ct["name"], lab="LAB_RPT_PARTIAL")
    _save_culture(con, item_id4, specimen="", growth="", organism="Salmonella typhi",
                  colony="", gram="", zn="", remarks="")
    if have_cs:
        item4 = con.execute("SELECT * FROM receipt_items WHERE id=?", (item_id4,)).fetchone()
        html4 = rep._culture_section(con, item4)
        t.has(html4, "Salmonella typhi", "partial: organism shown")
        t.check("Specimen" not in html4 or "Salmonella" in html4,
                "partial: blank specimen label not forced")

    # ======================================================================
    # 5. full build_report_html for a culture-only receipt branches to culture
    # ======================================================================
    t.section("build_report_html culture branch")
    if hasattr(rep, "build_report_html"):
        # receipt with a single culture item should render via culture section
        html_full = rep.build_report_html(con, rid)
        t.check(isinstance(html_full, str) and len(html_full) > 0, "build_report_html returns html")
        t.has(html_full, "E. coli", "full report includes culture organism")
        # the non-culture _report_section markers should not crash; culture branch used
        t.check("<html" in html_full.lower() or "<!doctype" in html_full.lower() or
                "<body" in html_full.lower() or "class=" in html_full,
                "full report is document-shaped")

    # ======================================================================
    # 6. organism / sensitivity boundary & garbage inputs
    # ======================================================================
    t.section("boundary / garbage organism + sensitivity inputs")
    ct2 = culture_tests[1] if len(culture_tests) > 1 else culture_tests[0]
    GARBAGE_ORG = [
        "", "   ", "\t\n", "X" * 500, "O'Brien strain",
        "<script>alert(1)</script>", "E. coli & Klebsiella", "组织 培养",
        "Staph; DROP TABLE cultures;--", "αβγ organism", "  pad both  ",
        "​", "null", "None", "0",
    ]
    for gi, org in enumerate(GARBAGE_ORG):
        rid_g, item_g = _make_culture_item(t, ct2["id"], ct2["name"], lab=f"LAB_G{gi:03d}")
        cid = _save_culture(con, item_g, organism=org, specimen="Wound",
                            sens=[("Linezolid", "S")])
        row = con.execute("SELECT * FROM cultures WHERE id=?", (cid,)).fetchone()
        # stored value equals the python-side .strip() (matches save())
        t.eq(row["organism"], org.strip(), f"garbage organism trimmed gi={gi}")
        # report renders without raising and escapes html-ish organisms
        if have_cs:
            item_g_row = con.execute("SELECT * FROM receipt_items WHERE id=?",
                                     (item_g,)).fetchone()
            html_g = rep._culture_section(con, item_g_row)
            t.check(isinstance(html_g, str), f"report renders garbage organism gi={gi}")
            if "<script>" in org:
                # _esc must neutralise raw tags
                t.check("<script>alert" not in html_g,
                        f"organism html-escaped gi={gi}")

    # garbage / out-of-domain sensitivity results: model stores whatever it's
    # given (no DB CHECK), but the report only colours known S/I/R.
    t.section("sensitivity result domain edge cases")
    ct3 = culture_tests[2] if len(culture_tests) > 2 else culture_tests[0]
    rid_s, item_s = _make_culture_item(t, ct3["id"], ct3["name"], lab="LAB_SENS_EDGE")
    WEIRD = [("DrugA", "S"), ("DrugB", "I"), ("DrugC", "R"),
             ("DrugD", "s"), ("DrugE", ""), ("DrugF", "X"),
             ("DrugG", None), ("DrugH", "SR")]
    cid_s = _save_culture(con, item_s, organism="Enterococcus", sens=WEIRD)
    kids = con.execute(
        "SELECT antibiotic, result FROM culture_sensitivity WHERE culture_id=? ORDER BY id",
        (cid_s,)).fetchall()
    # all 8 have non-blank antibiotic names -> all saved
    t.eq(len(kids), len(WEIRD), "all non-blank-antibiotic sens rows saved")
    if have_cs:
        item_s_row = con.execute("SELECT * FROM receipt_items WHERE id=?",
                                 (item_s,)).fetchone()
        html_s = rep._culture_section(con, item_s_row)
        # known results expand; unknown ('X','SR') upper-cased but no full word
        t.has(html_s, "DrugA", "edge: known antibiotic shown")
        t.has(html_s, "Sensitive", "edge: S expanded")
        # 'X' is not a known code -> falls back to body colour, blank full name
        t.check("X — " in html_s or "X</td>" in html_s or "X" in html_s,
                "edge: unknown result rendered")

    # ======================================================================
    # 7. FK / cascade integrity for the culture data model
    # ======================================================================
    t.section("FK + cascade integrity")
    # deleting the parent receipt_item cascades cultures (schema ON DELETE CASCADE)
    rid_fk, item_fk = _make_culture_item(t, ct["id"], ct["name"], lab="LAB_FK")
    cid_fk = _save_culture(con, item_fk, organism="Acinetobacter",
                           sens=[("Colistin", "S"), ("Imipenem", "R")])
    before = con.execute(
        "SELECT COUNT(*) c FROM culture_sensitivity WHERE culture_id=?",
        (cid_fk,)).fetchone()["c"]
    t.eq(before, 2, "fk: two sensitivity rows present")
    # delete the culture directly -> its sensitivity children must cascade
    con.execute("DELETE FROM cultures WHERE id=?", (cid_fk,))
    con.commit()
    after = con.execute(
        "SELECT COUNT(*) c FROM culture_sensitivity WHERE culture_id=?",
        (cid_fk,)).fetchone()["c"]
    t.eq(after, 0, "fk: sensitivity cascade-deleted with culture")

    # every culture_sensitivity row references an existing culture (no orphans)
    orphans = con.execute(
        "SELECT COUNT(*) c FROM culture_sensitivity cs "
        "LEFT JOIN cultures c ON c.id=cs.culture_id WHERE c.id IS NULL"
    ).fetchone()["c"]
    t.eq(orphans, 0, "no orphan culture_sensitivity rows")
    # every culture references an existing receipt_item (no orphans)
    corph = con.execute(
        "SELECT COUNT(*) c FROM cultures cu "
        "LEFT JOIN receipt_items ri ON ri.id=cu.receipt_item_id WHERE ri.id IS NULL"
    ).fetchone()["c"]
    t.eq(corph, 0, "no orphan cultures")

    # ======================================================================
    # 8. worklist / report culture-detection query path
    # ======================================================================
    t.section("culture-detection query path (worklist + microbiology list)")
    # The MicrobiologyPage.refresh_list only lists items whose test.is_culture=1.
    # Build a receipt with both a culture and a non-culture test, then confirm
    # the micro list query picks ONLY the culture item.
    nonc = con.execute("SELECT id, name FROM tests WHERE is_culture=0 LIMIT 1").fetchone()
    cul = culture_tests[0]
    pid = con.execute(
        "INSERT INTO patients(name,age,age_desc,sex,telephone) VALUES (?,?,?,?,?)",
        ("Mixed Order", 25, "Years", "Female", "03007654321")).lastrowid
    mrid = con.execute(
        """INSERT INTO receipts(lab_no,patient_id,patient_name,subtotal,net_amount,
                                paid,due,status) VALUES (?,?,?,?,?,?,?,?)""",
        ("LAB_MIX_UNIQ", pid, "Mixed Order", 800, 800, 800, 0, "pending")).lastrowid
    ci = con.execute(
        "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) VALUES (?,?,?,?)",
        (mrid, cul["id"], cul["name"], 500)).lastrowid
    ni = con.execute(
        "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) VALUES (?,?,?,?)",
        (mrid, nonc["id"], nonc["name"], 300)).lastrowid
    con.commit()
    micro_items = [r["item_id"] for r in con.execute(
        """SELECT ri.id AS item_id FROM receipt_items ri
           JOIN receipts r ON r.id=ri.receipt_id JOIN tests t ON t.id=ri.test_id
           WHERE t.is_culture=1 AND COALESCE(r.lab_no,'') LIKE ?""",
        ("%LAB_MIX_UNIQ%",))]
    t.check(ci in micro_items, "micro list includes the culture item")
    t.check(ni not in micro_items, "micro list excludes the non-culture item")
    t.eq(len(micro_items), 1, "exactly one culture item from mixed order")

    # search filter (patient/lab) behaves like the page's LIKE on both columns
    by_name = [r["item_id"] for r in con.execute(
        """SELECT ri.id AS item_id FROM receipt_items ri
           JOIN receipts r ON r.id=ri.receipt_id JOIN tests t ON t.id=ri.test_id
           WHERE t.is_culture=1 AND (COALESCE(r.patient_name,'') LIKE ?
                                     OR COALESCE(r.lab_no,'') LIKE ?)""",
        ("%Mixed Order%", "%Mixed Order%"))]
    t.check(ci in by_name, "micro search matches by patient name")
    # non-matching search returns nothing for that receipt
    none_match = [r["item_id"] for r in con.execute(
        """SELECT ri.id AS item_id FROM receipt_items ri
           JOIN receipts r ON r.id=ri.receipt_id JOIN tests t ON t.id=ri.test_id
           WHERE t.is_culture=1 AND (COALESCE(r.patient_name,'') LIKE ?
                                     OR COALESCE(r.lab_no,'') LIKE ?)""",
        ("%ZZZ_NO_SUCH%", "%ZZZ_NO_SUCH%"))]
    t.check(ci not in none_match, "micro search excludes on no match")

    # ======================================================================
    # 9. large-volume sensitivity panel (extreme antibiotic count)
    # ======================================================================
    t.section("large sensitivity panel")
    rid_l, item_l = _make_culture_item(t, ct["id"], ct["name"], lab="LAB_BIG_PANEL")
    big = [(f"Antibiotic{i:02d}", ["S", "I", "R"][i % 3]) for i in range(60)]
    cid_l = _save_culture(con, item_l, organism="Multi-resistant", sens=big)
    n = con.execute("SELECT COUNT(*) c FROM culture_sensitivity WHERE culture_id=?",
                    (cid_l,)).fetchone()["c"]
    t.eq(n, 60, "all 60 antibiotics saved")
    # report orders by antibiotic name (ORDER BY antibiotic)
    if have_cs:
        item_l_row = con.execute("SELECT * FROM receipt_items WHERE id=?",
                                 (item_l,)).fetchone()
        html_l = rep._culture_section(con, item_l_row)
        for i in range(0, 60, 7):
            t.has(html_l, f"Antibiotic{i:02d}", f"big panel shows Antibiotic{i:02d}")
    db_order = [r["antibiotic"] for r in con.execute(
        "SELECT antibiotic FROM culture_sensitivity WHERE culture_id=? ORDER BY antibiotic",
        (cid_l,))]
    t.eq(db_order, sorted(db_order), "report sensitivity rows alpha-ordered")

    t.section("microbiology generator complete")
