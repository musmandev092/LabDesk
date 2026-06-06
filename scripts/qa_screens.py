"""Render screenshots of every screen + dialog (with demo data) for QA review."""
from __future__ import annotations
import os, sys
from pathlib import Path

OUT = Path("/tmp/qa_shots"); OUT.mkdir(parents=True, exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["LABDESK_DATA_DIR"] = "/tmp/qa_data"
import shutil
shutil.rmtree("/tmp/qa_data", ignore_errors=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PySide6.QtWidgets import QApplication
from labdesk import db
from labdesk.ui.style import QSS

app = QApplication(sys.argv)
app.setStyleSheet(QSS)
con = db.init_db()

def shot(widget, name, w=1320, h=860, settle=4):
    widget.resize(w, h); widget.show()
    for _ in range(settle):
        app.processEvents()
    widget.grab().save(str(OUT / f"{name}.png"))
    print("saved", name)

# ---- pre-config screens ----
from labdesk.ui.setup_wizard import SetupWizard
shot(SetupWizard(con), "01_setup_wizard", 700, 780)

# configure branding
cfg = {
    "configured": "1", "lab_name": "City Diagnostic Lab",
    "lab_subtitle": "Pathology • Microbiology • Radiology",
    "address": "Main Boulevard, Lahore", "phone": "042-111-2233", "mobile": "0300-1234567",
    "email": "info@citylab.pk", "currency": "Rs.", "lab_no_prefix": "CDL",
    "phc_reg_no": "PHC-44218", "lab_reg_no": "LAB-2024-77",
    "signatory_1_name": "Dr. Imran Ali", "signatory_1_title": "Consultant Pathologist",
    "signatory_2_name": "Dr. Sara Khan", "signatory_2_title": "Consultant Haematologist",
    "whatsapp_url": "http://localhost:3000",
}
for k, v in cfg.items():
    db.set_setting(con, k, v)

from labdesk.ui.login import LoginDialog
shot(LoginDialog(con), "02_login", 440, 560)

# ---- demo data ----
con.execute("INSERT INTO doctors(name,hospital,area,tel,mobile) VALUES ('Dr. Ahmed Raza','City Hospital','Gulberg','042-555','0301-1112223')")
con.execute("INSERT INTO doctors(name,hospital,area,tel,mobile) VALUES ('Dr. Fatima Noor','Care Clinic','Model Town','042-777','0322-4445556')")
con.commit()
doc = con.execute("SELECT id FROM doctors LIMIT 1").fetchone()[0]

def make_receipt(name, title, sex, age, tests, paid, status="pending"):
    pid = con.execute("INSERT INTO patients(title,mr_no,name,age,age_desc,sex,telephone) VALUES (?,?,?,?,?,?,?)",
                      (title, "", name, age, "Years", sex, "03001234567")).lastrowid
    mr = f"MR{pid:05d}"; con.execute("UPDATE patients SET mr_no=? WHERE id=?", (mr, pid))
    sub = sum(t[2] for t in tests)
    rid = con.execute("""INSERT INTO receipts(lab_no,case_no,title,mr_no,patient_id,doctor_id,patient_name,age,age_desc,sex,
        telephone,dr_name,specimen,subtotal,net_amount,paid,due,status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (None,None,title,mr,pid,doc,name,age,"Years",sex,"03001234567","Dr. Ahmed Raza",
         "3cc EDTA Whole Blood (Lavender)",sub,sub,paid,sub-paid,status)).lastrowid
    lab=f"CDL-{rid:05d}"; con.execute("UPDATE receipts SET lab_no=?,case_no=? WHERE id=?",(lab,lab,rid))
    iids=[]
    for tid,tn,charge in tests:
        iids.append(con.execute("INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) VALUES (?,?,?,?)",
                                (rid,tid,tn,charge)).lastrowid)
    con.commit(); return rid, iids

cbc = con.execute("SELECT id,name,charges FROM tests WHERE name LIKE '%CBC%' LIMIT 1").fetchone()
lft = con.execute("SELECT id,name,charges FROM tests WHERE name LIKE '%LFT%' LIMIT 1").fetchone()
cult = con.execute("SELECT id,name,charges FROM tests WHERE is_culture=1 LIMIT 1").fetchone()
r1,_ = make_receipt("Muhammad Usman","Mr.","Male",35,[(cbc['id'],cbc['name'],cbc['charges']),(lft['id'],lft['name'],lft['charges'])],500)
r2,i2 = make_receipt("Ayesha Bibi","Mrs.","Female",28,[(cbc['id'],cbc['name'],cbc['charges'])],300)
if cult:
    r3,_ = make_receipt("Bilal Khan","Mr.","Male",40,[(cult['id'],cult['name'],cult['charges'])],0,"pending")
con.execute("INSERT INTO expenses(date,head,detail,amount) VALUES (date('now'),'Reagents','CBC kit',12000)")
con.execute("INSERT INTO expenses(date,head,detail,amount) VALUES (date('now'),'Salary','Technician',45000)")
con.commit()

# ---- main window pages ----
from labdesk.ui.main_window import MainWindow
user = con.execute("SELECT * FROM users LIMIT 1").fetchone()
win = MainWindow(con, user); win.resize(1320, 860); win.show()
for _ in range(4): app.processEvents()
pages = ["03_dashboard","04_reception_empty","05_worklist","06_catalog","07_doctors","08_microbiology","09_accounts","10_settings"]
idx   = [0,1,2,3,4,5,6,7]
for n,i in zip(pages, idx):
    win.go(i)
    for _ in range(4): app.processEvents()
    win.grab().save(str(OUT / f"{n}.png")); print("saved", n)

# reception with patient + cart filled
rec = win.pages[1]; win.go(1)
rec.title.setCurrentText("Mr."); rec.name.setText("Imran Shah"); rec.age.setValue(45)
rec.tel.setText("0300-9998887"); rec.specimen.setCurrentText("3cc EDTA Whole Blood (Lavender)")
rec.search_tests("CBC");
for _ in range(3): app.processEvents()
if rec.results.count(): rec.add_from_list(rec.results.item(0))
rec.search_tests("LFT")
for _ in range(3): app.processEvents()
if rec.results.count(): rec.add_from_list(rec.results.item(0))
rec.paid.setValue(400)
for _ in range(3): app.processEvents()
win.grab().save(str(OUT / "11_reception_filled.png")); print("saved 11")

# worklist with a receipt selected -> result entry
wl = win.pages[2]; win.go(2)
for _ in range(3): app.processEvents()
if wl.table.rowCount():
    wl.table.selectRow(0); wl.load_receipt()
    for _ in range(4): app.processEvents()
    win.grab().save(str(OUT / "12_worklist_results.png")); print("saved 12")

# microbiology with order selected
mb = win.pages[5]; win.go(5)
for _ in range(3): app.processEvents()
if mb.table.rowCount():
    mb.table.selectRow(0); mb.load_item()
    for _ in range(3): app.processEvents()
win.grab().save(str(OUT / "13_microbiology_sel.png")); print("saved 13")

# accounts tabs
ac = win.pages[6]; win.go(6)
for _ in range(3): app.processEvents()
for ti,nm in [(1,"14_accounts_expenses"),(2,"15_accounts_dues")]:
    ac.tabs.setCurrentIndex(ti)
    for _ in range(3): app.processEvents()
    win.grab().save(str(OUT / f"{nm}.png")); print("saved", nm)

# catalog with a test selected (params)
cat = win.pages[3]; win.go(3)
for _ in range(3): app.processEvents()
# select a row that has params (CBC)
for row in range(cat.tests.rowCount()):
    if cat.tests.item(row,0) and "CBC" in cat.tests.item(row,0).text():
        cat.tests.selectRow(row); cat.show_params(); break
for _ in range(3): app.processEvents()
win.grab().save(str(OUT / "16_catalog_params.png")); print("saved 16")

# dialogs
from labdesk.ui.catalog import TestDialog
trow = con.execute("SELECT * FROM tests WHERE name LIKE '%CBC%' LIMIT 1").fetchone()
shot(TestDialog(None, trow), "17_test_dialog", 480, 520)
from labdesk.ui.doctors import DoctorDialog
drow = con.execute("SELECT * FROM doctors LIMIT 1").fetchone()
shot(DoctorDialog(None, drow), "18_doctor_dialog", 420, 360)

# settings full (grab tall host to see all sections)
st = win.pages[7]; win.go(7)
for _ in range(3): app.processEvents()
win.grab().save(str(OUT / "19_settings_top.png")); print("saved 19")

print("ALL SCREENSHOTS DONE ->", OUT)
