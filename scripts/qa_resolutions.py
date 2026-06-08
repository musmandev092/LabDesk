"""Render the MAIN WINDOW at the critical laptop resolutions + a snapped half-width,
across the form-heavy and table-heavy pages, so real layout overflow/clipping shows.

Out -> /tmp/qa_res/<WxH>_<page>.png
"""
from __future__ import annotations
import os, sys
from pathlib import Path

OUT = Path("/tmp/qa_matrix")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["LABDESK_DATA_DIR"] = "/tmp/qa_res_data"
import shutil
shutil.rmtree("/tmp/qa_res_data", ignore_errors=True)
shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PySide6.QtWidgets import QApplication
from labdesk import db
from labdesk.ui.style import apply_theme

app = QApplication(sys.argv)
con = db.init_db()
cfg = {"configured": "1", "lab_name": "City Diagnostic Lab",
       "lab_subtitle": "Pathology • Microbiology • Radiology", "currency": "Rs.", "lab_no_prefix": "CDL"}
for k, v in cfg.items():
    db.set_setting(con, k, v)
con.execute("INSERT INTO doctors(name,hospital,area,tel,mobile) VALUES ('Dr. Ahmed Raza','City Hospital','Gulberg','042-555','0301-1112223')")
con.commit()
doc = con.execute("SELECT id FROM doctors LIMIT 1").fetchone()[0]


def make_receipt(name, sex, age, tests, paid, status="pending"):
    pid = con.execute("INSERT INTO patients(mr_no,name,age,age_desc,sex,telephone) VALUES (?,?,?,?,?,?)",
                      ("", name, age, "Years", sex, "03001234567")).lastrowid
    mr = f"MR{pid:05d}"; con.execute("UPDATE patients SET mr_no=? WHERE id=?", (mr, pid))
    sub = sum(t[2] for t in tests)
    rid = con.execute("""INSERT INTO receipts(lab_no,case_no,mr_no,patient_id,doctor_id,patient_name,age,age_desc,sex,
        telephone,dr_name,specimen,subtotal,net_amount,paid,due,status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (None,None,mr,pid,doc,name,age,"Years",sex,"03001234567","Dr. Ahmed Raza",
         "3cc EDTA Whole Blood (Lavender)",sub,sub,paid,sub-paid,status)).lastrowid
    lab = f"CDL-{rid:05d}"; con.execute("UPDATE receipts SET lab_no=?,case_no=? WHERE id=?", (lab, lab, rid))
    for tid, tn, charge in tests:
        con.execute("INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) VALUES (?,?,?,?)", (rid, tid, tn, charge))
    con.commit(); return rid


cbc = con.execute("SELECT id,name,charges FROM tests WHERE name LIKE '%CBC%' LIMIT 1").fetchone()
lft = con.execute("SELECT id,name,charges FROM tests WHERE name LIKE '%LFT%' LIMIT 1").fetchone()
for i in range(6):
    make_receipt(f"Patient {i}", "Male" if i % 2 else "Female", 30 + i,
                 [(cbc['id'], cbc['name'], cbc['charges']), (lft['id'], lft['name'], lft['charges'])], 500)
user = con.execute("SELECT * FROM users LIMIT 1").fetchone()

apply_theme(app, "light")
from labdesk.ui.main_window import MainWindow

# critical resolutions (logical) + a snapped half-width on a 1366 screen
SIZES = [
    (1280, 720,  "1280x720_16-9"),       # floor (16:9) — the proposed minimum lock
    (1366, 768,  "1366x768_16-9"),       # most common budget laptop
    (1280, 800,  "1280x800_16-10"),
    (1440, 900,  "1440x900_16-10"),
    (1600, 900,  "1600x900_16-9"),
    (1500, 1000, "1500x1000_3-2"),       # 3:2 Surface — TALL
    (1920, 1080, "1920x1080_16-9"),      # FHD standard
    (1920, 1200, "1920x1200_16-10"),
    (2256, 1504, "2256x1504_3-2"),       # Surface Pro
    (2560, 1440, "2560x1440_16-9"),      # QHD
    (2560, 1600, "2560x1600_16-10"),     # premium 13-14"
    (3000, 2000, "3000x2000_3-2"),       # Surface Book
    (3840, 2160, "3840x2160_4k"),        # 4K native (no scaling) — over-stretch check
]
PAGES = ["Dashboard", "Reception / Billing", "Receipts / Reports", "Worklist / Results",
         "Test Catalog", "Doctors", "Microbiology", "Accounts", "Settings", "Logs"]


def settle(n=6):
    for _ in range(n):
        app.processEvents()


for w, h, tag in SIZES:
    outdir = OUT / tag
    outdir.mkdir(parents=True, exist_ok=True)
    win = MainWindow(con, user)
    win.resize(w, h)        # force the exact resolution under test
    win.show(); settle()
    for label in PAGES:
        idx = win._page_index.get(label)
        if idx is None:
            continue
        win.go(idx); settle()
        safe = label.split(" / ")[0].lower().replace(" ", "")
        win.grab().save(str(outdir / f"{safe}.png"))
    print(f"  [{tag}] rendered {len(PAGES)} pages -> actual {win.width()}x{win.height()}")
    win.close()

print("DONE ->", OUT)
