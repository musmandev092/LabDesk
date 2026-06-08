#!/usr/bin/env python3
"""Generator-based mega-QA runner for LabDesk.

This file owns *all* isolation + the assertion harness. Each domain test lives in
``tests/gen/test_<domain>.py`` and exposes a single ``register(t)`` function that
receives the harness ``t`` and emits assertions via ``t.check / t.eq / t.has / t.near``.

Safety (identical guarantees to tests/test_all.py):
  * ``LABDESK_DATA_DIR`` points at a throwaway temp dir — the live DB is never touched.
  * ``urllib`` is monkeypatched — **no WhatsApp message ever leaves the machine**; every
    gateway failure mode is simulated locally through the ``t.SCN`` scenario dict.
  * ``QT_QPA_PLATFORM=offscreen`` — no real window is shown.

Run everything:     QT_QPA_PLATFORM=offscreen .venv/bin/python tests/run_gen.py
Run one module:     RUN_ONLY=test_billing .venv/bin/python tests/run_gen.py
Machine summary:    written to $GEN_SUMMARY (default /tmp/gen_summary.json)
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import socket
import sys
import tempfile
import traceback
import urllib.error
import urllib.request
from pathlib import Path

# ---- isolation: throwaway data dir BEFORE importing labdesk.db --------------
_TMP = tempfile.mkdtemp(prefix="labdesk_gen_")
os.environ["LABDESK_DATA_DIR"] = _TMP
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from labdesk import db, render, report, roles, whatsapp  # noqa: E402
from labdesk.constants import normalize_phone  # noqa: E402

# ============================================================================
# Fake WhatsApp gateway — patched over urllib so nothing leaves the machine.
# Generators drive it through t.SCN, e.g. t.SCN["mode"] = "down".
# ============================================================================
SCN: dict = {"mode": "ok"}


class _Resp:
    def __init__(self, status, body):
        self.status = status
        self._b = body.encode() if isinstance(body, str) else body

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code, body=b""):
    return urllib.error.HTTPError("http://gw/x", code, "err", {}, io.BytesIO(body))


def fake_urlopen(req, timeout=None):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    mode = SCN["mode"]
    if mode == "down":
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
    if mode == "no_internet":
        raise urllib.error.URLError(socket.gaierror(-2, "Name or service not known"))
    if mode == "timeout_wrapped":
        raise urllib.error.URLError(TimeoutError("timed out"))
    if mode == "timeout_raw":
        raise TimeoutError("timed out")
    if mode == "refused_raw":
        raise ConnectionRefusedError(111, "Connection refused")
    if mode == "unauthorized":
        raise _http_error(401, b'{"error":"bad token"}')
    if mode == "forbidden":
        raise _http_error(403, b'{"error":"forbidden"}')
    if mode == "notfound":
        raise _http_error(404, b"not found")
    if mode == "server_error_session":
        raise _http_error(500, b'{"error":"user is not logged in"}')
    if url.endswith("/session/status"):
        data = SCN.get("status", {"connected": True, "loggedIn": True})
        return _Resp(200, json.dumps({"success": True, "data": data}))
    return _Resp(
        SCN.get("send_status", 200), SCN.get("send_body", '{"success":true,"data":{"Id":"X"}}')
    )


urllib.request.urlopen = fake_urlopen  # global patch — no real network, ever


# ============================================================================
# Harness handed to every generator's register(t).
# ============================================================================
class Harness:
    def __init__(self, con):
        # modules (so generators don't re-import) ---------------------------
        self.db = db
        self.whatsapp = whatsapp
        self.report = report
        self.render = render
        self.roles = roles
        self.normalize_phone = normalize_phone
        # state -------------------------------------------------------------
        self.con = con
        self.SCN = SCN
        self.tmp = Path(_TMP)
        self.dummy_pdf = Path(_TMP) / "dummy.pdf"
        self.dummy_pdf.write_bytes(b"%PDF-1.4\n% dummy\n")
        # counters ----------------------------------------------------------
        self.passed = 0
        self.failed = 0
        self.fails: list[str] = []  # capped sample of failure names
        self._cur = "?"  # current module stem

    # --- assertion primitives ---------------------------------------------
    def check(self, cond, name):
        if cond:
            self.passed += 1
        else:
            self.failed += 1
            if len(self.fails) < 400:
                self.fails.append(f"[{self._cur}] {name}")

    def eq(self, a, b, name):
        self.check(a == b, f"{name}: got {a!r} want {b!r}")

    def near(self, a, b, name, tol=1e-9):
        self.check(abs(a - b) <= tol, f"{name}: got {a!r} ~ {b!r}")

    def has(self, hay, needle, name):
        self.check(needle.lower() in (hay or "").lower(), f"{name}: msg={hay!r}")

    def section(self, title):
        print(f"  …[{self._cur}] {title}")

    # --- shared receipt factory (mirrors tests/test_all.py) ---------------
    def make_receipt(
        self,
        phone="03001234567",
        *,
        sub=1000.0,
        paid=1000.0,
        with_results=True,
        status="reported",
        sex="Male",
        age=30,
    ):
        con = self.con
        pid = con.execute(
            "INSERT INTO patients(name,age,age_desc,sex,telephone,mr_no) VALUES (?,?,?,?,?,?)",
            ("Test Patient", age, "Years", sex, phone, None),
        ).lastrowid
        test_id = con.execute(
            "SELECT test_id FROM test_parameters GROUP BY test_id LIMIT 1"
        ).fetchone()[0]
        tname = con.execute("SELECT name FROM tests WHERE id=?", (test_id,)).fetchone()[0]
        due = max(0.0, sub - paid)
        rid = con.execute(
            """INSERT INTO receipts(lab_no,patient_id,patient_name,age,age_desc,sex,telephone,
                                    dr_name,specimen,subtotal,net_amount,paid,due,status,mr_no)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f"LAB_GEN_{pid:05d}",
                pid,
                "Test Patient",
                age,
                "Years",
                sex,
                phone,
                "Dr. Test",
                "3cc EDTA",
                sub,
                sub,
                paid,
                due,
                status,
                None,
            ),
        ).lastrowid
        item_id = con.execute(
            "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) VALUES (?,?,?,?)",
            (rid, test_id, tname, sub),
        ).lastrowid
        if with_results:
            params = con.execute(
                "SELECT * FROM test_parameters WHERE test_id=? ORDER BY seq LIMIT 4", (test_id,)
            ).fetchall()
            for p in params:
                con.execute(
                    """INSERT INTO results(receipt_item_id,parameter_id,seq,part_type,name,units,
                                           ref_text,value,hidden)
                       VALUES (?,?,?,?,?,?,?,?,0)""",
                    (
                        item_id,
                        p["id"],
                        p["seq"],
                        p["part_type"] or "N",
                        p["name"],
                        p["units"],
                        p["ref_male"],
                        "1",
                    ),
                )
        con.commit()
        return rid


# ============================================================================
# Discover + run generators
# ============================================================================
def _discover(only):
    gen_dir = _ROOT / "tests" / "gen"
    gen_dir.mkdir(exist_ok=True)
    mods = []
    for path in sorted(gen_dir.glob("test_*.py")):
        stem = path.stem
        if only and stem not in only:
            continue
        mods.append((stem, path))
    return mods


def main():
    only = set(filter(None, os.environ.get("RUN_ONLY", "").split(",")))
    print("Setting up isolated mega-QA database…")
    con = db.init_db()
    t = Harness(con)

    mods = _discover(only)
    if not mods:
        print("  (no generator modules found in tests/gen/)")
    per_module = {}
    for stem, path in mods:
        t._cur = stem
        before_p, before_f = t.passed, t.failed
        spec = importlib.util.spec_from_file_location(f"gen.{stem}", path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            if not hasattr(mod, "register"):
                raise AttributeError("missing register(t)")
            mod.register(t)
        except Exception:
            t.failed += 1
            tb = traceback.format_exc().strip().splitlines()[-1]
            t.fails.append(f"[{stem}] IMPORT/RUN ERROR: {tb}")
            print(f"  !! {stem} crashed: {tb}")
        cases = (t.passed - before_p) + (t.failed - before_f)
        per_module[stem] = {
            "cases": cases,
            "passed": t.passed - before_p,
            "failed": t.failed - before_f,
        }
        print(f"  ✓ {stem}: {cases} cases ({t.failed - before_f} failed)")

    total = t.passed + t.failed
    print("\n" + "=" * 60)
    print(f"  MODULES     : {len(mods)}")
    print(f"  TOTAL CASES : {total}")
    print(f"  PASSED      : {t.passed}")
    print(f"  FAILED      : {t.failed}")
    print("=" * 60)
    if t.fails:
        print("First failures:")
        for f in t.fails[:40]:
            print("   ✗", f)

    summary_path = os.environ.get("GEN_SUMMARY", "/tmp/gen_summary.json")
    Path(summary_path).write_text(
        json.dumps(
            {
                "total": total,
                "passed": t.passed,
                "failed": t.failed,
                "modules": per_module,
                "fails": t.fails[:400],
            },
            indent=2,
        )
    )
    return 1 if t.failed else 0


if __name__ == "__main__":
    sys.exit(main())
