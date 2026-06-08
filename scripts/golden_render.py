#!/usr/bin/env python3
"""Golden-output safety net for the clean-code refactor.

The native renderer (render.py) and the report/billing logic must produce
**bit-for-bit identical output** before and after the decomposition. This module
builds a fixed, fully date-pinned set of receipts + lab reports, then captures a
hash of every observable signal:

  * pixel hash of every rendered page   (render.render_pages — the *real* output
    users see/print; guards render.py)
  * hash of the receipt/report HTML      (report.build_*_html; guards report.py)
  * the billing totals + amount-in-words (guards money logic)

Pixel hashes depend on the local Qt/font build, so this is a **same-machine
baseline check**, not a portable assertion: snapshot once on known-good code,
then compare after every refactor step.

Usage:
    python scripts/golden_render.py snapshot   # write build/golden_baseline.json
    python scripts/golden_render.py compare     # diff current vs baseline (exit 1 on drift)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

BASELINE = Path(__file__).resolve().parents[1] / "build" / "golden_baseline.json"

# Every date the renderers can read is pinned so output never depends on the
# wall clock (received_at also feeds a datetime.now() year-fallback otherwise).
FIXED_RECEIVED_AT = "2024-01-15 09:30"
FIXED_REPORTED_AT = "2024-01-15 14:00"
FIXED_REPORT_DUE = "2024-01-16 18:00"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _page_pixels(images) -> str:
    """Stable hash of a list of QImage pages (raw pixels + dimensions)."""
    h = hashlib.sha256()
    for im in images:
        h.update(bytes(im.constBits()))
        h.update(f"|{im.width()}x{im.height()}|".encode())
    return h.hexdigest()


def _make_receipt(con, *, lab_no, charges, discount_pct, paid, status, created_by):
    """Insert one fully-pinned receipt with explicit item charges. Returns rid."""
    subtotal = round(sum(charges), 2)
    net = round(subtotal - subtotal * discount_pct / 100.0, 2)
    due = max(0.0, round(net - paid, 2))
    pid = con.execute(
        "INSERT INTO patients(name,age,age_desc,sex,telephone,address) "
        "VALUES('Ali Khan',34,'Years','Male','03001234567','Sargodha')"
    ).lastrowid
    rid = con.execute(
        """INSERT INTO receipts(lab_no,patient_id,patient_name,age,age_desc,sex,
                telephone,address,dr_name,specimen,received_at,report_due,
                subtotal,discount_pct,net_amount,paid,due,status,reported_at,created_by)
           VALUES(?,?,'Ali Khan',34,'Years','Male','03001234567','Sargodha',
                'Dr. Saíd','Blood',?,?,?,?,?,?,?,?,?,?)""",
        (
            lab_no,
            pid,
            FIXED_RECEIVED_AT,
            FIXED_REPORT_DUE,
            subtotal,
            discount_pct,
            net,
            paid,
            due,
            status,
            FIXED_REPORTED_AT,
            created_by,
        ),
    ).lastrowid
    rows = con.execute(
        "SELECT test_id FROM test_parameters GROUP BY test_id ORDER BY test_id LIMIT ?",
        (len(charges),),
    ).fetchall()
    for j, ch in enumerate(charges):
        tid = rows[j % len(rows)][0]
        tname = con.execute("SELECT name FROM tests WHERE id=?", (tid,)).fetchone()[0]
        con.execute(
            "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) VALUES(?,?,?,?)",
            (rid, tid, tname, ch),
        )
    con.commit()
    return rid


def _add_results(con, rid):
    """Finalise results for every parameter on a receipt's items (for the report)."""
    items = con.execute(
        "SELECT id,test_id FROM receipt_items WHERE receipt_id=? ORDER BY id", (rid,)
    ).fetchall()
    for item_id, test_id in items:
        params = con.execute(
            "SELECT id,name FROM test_parameters WHERE test_id=? ORDER BY id", (test_id,)
        ).fetchall()
        for k, (param_id, _name) in enumerate(params):
            con.execute(
                "INSERT INTO results(receipt_item_id,parameter_id,value) VALUES(?,?,?)",
                (item_id, param_id, f"{10 + k}.{k}"),
            )
    con.commit()


def _build_fixtures(con):
    """A deterministic spread of receipts/reports covering the money + render
    matrix: discounts, overpayment/change, dues, multi-item, single-item."""
    specs = [
        dict(
            lab_no="G-0001",
            charges=[1000.0],
            discount_pct=0,
            paid=1000.0,
            status="reported",
            created_by="admin",
        ),
        dict(
            lab_no="G-0002",
            charges=[800.0, 450.0],
            discount_pct=10,
            paid=500.0,
            status="reported",
            created_by="admin",
        ),
        dict(
            lab_no="G-0003",
            charges=[1250.0, 333.0, 50.0],
            discount_pct=12.5,
            paid=2000.0,
            status="delivered",
            created_by="recep1",
        ),
        dict(
            lab_no="G-0004",
            charges=[0.0],
            discount_pct=0,
            paid=0.0,
            status="pending",
            created_by=None,
        ),
        dict(
            lab_no="G-0005",
            charges=[99999.0],
            discount_pct=33,
            paid=10000.0,
            status="reported",
            created_by="admin",
        ),
    ]
    out = []
    for s in specs:
        rid = _make_receipt(con, **s)
        with_results = s["status"] in ("reported", "delivered")
        if with_results:
            _add_results(con, rid)
        out.append((s["lab_no"], rid, with_results))
    return out


def capture() -> dict:
    """Render every fixture and return {key: hash} for all observable signals."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["LABDESK_DATA_DIR"] = tempfile.mkdtemp(prefix="golden_")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from labdesk import db, render, report  # noqa: E402

    render.preload()
    db.init_db(db.db_path())
    con = db.connect(db.db_path())

    sig: dict[str, str] = {}
    for lab_no, rid, with_results in _build_fixtures(con):
        # real native output (the thing users print) — pixel hash
        sig[f"{lab_no}:receipt_px"] = _page_pixels(render.render_pages(con, rid, "receipt"))
        # parallel HTML representation + money logic
        rhtml = report.build_receipt_html(con, rid)
        sig[f"{lab_no}:receipt_html"] = _sha(rhtml.encode())
        row = con.execute(
            "SELECT subtotal,net_amount,paid,due FROM receipts WHERE id=?", (rid,)
        ).fetchone()
        sig[f"{lab_no}:totals"] = _sha(
            f"{row[0]:.2f}|{row[1]:.2f}|{row[2]:.2f}|{row[3]:.2f}|"
            f"{report._amount_in_words(row[1])}".encode()
        )
        if with_results:
            sig[f"{lab_no}:report_px"] = _page_pixels(render.render_pages(con, rid, "report"))
            sig[f"{lab_no}:report_html"] = _sha(report.build_report_html(con, rid).encode())
    return sig


def main(argv):
    mode = argv[1] if len(argv) > 1 else "compare"
    current = capture()
    if mode == "snapshot":
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(current, indent=2, sort_keys=True))
        print(f"snapshot: wrote {len(current)} signals to {BASELINE}")
        return 0
    if not BASELINE.exists():
        print(f"ERROR: no baseline at {BASELINE} — run `snapshot` first", file=sys.stderr)
        return 2
    baseline = json.loads(BASELINE.read_text())
    drift = [k for k in sorted(set(baseline) | set(current)) if baseline.get(k) != current.get(k)]
    if drift:
        print(f"GOLDEN DRIFT in {len(drift)} signal(s):", file=sys.stderr)
        for k in drift:
            print(f"  {k}: {baseline.get(k)} -> {current.get(k)}", file=sys.stderr)
        return 1
    print(f"golden OK: {len(current)} signals identical to baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
