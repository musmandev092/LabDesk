"""Render screenshots of every screen + dialog (with demo data) for QA review.

Renders the WHOLE app in BOTH light and dark themes into /tmp/qa_shots/<theme>/
so washouts/glitches can be compared side by side. Pages are looked up by their
NAV label (not a hard-coded index) so this can't silently drift when pages are
added/reordered.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

OUT = Path("/tmp/qa_shots")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["LABDESK_DATA_DIR"] = "/tmp/qa_data"
import shutil

shutil.rmtree("/tmp/qa_data", ignore_errors=True)
shutil.rmtree(OUT, ignore_errors=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PySide6.QtWidgets import QApplication

from labdesk import db
from labdesk.ui.style import apply_theme

app = QApplication(sys.argv)
con = db.init_db()

# ---- branding + demo data (once) -------------------------------------------
cfg = {
    "configured": "1",
    "lab_name": "City Diagnostic Lab",
    "lab_subtitle": "Pathology • Microbiology • Radiology",
    "address": "Main Boulevard, Lahore",
    "phone": "042-111-2233",
    "mobile": "0300-1234567",
    "email": "info@citylab.pk",
    "currency": "Rs.",
    "lab_no_prefix": "CDL",
    "phc_reg_no": "PHC-44218",
    "lab_reg_no": "LAB-2024-77",
    "signatory_1_name": "Dr. Imran Ali",
    "signatory_1_title": "Consultant Pathologist",
    "signatory_2_name": "Dr. Sara Khan",
    "signatory_2_title": "Consultant Haematologist",
    "whatsapp_url": "http://localhost:3000",
}
for k, v in cfg.items():
    db.set_setting(con, k, v)

con.execute(
    "INSERT INTO doctors(name,hospital,area,tel,mobile) VALUES ('Dr. Ahmed Raza','City Hospital','Gulberg','042-555','0301-1112223')"
)
con.execute(
    "INSERT INTO doctors(name,hospital,area,tel,mobile) VALUES ('Dr. Fatima Noor','Care Clinic','Model Town','042-777','0322-4445556')"
)
con.commit()
doc = con.execute("SELECT id FROM doctors LIMIT 1").fetchone()[0]


def make_receipt(name, title, sex, age, tests, paid, status="pending"):
    pid = con.execute(
        "INSERT INTO patients(title,mr_no,name,age,age_desc,sex,telephone) VALUES (?,?,?,?,?,?,?)",
        (title, "", name, age, "Years", sex, "03001234567"),
    ).lastrowid
    mr = f"MR{pid:05d}"
    con.execute("UPDATE patients SET mr_no=? WHERE id=?", (mr, pid))
    sub = sum(t[2] for t in tests)
    rid = con.execute(
        """INSERT INTO receipts(lab_no,case_no,title,mr_no,patient_id,doctor_id,patient_name,age,age_desc,sex,
        telephone,dr_name,specimen,subtotal,net_amount,paid,due,status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            None,
            None,
            title,
            mr,
            pid,
            doc,
            name,
            age,
            "Years",
            sex,
            "03001234567",
            "Dr. Ahmed Raza",
            "3cc EDTA Whole Blood (Lavender)",
            sub,
            sub,
            paid,
            sub - paid,
            status,
        ),
    ).lastrowid
    lab = f"CDL-{rid:05d}"
    con.execute("UPDATE receipts SET lab_no=?,case_no=? WHERE id=?", (lab, lab, rid))
    iids = []
    for tid, tn, charge in tests:
        iids.append(
            con.execute(
                "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) VALUES (?,?,?,?)",
                (rid, tid, tn, charge),
            ).lastrowid
        )
    con.commit()
    return rid, iids


cbc = con.execute("SELECT id,name,charges FROM tests WHERE name LIKE '%CBC%' LIMIT 1").fetchone()
lft = con.execute("SELECT id,name,charges FROM tests WHERE name LIKE '%LFT%' LIMIT 1").fetchone()
cult = con.execute("SELECT id,name,charges FROM tests WHERE is_culture=1 LIMIT 1").fetchone()
r1, i1 = make_receipt(
    "Muhammad Usman",
    "Mr.",
    "Male",
    35,
    [(cbc["id"], cbc["name"], cbc["charges"]), (lft["id"], lft["name"], lft["charges"])],
    500,
)
r2, _ = make_receipt(
    "Ayesha Bibi", "Mrs.", "Female", 28, [(cbc["id"], cbc["name"], cbc["charges"])], 300, "reported"
)
if cult:
    r3, _ = make_receipt(
        "Bilal Khan", "Mr.", "Male", 40, [(cult["id"], cult["name"], cult["charges"])], 0, "pending"
    )
# give r2 a finalised result + reported date so the report buttons light up
con.execute(
    "UPDATE receipts SET reported_at=datetime('now','localtime'), status='reported' WHERE id=?",
    (r2,),
)
con.execute(
    "INSERT INTO expenses(date,head,detail,amount) VALUES (date('now'),'Reagents','CBC kit',12000)"
)
con.execute(
    "INSERT INTO expenses(date,head,detail,amount) VALUES (date('now'),'Salary','Technician',45000)"
)
con.commit()

user = con.execute("SELECT * FROM users LIMIT 1").fetchone()

PAGES = [
    ("Dashboard", "03_dashboard"),
    ("Reception / Billing", "04_reception"),
    ("Receipts / Reports", "05_receipts"),
    ("Worklist / Results", "06_worklist"),
    ("Test Catalog", "07_catalog"),
    ("Doctors", "08_doctors"),
    ("Microbiology", "09_microbiology"),
    ("Accounts", "10_accounts"),
    ("Settings", "11_settings"),
    ("Logs", "12_logs"),
]


def render_theme(theme: str):
    apply_theme(app, theme)
    outdir = OUT / theme
    outdir.mkdir(parents=True, exist_ok=True)

    def settle(n=5):
        for _ in range(n):
            app.processEvents()

    def shot(widget, name, w=1320, h=860):
        widget.resize(w, h)
        widget.show()
        settle()
        widget.grab().save(str(outdir / f"{name}.png"))
        widget.close()
        print(f"  [{theme}] {name}")

    # pre-login surfaces
    from labdesk.ui.setup_wizard import SetupWizard

    shot(SetupWizard(con), "01_setup_wizard", 720, 800)
    from labdesk.ui.login import LoginDialog

    shot(LoginDialog(con), "02_login", 460, 620)

    # main window — every page by label
    from labdesk.ui.main_window import MainWindow

    win = MainWindow(con, user)
    win.resize(1320, 860)
    win.show()
    settle()
    for label, name in PAGES:
        win.go(win._page_index[label])
        settle()
        win.grab().save(str(outdir / f"{name}.png"))
        print(f"  [{theme}] {name}")

    # filled / selected states ------------------------------------------------
    # reception filled
    win.go(win._page_index["Reception / Billing"])
    rec = win.pages[win._page_index["Reception / Billing"]]
    rec.title.setCurrentText("Mr.")
    rec.name.setText("Imran Shah")
    rec.age.setValue(45)
    rec.tel.setText("0300-9998887")
    rec.specimen.setCurrentText("3cc EDTA Whole Blood (Lavender)")
    rec.search_tests("CBC")
    settle()
    if rec.results.count():
        rec.add_from_list(rec.results.item(0))
    rec.search_tests("LFT")
    settle()
    if rec.results.count():
        rec.add_from_list(rec.results.item(0))
    rec.paid.setValue(400)
    settle()
    win.grab().save(str(outdir / "04b_reception_filled.png"))
    print(f"  [{theme}] 04b_reception_filled")

    # receipts with a row selected (toolbar lights up)
    win.go(win._page_index["Receipts / Reports"])
    rcpt = win.pages[win._page_index["Receipts / Reports"]]
    settle()
    if rcpt.table.rowCount():
        rcpt.table.selectRow(0)
        settle()
    win.grab().save(str(outdir / "05b_receipts_selected.png"))
    print(f"  [{theme}] 05b_receipts_selected")

    # worklist result entry
    win.go(win._page_index["Worklist / Results"])
    wl = win.pages[win._page_index["Worklist / Results"]]
    wl.status_filter.setCurrentIndex(0)
    settle()
    if wl.table.rowCount():
        wl.table.selectRow(0)
        wl.load_receipt()
        settle()
    win.grab().save(str(outdir / "06b_worklist_results.png"))
    print(f"  [{theme}] 06b_worklist_results")

    # catalog params
    win.go(win._page_index["Test Catalog"])
    cat = win.pages[win._page_index["Test Catalog"]]
    settle()
    for row in range(cat.tests.rowCount()):
        it = cat.tests.item(row, 0)
        if it and "CBC" in it.text():
            cat.tests.selectRow(row)
            cat.show_params()
            break
    settle()
    win.grab().save(str(outdir / "07b_catalog_params.png"))
    print(f"  [{theme}] 07b_catalog_params")

    # microbiology selected
    win.go(win._page_index["Microbiology"])
    mb = win.pages[win._page_index["Microbiology"]]
    settle()
    if mb.table.rowCount():
        mb.table.selectRow(0)
        if hasattr(mb, "load_item"):
            mb.load_item()
        settle()
    win.grab().save(str(outdir / "09b_microbiology_sel.png"))
    print(f"  [{theme}] 09b_microbiology_sel")

    # accounts tabs
    win.go(win._page_index["Accounts"])
    ac = win.pages[win._page_index["Accounts"]]
    settle()
    for ti, nm in [(1, "10b_accounts_expenses"), (2, "10c_accounts_dues")]:
        if ac.tabs.count() > ti:
            ac.tabs.setCurrentIndex(ti)
            settle()
            win.grab().save(str(outdir / f"{nm}.png"))
            print(f"  [{theme}] {nm}")

    win.close()

    # dialogs -----------------------------------------------------------------
    from labdesk.ui.catalog import TestDialog

    trow = con.execute("SELECT * FROM tests WHERE name LIKE '%CBC%' LIMIT 1").fetchone()
    shot(TestDialog(None, trow), "20_test_dialog", 500, 540)
    from labdesk.ui.doctors import DoctorDialog

    drow = con.execute("SELECT * FROM doctors LIMIT 1").fetchone()
    shot(DoctorDialog(None, drow), "21_doctor_dialog", 440, 380)
    from labdesk.ui.receipts import _EditReceiptDialog

    rec_row = con.execute("SELECT * FROM receipts WHERE id=?", (r1,)).fetchone()
    shot(_EditReceiptDialog(con, rec_row, "Rs."), "22_edit_bill_dialog", 520, 620)
    from labdesk.ui.settings import UserDialog

    shot(UserDialog(None), "23_user_dialog", 460, 360)


for theme in ("light", "dark"):
    print(f"== rendering {theme} ==")
    render_theme(theme)

print("ALL SCREENSHOTS DONE ->", OUT)
