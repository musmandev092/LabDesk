"""Render-category classification, conclusion persistence, and per-category
report rendering.

Covers labdesk.catalog_render.classify / category_for_test, the new
descriptive / qualitative draw paths in render.report_doc, the _polarity colour
helper, and the conclusion write added to application.results.release_results.
"""

from __future__ import annotations

from factories import make_item, make_receipt
from labdesk.application import results as svc
from labdesk.catalog_render import category_for_test, classify
from labdesk.render import report_doc
from labdesk.render.constants import GREEN, RED


def _params(con, test_id):
    return con.execute(
        "SELECT * FROM test_parameters WHERE test_id=? ORDER BY seq", (test_id,)
    ).fetchall()


def _test(con, test_id):
    return con.execute("SELECT * FROM tests WHERE id=?", (test_id,)).fetchone()


# --------------------------------------------------------------------------
# classify / category_for_test
# --------------------------------------------------------------------------


def test_classify_abdominal_ultrasound_is_descriptive(con):
    assert classify(_test(con, 678), _params(con, 678)) == "descriptive"


def test_classify_serology_is_qualitative(con):
    # 652 = VDRL (RPR), 599 = Typhidot Test (IgG & IgM)
    assert classify(_test(con, 652), _params(con, 652)) == "qualitative"
    assert classify(_test(con, 599), _params(con, 599)) == "qualitative"


def test_classify_cbc_lft_rft_stay_numeric(con):
    for tid in (683, 684, 685):
        assert classify(_test(con, tid), _params(con, tid)) == "numeric_tabular"


def test_classify_culture(con):
    cult = con.execute("SELECT id FROM tests WHERE is_culture=1 LIMIT 1").fetchone()[
        "id"
    ]
    assert classify(_test(con, cult), _params(con, cult)) == "culture"


def test_category_for_test_honours_override(con):
    # A non-NULL render_category overrides classification.
    con.execute("UPDATE tests SET render_category='qualitative' WHERE id=683")
    con.commit()
    assert category_for_test(con, 683) == "qualitative"
    con.execute("UPDATE tests SET render_category=NULL WHERE id=683")
    con.commit()
    assert category_for_test(con, 683) == "numeric_tabular"


def test_category_for_unknown_test_defaults_numeric(con):
    assert category_for_test(con, 999999) == "numeric_tabular"


# --------------------------------------------------------------------------
# _polarity colouring
# --------------------------------------------------------------------------


def test_polarity_positive_is_red_negative_is_green():
    assert report_doc._polarity("Positive") == RED
    assert report_doc._polarity("Reactive") == RED
    assert report_doc._polarity("Detected") == RED
    assert report_doc._polarity("Negative") == GREEN
    assert report_doc._polarity("Non-Reactive") == GREEN
    assert report_doc._polarity("Not Detected") == GREEN


def test_polarity_unknown_is_none():
    # blood groups and titres carry no pathology polarity → no colour
    assert report_doc._polarity("Group A") is None
    assert report_doc._polarity("O+") is None
    assert report_doc._polarity("1:160") is None
    assert report_doc._polarity("") is None


# --------------------------------------------------------------------------
# conclusion persistence (release_results)
# --------------------------------------------------------------------------


def test_release_persists_conclusion(con):
    rid = make_receipt(con, status="pending")
    iid = make_item(con, rid, test_id=678, test_name="Ultrasound-Abdominal")
    svc.release_results(
        con,
        receipt_id=rid,
        result_rows=[{"item_id": iid, "parameter_id": None, "value": "x", "hidden": 0}],
        remarks={},
        static_rows=[],
        actor_username="tom",
        actor_role="technician",
        conclusion={iid: "Normal study. No abnormality detected."},
    )
    got = con.execute(
        "SELECT conclusion FROM receipt_items WHERE id=?", (iid,)
    ).fetchone()[0]
    assert got == "Normal study. No abnormality detected."


def test_release_blank_conclusion_stored_as_null(con):
    rid = make_receipt(con, status="pending")
    iid = make_item(con, rid)
    svc.release_results(
        con,
        receipt_id=rid,
        result_rows=[{"item_id": iid, "parameter_id": None, "value": "x", "hidden": 0}],
        remarks={},
        static_rows=[],
        actor_username="tom",
        actor_role="technician",
        conclusion={iid: ""},
    )
    assert (
        con.execute(
            "SELECT conclusion FROM receipt_items WHERE id=?", (iid,)
        ).fetchone()[0]
        is None
    )


# --------------------------------------------------------------------------
# per-category rendering (smoke: build_report must not crash and emit a PDF)
# --------------------------------------------------------------------------


def _render_test(con, test_id, values, conclusion=None):
    rid = make_receipt(con, status="reported")
    name = _test(con, test_id)["name"]
    iid = con.execute(
        "INSERT INTO receipt_items(receipt_id,test_id,test_name,conclusion) "
        "VALUES (?,?,?,?)",
        (rid, test_id, name, conclusion),
    ).lastrowid
    for p in _params(con, test_id):
        pt = (p["part_type"] or "N").upper()
        val = values.get(p["name"] or "", "") if pt != "H" else ""
        con.execute(
            "INSERT INTO results(receipt_item_id,parameter_id,seq,part_type,name,"
            "units,ref_text,value) VALUES (?,?,?,?,?,?,?,?)",
            (
                iid,
                p["id"],
                p["seq"],
                p["part_type"],
                p["name"],
                p["units"],
                p["ref_male"],
                val,
            ),
        )
    con.commit()
    return rid


def test_render_descriptive_report(con):
    rid = _render_test(
        con,
        678,
        {
            "Liver": "Normal in size and echotexture. No mass or cyst seen. "
            "Portal vein normal in calibre.",
            "Right Kidney": "Normal. Size 9.37 x 4.08 cm. No stone.",
        },
        conclusion="Normal abdominal ultrasound.",
    )
    pdf = report_doc.build_report(con, rid)
    assert isinstance(pdf, bytes) and len(pdf) > 1000


def test_render_qualitative_report(con):
    rid = _render_test(
        con,
        599,
        {"Typhidot IgG": "Positive", "Typhidot IgM": "Negative"},
        conclusion="Past exposure to S. Typhi.",
    )
    pdf = report_doc.build_report(con, rid)
    assert isinstance(pdf, bytes) and len(pdf) > 1000


def test_render_numeric_report_unchanged(con):
    rid = _render_test(con, 683, {"Haemoglobin": "13.5", "Platelets": "250"})
    pdf = report_doc.build_report(con, rid)
    assert isinstance(pdf, bytes) and len(pdf) > 1000


# --------------------------------------------------------------------------
# blood bank (Phase A) + cumulative-history policy
# --------------------------------------------------------------------------


def test_classify_blood_bank(con):
    # 154 Blood Group & Rh, 226 Cross Matching, 211 Coombs Direct
    for tid in (154, 226, 211):
        assert classify(_test(con, tid), _params(con, tid)) == "blood_bank"


def test_render_blood_bank_report(con):
    rid = _render_test(con, 154, {"Blood Group": "B", "Rh Factor": "Positive"})
    pdf = report_doc.build_report(con, rid)
    assert isinstance(pdf, bytes) and len(pdf) > 1000


def test_render_histopath_narrative(con):
    # 140 Biopsy For H/P has no parameters → single free-text narrative report
    rid = make_receipt(con, status="reported")
    iid = con.execute(
        "INSERT INTO receipt_items(receipt_id,test_id,test_name,conclusion) "
        "VALUES (?,140,'Biopsy For H/P',?)",
        (rid, "Chronic inflammation, no malignancy."),
    ).lastrowid
    con.execute(
        "INSERT INTO results(receipt_item_id,parameter_id,seq,part_type,name,value) "
        "VALUES (?,NULL,0,'N','Result',?)",
        (
            iid,
            "Sections show gastric mucosa with mild chronic inflammation. "
            "No dysplasia or malignancy.",
        ),
    )
    con.commit()
    assert category_for_test(con, 140) == "descriptive"
    pdf = report_doc.build_report(con, rid)
    assert isinstance(pdf, bytes) and len(pdf) > 1000


def test_classify_obstetric(con):
    assert classify(_test(con, 679), _params(con, 679)) == "obstetric"


def test_render_obstetric_report(con):
    rid = _render_test(
        con,
        679,
        {"Biparietal Diameter": "8.2", "Femur Length": "6.1"},
        conclusion="Single live fetus, ~32 weeks. EDD 14-Aug-2026.",
    )
    pdf = report_doc.build_report(con, rid)
    assert isinstance(pdf, bytes) and len(pdf) > 1000


def test_prev_impression_note(con):
    from labdesk.report.content import _prev_impression

    con.execute("INSERT INTO patients(id,name,sex) VALUES (77,'P','Male')")
    con.execute(
        "INSERT INTO receipts(id,lab_no,patient_id,received_at,reported_at,status) "
        "VALUES (201,'A',77,'2026-01-01 09:00','2026-01-01 10:00','reported')"
    )
    con.execute(
        "INSERT INTO receipt_items(id,receipt_id,test_id,test_name,conclusion) "
        "VALUES (201,201,678,'USG','Prior hepatomegaly.')"
    )
    con.execute(
        "INSERT INTO receipts(id,lab_no,patient_id,received_at,status) "
        "VALUES (202,'B',77,'2026-06-01 09:00','reported')"
    )
    con.execute(
        "INSERT INTO receipt_items(id,receipt_id,test_id,test_name) "
        "VALUES (202,202,678,'USG')"
    )
    con.commit()
    cur = con.execute("SELECT * FROM receipts WHERE id=202").fetchone()
    item = con.execute("SELECT * FROM receipt_items WHERE id=202").fetchone()
    prev = _prev_impression(con, item, cur)
    assert prev is not None and prev[1] == "Prior hepatomegaly."


def test_test_dialog_render_category_override(con, qtbot):
    from labdesk.presentation.catalog_dialogs import TestDialog

    row = con.execute("SELECT * FROM tests WHERE id=678").fetchone()
    d = TestDialog(data=row)
    qtbot.addWidget(d)
    assert d.values()["render_category"] is None  # NULL → Auto
    d.render_cat.setCurrentIndex(d.render_cat.findData("blood_bank"))
    assert d.values()["render_category"] == "blood_bank"


def test_history_respects_show_history_setting(con):
    from labdesk.report.content import _history_for_item

    rid = make_receipt(con, status="reported")
    iid = make_item(con, rid)
    rcpt = con.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone()
    item = con.execute("SELECT * FROM receipt_items WHERE id=?", (iid,)).fetchone()
    con.execute(
        "INSERT OR REPLACE INTO settings(key,value) VALUES ('show_history','0')"
    )
    con.commit()
    labels, maps = _history_for_item(con, item, rcpt)
    assert labels == [] and maps == []


# --------------------------------------------------------------------------
# category-aware data-entry widgets (worklist)
# --------------------------------------------------------------------------


def test_entry_widgets_match_category(con, qtbot):
    from PySide6.QtWidgets import QComboBox, QLineEdit, QPlainTextEdit

    from labdesk.presentation.worklist import WorklistPage

    rid = make_receipt(con, status="pending")
    for tid, nm in ((678, "USG"), (599, "Typhidot"), (683, "CBC")):
        con.execute(
            "INSERT INTO receipt_items(receipt_id,test_id,test_name) VALUES (?,?,?)",
            (rid, tid, nm),
        )
    con.commit()

    page = WorklistPage(con, {"username": "a", "role": "admin"})
    qtbot.addWidget(page)
    page.refresh_list()
    for r in range(page.table.rowCount()):
        if page._ids[r] == rid:
            page.table.selectRow(r)
            break

    widgets = list(page._editors.values())
    # isinstance (not exact class name) so auto-growing QPlainTextEdit subclasses count
    assert any(isinstance(w, QPlainTextEdit) for w in widgets)  # descriptive findings
    assert any(isinstance(w, QComboBox) for w in widgets)  # qualitative dropdowns
    assert any(isinstance(w, QLineEdit) for w in widgets)  # numeric value boxes
    # a descriptive organ box is pre-filled with its normal template text
    filled = [
        w.toPlainText() for w in page._editors.values() if isinstance(w, QPlainTextEdit)
    ]
    assert any("Normal" in t for t in filled)
