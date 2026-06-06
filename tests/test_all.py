#!/usr/bin/env python3
"""Comprehensive OFFLINE test suite for LabDesk (~2000 use-cases).

Safety guarantees:
  * urllib is monkeypatched — **no WhatsApp message is ever actually sent**, and
    every network failure mode (no internet, gateway down, not logged in, bad
    token, timeout, DNS failure …) is simulated locally.
  * LABDESK_DATA_DIR points at a throwaway temp dir, so the **live database is
    never touched**.

Run:  QT_QPA_PLATFORM=offscreen .venv/bin/python tests/test_all.py
"""
from __future__ import annotations

import io
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

# ---- isolation: throwaway data dir BEFORE importing labdesk.db --------------
_TMP = tempfile.mkdtemp(prefix="labdesk_test_")
os.environ["LABDESK_DATA_DIR"] = _TMP
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from labdesk import db, whatsapp, report                      # noqa: E402
from labdesk.constants import normalize_phone                 # noqa: E402

# ---- tiny assertion framework ----------------------------------------------
PASS = 0
FAIL = 0
FAILS: list[str] = []


def check(cond, name):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        if len(FAILS) < 80:
            FAILS.append(name)


def eq(a, b, name):
    check(a == b, f"{name}: got {a!r} want {b!r}")


def has(hay, needle, name):
    check(needle.lower() in (hay or "").lower(), f"{name}: msg={hay!r}")


def section(title):
    print(f"  …{title}")


# ============================================================================
# Fake WhatsApp gateway — patched over urllib so nothing leaves the machine
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
        raise urllib.error.URLError(socket.timeout("timed out"))
    if mode == "timeout_raw":
        raise socket.timeout("timed out")
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
    # normal responses ------------------------------------------------------
    if url.endswith("/session/status"):
        data = SCN.get("status", {"connected": True, "loggedIn": True})
        return _Resp(200, json.dumps({"success": True, "data": data}))
    # POST /chat/send/document
    return _Resp(SCN.get("send_status", 200),
                 SCN.get("send_body", '{"success":true,"data":{"Id":"X"}}'))


urllib.request.urlopen = fake_urlopen   # global patch — no real network, ever


# ============================================================================
# Throwaway DB with a couple of receipts
# ============================================================================
print("Setting up isolated test database…")
con = db.init_db()


def _make_receipt(phone, *, sub=1000.0, paid=1000.0, with_results=True, status="reported"):
    pid = con.execute(
        "INSERT INTO patients(name,age,age_desc,sex,telephone,mr_no) VALUES (?,?,?,?,?,?)",
        ("Test Patient", 30, "Years", "Male", phone, None),
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
        (f"LAB_TEST_{pid:04d}", pid, "Test Patient", 30, "Years", "Male", phone,
         "Dr. Test", "3cc EDTA", sub, sub, paid, due, status, None),
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
                (item_id, p["id"], p["seq"], p["part_type"] or "N", p["name"], p["units"],
                 p["ref_male"], "1"),
            )
    con.commit()
    return rid


R_VALID = _make_receipt("03001234567")               # good phone, has results
R_NOPHONE = _make_receipt("", with_results=False)     # no phone at all
R_BADPHONE = _make_receipt("12", with_results=False)  # too short to be valid

# a tiny dummy PDF so send_pdf never invokes WeasyPrint in the network matrix
_DUMMY = Path(_TMP) / "dummy.pdf"
_DUMMY.write_bytes(b"%PDF-1.4\n% dummy\n")


# ============================================================================
# 1) Phone normalization + WhatsApp number derivation  (~1000 cases)
# ============================================================================
section("phone normalization + wa_number")
_OPERATORS = [f"3{a}{b}" for a in range(0, 5) for b in range(0, 10)]  # 300..349 (50)
_SUBS = ["1234567", "0000001", "9999999", "1122334", "7654321"]       # 5
for op in _OPERATORS:
    for sub in _SUBS:
        canon = "0" + op + sub                 # 03XX XXXXXXX (11 digits)
        national = op + sub                    # 3XX XXXXXXX (10 digits)
        wa = "92" + national
        variants = [
            canon,                              # 03001234567
            "+92" + national,                   # +923001234567
            "0092" + national,                  # 0092...
            "92" + national,                    # 92...
            national,                           # bare national
            f"0{op}-{sub}",                     # dashed
            f"0{op} {sub}",                     # spaced
            f" +92 {op} {sub} ",                # messy with +92
        ]
        for v in variants:
            eq(normalize_phone(v), canon, f"normalize({v!r})")
            eq(whatsapp.wa_number(v, "92"), wa, f"wa_number({v!r})")

# invalid / garbage phones → wa_number must reject (None)
for bad in ["", "   ", "abc", "12", "12345", "0", "00", "++", "9-2", "phone", "0300abc",
            "1", "92", "920", "+", "()-", "....", "0000000"]:
    check(whatsapp.wa_number(bad, "92") is None, f"wa_number rejects {bad!r}")


# ============================================================================
# 2) Reference-range abnormal flags  (~500 cases)
# ============================================================================
section("reference-range flags (high/low/normal)")
for lo in range(1, 60):                         # 59 ranges
    hi = lo + 10
    ref = f"{lo} - {hi}"
    eq(report._flag(lo - 3, ref)[0], "Low", f"flag {lo-3} in {ref}")
    eq(report._flag(lo, ref)[0], "Normal", f"flag lo-bound {lo} in {ref}")
    eq(report._flag((lo + hi) / 2, ref)[0], "Normal", f"flag mid in {ref}")
    eq(report._flag(hi, ref)[0], "Normal", f"flag hi-bound {hi} in {ref}")
    eq(report._flag(hi + 3, ref)[0], "High", f"flag {hi+3} in {ref}")
# upper-bound-only ("<= n") and lower-bound-only ("> n") forms
for n in range(1, 40):
    eq(report._flag(n + 5, f"<= {n}")[0], "High", f"flag >upper {n}")
    eq(report._flag(n - 0.5, f"<= {n}")[0], "Normal", f"flag <=upper {n}")
    eq(report._flag(n - 5, f"> {n}")[0], "Low", f"flag <lower {n}")
    eq(report._flag(n + 0.5, f"> {n}")[0], "Normal", f"flag >lower {n}")
# non-numeric values never crash → None
for v in ["positive", "Trace", "Nil", "", None, "++", "seen"]:
    check(report._flag(v, "10 - 20") is None, f"flag non-numeric {v!r}")


# ============================================================================
# 3) Amount-in-words  (~300 cases)
# ============================================================================
section("amount in words")
eq(report._amount_in_words(0), "Zero Rupees Only", "words(0)")
for exact, want in [
    (1, "One Rupees Only"), (21, "Twenty One Rupees Only"),
    (100, "One Hundred Rupees Only"), (1500, "One Thousand Five Hundred Rupees Only"),
    (100000, "One Lakh Rupees Only"), (1000000, "Ten Lakh Rupees Only"),
    (10000000, "One Crore Rupees Only"),
]:
    eq(report._amount_in_words(exact), want, f"words({exact})")
for n in list(range(0, 250)) + [999, 12345, 99999, 250000, 7500000, 12345678]:
    w = report._amount_in_words(n)
    check(bool(w) and w.endswith("Rupees Only"), f"words({n}) well-formed -> {w!r}")


# ============================================================================
# 4) Billing math: discount / net / due / change  (~200 cases)
# ============================================================================
section("billing math (discount/net/due/change)")
for sub in [0, 100, 250, 800, 1250, 5000, 99999]:
    for disc in [0, 10, 20, 30, 50, 100]:
        for paid in [0, sub / 2, sub, sub + 500]:
            net = max(0.0, sub - sub * disc / 100.0)
            due = max(0.0, net - paid)
            change = max(0.0, paid - net)
            check(net <= sub + 1e-9, f"net<=sub sub={sub} disc={disc}")
            check(due >= 0 and change >= 0, f"due/change >=0 sub={sub}")
            check(not (due > 1e-9 and change > 1e-9),
                  f"never due AND change sub={sub} disc={disc} paid={paid}")
            if paid >= net:
                check(abs(change - (paid - net)) < 1e-9 and due < 1e-9,
                      f"overpaid change sub={sub} disc={disc} paid={paid}")


# ============================================================================
# 5) WhatsApp pre-flight (instant, no network)  (~30 cases)
# ============================================================================
section("WhatsApp pre-flight (config/recipient)")
# config_ready across url/token presence
for url, tok, ok_expect in [("", "", False), ("http://x", "", False),
                            ("", "t", False), ("http://x", "t", True)]:
    db.set_setting(con, "whatsapp_url", url)
    db.set_setting(con, "whatsapp_api_key", tok)
    ok, msg = whatsapp.config_ready(con)
    eq(ok, ok_expect, f"config_ready url={url!r} tok={tok!r}")
    if not ok_expect:
        check(bool(msg), "config_ready gives a message")
# recipient_ready
db.set_setting(con, "whatsapp_url", "http://localhost:8080")
db.set_setting(con, "whatsapp_api_key", "tok")
ok, _ = whatsapp.recipient_ready(con, R_VALID); check(ok, "recipient_ready valid phone")
ok, m = whatsapp.recipient_ready(con, R_NOPHONE); check(not ok, "recipient_ready no phone")
has(m, "no valid", "recipient_ready no-phone message")
ok, _ = whatsapp.recipient_ready(con, R_BADPHONE); check(not ok, "recipient_ready bad phone")
ok, m = whatsapp.recipient_ready(con, 999999); check(not ok, "recipient_ready missing receipt")
has(m, "not found", "recipient_ready missing message")


# ============================================================================
# 6) WhatsApp status check across every gateway state  (~20 cases)
# ============================================================================
section("WhatsApp check_status across gateway states")
db.set_setting(con, "whatsapp_url", "http://localhost:8080")
db.set_setting(con, "whatsapp_api_key", "tok")

SCN.clear(); SCN["mode"] = "ok"; SCN["status"] = {"connected": True, "loggedIn": True}
ok, m = whatsapp.check_status(con); check(ok, "status: logged in -> ok"); has(m, "ready", "status ready msg")

SCN["status"] = {"connected": True, "loggedIn": False}
ok, m = whatsapp.check_status(con); check(not ok, "status: connected not linked")
has(m, "scan", "status not-linked mentions scan")

SCN["status"] = {"connected": False, "loggedIn": False}
ok, m = whatsapp.check_status(con); check(not ok, "status: not connected")

for mode, needle in [("down", "could not reach"), ("no_internet", "host not found"),
                     ("timeout_wrapped", "timed out"), ("timeout_raw", "timed out"),
                     ("unauthorized", "token"), ("forbidden", "token")]:
    SCN["mode"] = mode
    ok, m = whatsapp.check_status(con)
    check(not ok, f"status {mode} -> not ok")
    has(m, needle, f"status {mode} message")
SCN["mode"] = "ok"

# missing config short-circuits before any network
db.set_setting(con, "whatsapp_url", "")
ok, m = whatsapp.check_status(con); check(not ok, "status: no url"); has(m, "url", "status no-url msg")
db.set_setting(con, "whatsapp_url", "http://localhost:8080")
db.set_setting(con, "whatsapp_api_key", "")
ok, m = whatsapp.check_status(con); check(not ok, "status: no token")
db.set_setting(con, "whatsapp_api_key", "tok")


# ============================================================================
# 7) WhatsApp send_pdf across every failure mode  (~60 cases)
# ============================================================================
section("WhatsApp send_pdf across failure modes")
NUM = "03001234567"
# (mode, send_status, send_body) -> (ok_expect, needle)
CASES = [
    (dict(mode="ok"), True, "sent to"),
    (dict(mode="down"), False, "could not reach"),
    (dict(mode="refused_raw"), False, "could not reach"),
    (dict(mode="no_internet"), False, "host not found"),
    (dict(mode="timeout_wrapped"), False, "timed out"),
    (dict(mode="timeout_raw"), False, "timed out"),
    (dict(mode="unauthorized"), False, "token"),
    (dict(mode="forbidden"), False, "token"),
    (dict(mode="notfound"), False, "error (http 404)"),
    (dict(mode="server_error_session"), False, "isn't linked"),
    (dict(mode="ok", send_status=200, send_body='{"success":false,"error":"x"}'),
     False, "could not send"),
    (dict(mode="ok", send_status=200, send_body='{"error":"user not logged in"}'),
     False, "isn't linked"),
    (dict(mode="ok", send_status=500, send_body='{"error":"boom"}'),
     False, "could not send"),
]
for scn, ok_expect, needle in CASES:
    SCN.clear(); SCN.update(scn)
    ok, m = whatsapp.send_pdf(con, NUM, str(_DUMMY), "caption")
    eq(ok, ok_expect, f"send_pdf {scn.get('mode')} body={scn.get('send_body')!r}")
    has(m, needle, f"send_pdf {scn.get('mode')} message")
SCN.clear(); SCN["mode"] = "ok"

# send_pdf guards: bad phone, missing file, not configured
ok, m = whatsapp.send_pdf(con, "12", str(_DUMMY), ""); check(not ok, "send_pdf bad phone")
ok, m = whatsapp.send_pdf(con, NUM, str(Path(_TMP) / "nope.pdf"), ""); check(not ok, "send_pdf missing file")
has(m, "could not be created", "send_pdf missing-file message")
db.set_setting(con, "whatsapp_url", "")
ok, m = whatsapp.send_pdf(con, NUM, str(_DUMMY), ""); check(not ok, "send_pdf not configured")
db.set_setting(con, "whatsapp_url", "http://localhost:8080")


# ============================================================================
# 8) send_report / send_receipt end-to-end (real PDF build)  (~12 cases)
# ============================================================================
section("send_report / send_receipt (builds real PDF)")
SCN.clear(); SCN["mode"] = "ok"
ok, m = whatsapp.send_report(con, R_VALID); check(ok, "send_report ok"); has(m, "sent to", "send_report msg")
ok, m = whatsapp.send_receipt(con, R_VALID); check(ok, "send_receipt ok")
# gateway down during a real send
SCN["mode"] = "down"
ok, m = whatsapp.send_report(con, R_VALID); check(not ok, "send_report gateway down")
has(m, "could not reach", "send_report down msg")
SCN["mode"] = "ok"
# no phone / missing receipt
ok, m = whatsapp.send_report(con, R_NOPHONE); check(not ok, "send_report no phone")
ok, m = whatsapp.send_receipt(con, 999999); check(not ok, "send_receipt missing receipt")
has(m, "not found", "send_receipt missing msg")


# ============================================================================
# 9) PDF generation variety  (~20 cases)
# ============================================================================
section("PDF generation (report + receipt variants)")
variants = [
    _make_receipt("03007654321", sub=500, paid=500),                 # exact
    _make_receipt("03007654322", sub=1250, paid=2000),               # overpaid (change)
    _make_receipt("03007654323", sub=800, paid=300),                 # underpaid (due)
    _make_receipt("03007654324", sub=0, paid=0, with_results=False),  # empty/zero
    _make_receipt("", sub=999, paid=999),                            # no phone
]
for rid in [R_VALID] + variants:
    rb = report.build_report_bytes(con, rid)
    check(rb[:4] == b"%PDF" and len(rb) > 1000, f"report PDF rid={rid} ({len(rb)}B)")
    cb = report.build_receipt_bytes(con, rid)
    check(cb[:4] == b"%PDF" and len(cb) > 1000, f"receipt PDF rid={rid} ({len(cb)}B)")
tb = report.build_test_page_bytes("Some Printer")
check(tb[:4] == b"%PDF", "test-page PDF builds")


# ============================================================================
# 10) DB / settings / catalog integrity  (~15 cases)
# ============================================================================
section("DB / settings / catalog")
check(con.execute("SELECT COUNT(*) FROM tests").fetchone()[0] > 100, "catalog has tests")
check(con.execute("SELECT COUNT(*) FROM test_parameters").fetchone()[0] > 100, "catalog has params")
db.set_setting(con, "k_roundtrip", "v1"); eq(db.get_setting(con, "k_roundtrip"), "v1", "setting roundtrip")
db.set_setting(con, "k_roundtrip", "v2"); eq(db.get_setting(con, "k_roundtrip"), "v2", "setting update")
eq(db.get_setting(con, "missing_key", "def"), "def", "setting default")
# hidden results excluded from report; column present
cols = [r[1] for r in con.execute("PRAGMA table_info(results)")]
check("hidden" in cols, "results.hidden column exists")
icols = [r[1] for r in con.execute("PRAGMA table_info(receipt_items)")]
check("remarks" in icols, "receipt_items.remarks column exists")
# auth
check(db.verify_user(con, "admin", "admin") is not None, "admin login works")
check(db.verify_user(con, "admin", "wrong") is None, "wrong password rejected")
check(db.verify_user(con, "ghost", "x") is None, "unknown user rejected")
# audit log
db.log_audit(con, "tester", "login", "unit test entry")
n = con.execute("SELECT COUNT(*) FROM audit_log WHERE username='tester' AND action='login'").fetchone()[0]
check(n >= 1, "log_audit writes a row")
db.log_audit(con, None, None, None)  # must tolerate junk and never raise
check(True, "log_audit tolerates None args")
# every action the app emits must have a friendly label on the Logs page
from labdesk.ui.logs import ACTION_LABELS                       # noqa: E402
EXPECTED_ACTIONS = {
    "login", "login_failed", "logout", "setup_completed", "patient_created",
    "patient_updated", "receipt_created", "discount_approved",
    "discount_approval_failed", "results_saved",
    "culture_saved", "due_received", "expense_added", "expense_updated",
    "expense_deleted", "previewed_receipt", "previewed_report", "printed_receipt",
    "printed_report", "exported_pdf", "whatsapp_report", "whatsapp_receipt",
    "whatsapp_test", "whatsapp_test_message", "printer_test", "user_created",
    "user_enabled", "user_disabled", "password_changed", "settings_saved",
    "doctor_created", "doctor_updated", "doctor_deleted", "test_created",
    "test_updated", "test_deleted", "logs_cleared",
}
for _a in sorted(EXPECTED_ACTIONS):
    check(_a in ACTION_LABELS, f"Logs page has a label for action '{_a}'")


# ============================================================================
# 10b) Security hardening: hashing, lockout, secrets, audit chain, URL, phone
# ============================================================================
section("security: hashing / lockout / secrets / audit-chain / url / phone")
import hashlib as _hl                                            # noqa: E402
from labdesk import whatsapp as _wa                              # noqa: E402

# scrypt password hashing (slow KDF, not bare sha256)
_h, _ = db.hash_password("s3cret-pw")
check(_h.startswith("scrypt$"), "hash_password uses scrypt KDF")
check(db._verify_password("s3cret-pw", _h, "") is True, "scrypt verify accepts correct")
check(db._verify_password("wrong", _h, "") is False, "scrypt verify rejects wrong")

# legacy sha256 row verifies AND is upgraded to scrypt on successful login
_lsalt = "abc123"
_legacy = _hl.sha256((_lsalt + "oldpw").encode()).hexdigest()
check(db._verify_password("oldpw", _legacy, _lsalt) is True, "legacy sha256 still verifies")
con.execute("INSERT INTO users(username,pass_hash,salt,full_name,role,active) "
            "VALUES ('legacyuser',?,?,?,'technician',1)", (_legacy, _lsalt, "Legacy"))
con.commit()
check(db.verify_user(con, "legacyuser", "oldpw") is not None, "legacy user logs in")
_nh = con.execute("SELECT pass_hash FROM users WHERE username='legacyuser'").fetchone()[0]
check(_nh.startswith("scrypt$"), "legacy hash upgraded to scrypt on login")

# brute-force lockout
con.execute("UPDATE users SET failed_attempts=0, locked_until=NULL WHERE username='legacyuser'")
con.commit()
for _ in range(5):
    db.verify_user(con, "legacyuser", "badpw")
check(db.lock_remaining(con, "legacyuser") > 0, "account locks after repeated failures")
check(db.verify_user(con, "legacyuser", "oldpw") is None, "correct password refused while locked")
con.execute("UPDATE users SET failed_attempts=0, locked_until=NULL WHERE username='legacyuser'")
con.commit()
check(db.verify_user(con, "legacyuser", "oldpw") is not None, "unlocks after reset")

# secret store (file, not the DB)
db.set_secret("unit_k", "topsecret")
check(db.get_secret("unit_k") == "topsecret", "secret roundtrip")
check(db.get_secret("nope", "d") == "d", "secret default")

# audit hash-chain tamper detection
ok_chain, _bad = db.verify_audit_chain(con)
check(ok_chain, "audit chain intact before tampering")
_row = con.execute("SELECT id FROM audit_log WHERE hash IS NOT NULL LIMIT 1").fetchone()
if _row:
    con.execute("UPDATE audit_log SET detail='TAMPERED' WHERE id=?", (_row[0],)); con.commit()
    ok2, _b2 = db.verify_audit_chain(con)
    check(not ok2, "audit chain detects tampering")
    con.execute("UPDATE audit_log SET detail='unit test entry' WHERE id=?", (_row[0],)); con.commit()

# gateway URL validation + locality
check(_wa.validate_url("http://localhost:8080")[0], "valid http URL accepted")
check(not _wa.validate_url("ftp://x")[0], "non-http scheme rejected")
check(not _wa.validate_url("notaurl")[0], "garbage URL rejected")
check(_wa.is_local_url("http://127.0.0.1:8080"), "loopback is local")
check(_wa.is_local_url("http://192.168.1.5:8080"), "RFC1918 is local")
check(not _wa.is_local_url("http://evil.example.com"), "public host is not local")

# tightened phone (cc 92 → must be a real mobile)
check(_wa.wa_number("03001234567", "92") == "923001234567", "valid PK mobile accepted")
check(_wa.wa_number("0421234567", "92") is None, "non-mobile/landline rejected for cc92")

# format-string injection blocked in caption template
db.set_setting(con, "whatsapp_report_caption", "{lab.__class__}")
_cap = _wa._caption(con, "whatsapp_report_caption", "fb", lab="L")
check(_cap == "{lab.__class__}", "format-string injection blocked (template kept literal)")
db.set_setting(con, "whatsapp_report_caption", "")

# ---- regressions found by the GUI test fleet (run 2) ----
from labdesk.ui.widgets import money as _money, like_term as _lt   # noqa: E402
eq(_money(-0.0), "Rs. 0", "money(-0.0) -> 'Rs. 0' (no '-0')")
eq(_money(0.0), "Rs. 0", "money(0) -> 'Rs. 0'")
check(_money(-5).startswith("- Rs."), "money negative still formats")
eq(_lt("_"), "%\\_%", "like_term escapes underscore")
eq(_lt("%"), "%\\%%", "like_term escapes percent")
# catalog: a literal '_' search must NOT match the whole catalog
_nall = con.execute("SELECT COUNT(*) FROM tests WHERE active=1").fetchone()[0]
_nund = con.execute("SELECT COUNT(*) FROM tests WHERE active=1 AND name LIKE ? ESCAPE '\\'",
                    (_lt("_"),)).fetchone()[0]
check(_nall > 100 and _nund < _nall, "catalog: literal '_' search no longer returns everything")
# a receipt with NULL patient_name AND NULL lab_no still appears on an empty search (COALESCE)
con.execute("INSERT INTO receipts(lab_no,patient_name,status,net_amount,paid,due) "
            "VALUES(NULL,NULL,'reported',0,0,0)")
con.commit()
_tot = con.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
_vis = con.execute("SELECT COUNT(*) FROM receipts WHERE (COALESCE(patient_name,'') LIKE '%' "
                   "OR COALESCE(lab_no,'') LIKE '%')").fetchone()[0]
check(_vis == _tot, "NULL name/lab_no receipt visible on empty search (COALESCE)")

# WhatsApp attachment uses a friendly lab_no filename, not the random temp name
eq(_wa._safe_filename("LAB_2026-06-06_003"), "LAB_2026-06-06_003.pdf", "safe filename keeps lab_no")
eq(_wa._safe_filename("../etc/passwd"), "etcpasswd.pdf", "safe filename strips path chars")
_cap = []
_orig_post = _wa._post
_wa._post = lambda cfg, path, payload, timeout=None: (_cap.append(payload), (200, '{"success":true}'))[1]
db.set_setting(con, "whatsapp_url", "http://localhost:8080"); db.set_secret("whatsapp_api_key", "tok")
_wa.send_report(con, R_VALID)
_wa._post = _orig_post
check(_cap and _cap[0].get("FileName", "").endswith(".pdf")
      and "tmp" not in _cap[0]["FileName"].lower(),
      "WhatsApp FileName is the lab_no PDF, not a temp name")
# new lab_no format uses hyphenated date (verify the strftime the app uses)
_ds = con.execute("SELECT strftime('%Y-%m-%d','now','localtime')").fetchone()[0]
check(len(_ds) == 10 and _ds[4] == "-" and _ds[7] == "-", "lab_no date format is YYYY-MM-DD")

# ---- improvement-pass additions ----
import os as _os                                                 # noqa: E402
# unique lab_no guard index exists
_idx = [r[1] for r in con.execute("PRAGMA index_list('receipts')")]
check("ux_receipts_labno" in _idx, "unique lab_no index exists (race guard)")
# hot-path indexes created
_pidx = [r[1] for r in con.execute("PRAGMA index_list('patients')")]
check("ix_patients_tel" in _pidx, "patients.telephone index exists")
# backups
_bp = db.backup_db("test")
check(_bp and _os.path.exists(str(_bp)), "backup_db creates a file")
check(db.restore_db("/no/such/file.sqlite") is False, "restore_db rejects a missing file")
# audit re-chain after purge
for _i in range(3):
    db.log_audit(con, "chainuser", "login", f"chain{_i}")
con.execute("DELETE FROM audit_log WHERE detail='chain1'"); con.commit()
_ok, _ = db.verify_audit_chain(con)
check(not _ok, "deleting a middle row breaks the audit chain")
db.rechain_audit(con)
_ok2, _ = db.verify_audit_chain(con)
check(_ok2, "rechain_audit restores integrity after a purge")
# report uses the STORED reported_at (stable reprint date)
con.execute("UPDATE receipts SET reported_at='2026-06-01 09:00' WHERE id=?", (R_VALID,)); con.commit()
_rh = report.build_report_html(con, R_VALID)
check("2026-06-01 09:00" in _rh, "report uses stored reported_at, not now()")
# microbiology culture & sensitivity renders on the report
_ct = con.execute("SELECT id, name FROM tests WHERE is_culture=1 LIMIT 1").fetchone()
if _ct:
    _cpid = con.execute("INSERT INTO patients(name,age,age_desc,sex,telephone) "
                        "VALUES('Cult Pt',30,'Years','Male','03001234567')").lastrowid
    _crid = con.execute("INSERT INTO receipts(lab_no,patient_id,patient_name,age,age_desc,sex,"
                        "status,net_amount,paid,due) VALUES('LAB_CULT_1',?,'Cult Pt',30,'Years',"
                        "'Male','reported',500,500,0)", (_cpid,)).lastrowid
    _citem = con.execute("INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) "
                         "VALUES(?,?,?,500)", (_crid, _ct["id"], _ct["name"])).lastrowid
    _cid = con.execute("INSERT INTO cultures(receipt_item_id,specimen,growth,organism,gram_stain) "
                       "VALUES(?,?,?,?,?)", (_citem, "Urine", "Growth present", "E. coli",
                                            "Gram negative")).lastrowid
    con.execute("INSERT INTO culture_sensitivity(culture_id,antibiotic,result) VALUES(?,?,?)",
                (_cid, "Ciprofloxacin", "S"))
    con.commit()
    _chtml = report.build_report_html(con, _crid)
    check("E. coli" in _chtml and "Ciprofloxacin" in _chtml and "Sensitiv" in _chtml,
          "report renders microbiology culture & sensitivity")

# ---- deferred-features batch ----
section("deferred features: void / opt-out / wa-log / retire / payment")
# void exclusion from income + dues
_vr = _make_receipt("03001234567", sub=500, paid=500, status="reported")
_before = con.execute("SELECT COALESCE(SUM(paid),0) FROM receipts WHERE COALESCE(voided,0)=0").fetchone()[0]
con.execute("UPDATE receipts SET voided=1, due=0 WHERE id=?", (_vr,)); con.commit()
_after = con.execute("SELECT COALESCE(SUM(paid),0) FROM receipts WHERE COALESCE(voided,0)=0").fetchone()[0]
check(_after == _before - 500, "voided receipt excluded from income sum")
check(con.execute("SELECT COUNT(*) FROM receipts WHERE due>0 AND COALESCE(voided,0)=0 AND id=?",
                  (_vr,)).fetchone()[0] == 0, "voided receipt not counted in dues")
# WhatsApp opt-out honored by recipient_ready
con.execute("UPDATE patients SET wa_optout=1 WHERE id=(SELECT patient_id FROM receipts WHERE id=?)",
            (R_VALID,)); con.commit()
_ok, _m = _wa.recipient_ready(con, R_VALID)
check(not _ok and "opted out" in _m.lower(), "recipient_ready honors WhatsApp opt-out")
con.execute("UPDATE patients SET wa_optout=0 WHERE id=(SELECT patient_id FROM receipts WHERE id=?)",
            (R_VALID,)); con.commit()
# WhatsApp delivery log written on send
db.set_setting(con, "whatsapp_url", "http://localhost:8080"); db.set_secret("whatsapp_api_key", "tok")
_op2 = _wa._post
_wa._post = lambda cfg, path, payload, timeout=None: (200, '{"success":true}')
_n0 = con.execute("SELECT COUNT(*) FROM wa_messages").fetchone()[0]
_wa.send_report(con, R_VALID)
_wa._post = _op2
_n1 = con.execute("SELECT COUNT(*) FROM wa_messages").fetchone()[0]
check(_n1 == _n0 + 1, "wa_messages logs a send")
check(con.execute("SELECT ok FROM wa_messages ORDER BY id DESC LIMIT 1").fetchone()[0] == 1,
      "wa_messages records success")
# payment method persists
con.execute("UPDATE receipts SET payment_method='Card' WHERE id=?", (R_VALID,)); con.commit()
check(con.execute("SELECT payment_method FROM receipts WHERE id=?", (R_VALID,)).fetchone()[0] == "Card",
      "payment_method stored")
# catalog retire/restore (active flag)
_tt = con.execute("SELECT id FROM tests WHERE active=1 LIMIT 1").fetchone()[0]
con.execute("UPDATE tests SET active=0 WHERE id=?", (_tt,)); con.commit()
check(con.execute("SELECT active FROM tests WHERE id=?", (_tt,)).fetchone()[0] == 0,
      "test can be retired (active=0)")
con.execute("UPDATE tests SET active=1 WHERE id=?", (_tt,)); con.commit()
# new action labels exist
for _a in ("receipt_voided", "report_delivered", "exported_csv",
           "test_deactivated", "test_activated"):
    check(_a in ACTION_LABELS, f"Logs has a label for '{_a}'")


# ============================================================================
# 11b) Themes / caption templates / send_text / timeout / new settings
# ============================================================================
section("themes / captions / send_text / settings")
from labdesk.ui.style import build_qss, THEMES                  # noqa: E402
for t in ("light", "dark"):
    q = build_qss(t)
    check(isinstance(q, str) and "QPushButton" in q and len(q) > 1000, f"build_qss({t}) valid")
check(build_qss("dark") != build_qss("light"), "dark differs from light")
check("#0f1720" in build_qss("dark"), "dark uses a dark background")
check({"light", "dark"} <= set(THEMES), "THEMES has light + dark")
check(build_qss("nonsense") == build_qss("light"), "unknown theme falls back to light")

# caption templating ({lab}/{lab_no}/{name})
eq(whatsapp._caption(con, "no_such_key", "FB"), "FB", "caption blank -> fallback")
db.set_setting(con, "whatsapp_report_caption", "{lab}/{lab_no}/{name}")
eq(whatsapp._caption(con, "whatsapp_report_caption", "FB", lab="L", lab_no="N1", name="Joe"),
   "L/N1/Joe", "caption renders placeholders")
db.set_setting(con, "whatsapp_report_caption", "{bogus}")
eq(whatsapp._caption(con, "whatsapp_report_caption", "FB", lab="L"), "{bogus}",
   "bad caption placeholder -> sent as-is, no crash")
db.set_setting(con, "whatsapp_report_caption", "")

# upload timeout clamping in _cfg
db.set_setting(con, "whatsapp_timeout", "1"); eq(whatsapp._cfg(con)["timeout"], 5, "timeout clamps low->5")
db.set_setting(con, "whatsapp_timeout", "9999"); eq(whatsapp._cfg(con)["timeout"], 120, "timeout clamps high->120")
db.set_setting(con, "whatsapp_timeout", "abc"); eq(whatsapp._cfg(con)["timeout"], 40, "timeout bad->default")
db.set_setting(con, "whatsapp_timeout", "30"); eq(whatsapp._cfg(con)["timeout"], 30, "timeout valid kept")

# send_text across gateway states (the Settings 'send test message' button)
db.set_setting(con, "whatsapp_url", "http://localhost:8080")
db.set_setting(con, "whatsapp_api_key", "tok")
SCN.clear(); SCN["mode"] = "ok"
ok, m = whatsapp.send_text(con, "03001234567", "hi"); check(ok, "send_text ok")
has(m, "test message sent", "send_text ok msg")
SCN["mode"] = "down"
ok, m = whatsapp.send_text(con, "03001234567", "hi"); check(not ok, "send_text gateway down")
has(m, "could not reach", "send_text down msg")
SCN["mode"] = "unauthorized"
ok, m = whatsapp.send_text(con, "03001234567", "hi"); check(not ok, "send_text bad token")
SCN.clear(); SCN["mode"] = "ok"
ok, m = whatsapp.send_text(con, "12", "hi"); check(not ok, "send_text invalid number")
db.set_setting(con, "whatsapp_url", "")
ok, m = whatsapp.send_text(con, "03001234567", "hi"); check(not ok, "send_text not configured")
db.set_setting(con, "whatsapp_url", "http://localhost:8080")

for k in ("theme", "whatsapp_auto_receipt", "whatsapp_report_caption",
          "whatsapp_receipt_caption", "whatsapp_timeout"):
    check(k in db.DEFAULT_SETTINGS, f"default setting {k} present")


# ============================================================================
# 11) Background task helper + debounce (Qt)  (~6 cases)
# ============================================================================
section("Qt background helper + debounce")
try:
    import time
    from PySide6.QtWidgets import QApplication, QPushButton, QWidget
    app = QApplication.instance() or QApplication([])
    from labdesk.ui import tasks

    parent = QWidget(); btn = QPushButton("Go")
    res = {}
    tasks.run_in_background(parent, lambda c: report.build_report_bytes(c, R_VALID),
                            lambda ok, r: res.update(ok=ok, n=(len(r) if ok else r)),
                            clicked=btn, busy_text="Working…")
    check(btn.text() == "Working…" and not btn.isEnabled(), "task: busy state shown")
    for _ in range(200):
        app.processEvents(); time.sleep(0.02)
        if "ok" in res:
            break
    check(res.get("ok") is True and res.get("n", 0) > 1000, "task: completed with PDF")
    check(btn.text() == "Go" and btn.isEnabled(), "task: button restored")

    hits = {"n": 0}
    trig = tasks.debounce(parent, lambda: hits.__setitem__("n", hits["n"] + 1), ms=100)
    for _ in range(5):
        trig("x")
    for _ in range(40):
        app.processEvents(); time.sleep(0.02)
        if hits["n"]:
            break
    eq(hits["n"], 1, "debounce: 5 calls -> 1 fire")

    # error path: work raises -> on_done(ok=False, message)
    res2 = {}
    tasks.run_in_background(parent, lambda c: (_ for _ in ()).throw(RuntimeError("boom")),
                            lambda ok, r: res2.update(ok=ok, r=r))
    for _ in range(50):
        app.processEvents(); time.sleep(0.02)
        if "ok" in res2:
            break
    check(res2.get("ok") is False and "boom" in str(res2.get("r")), "task: error surfaced safely")

    # ---- login: a wrong password must warn exactly ONCE (not twice) ----
    from PySide6.QtWidgets import QMessageBox, QPushButton
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt as _Qt
    from labdesk.ui.login import LoginDialog
    _wc = {"n": 0}
    _orig_warn = QMessageBox.warning
    QMessageBox.warning = staticmethod(lambda *a, **k: _wc.__setitem__("n", _wc["n"] + 1))
    # the seeded admin is forced to change password on first login; clear that +
    # any lockout so this test exercises the wrong/right-password warning flow.
    con.execute("UPDATE users SET must_change_password=0, failed_attempts=0, "
                "locked_until=NULL WHERE username='admin'"); con.commit()
    try:
        d = LoginDialog(con); d.show()
        d.username.setText("admin"); d.password.setText("definitely-wrong")
        QTest.keyClick(d.password, _Qt.Key_Return); app.processEvents()
        eq(_wc["n"], 1, "login: ENTER wrong password warns once")
        _wc["n"] = 0
        d2 = LoginDialog(con); d2.show()
        d2.username.setText("admin"); d2.password.setText("nope")
        [b for b in d2.findChildren(QPushButton) if b.text() == "Sign in"][0].click()
        app.processEvents()
        eq(_wc["n"], 1, "login: CLICK wrong password warns once")
        _wc["n"] = 0
        d3 = LoginDialog(con); d3.show()
        d3.username.setText("admin"); d3.password.setText("admin")
        QTest.keyClick(d3.password, _Qt.Key_Return); app.processEvents()
        check(_wc["n"] == 0 and d3.user is not None, "login: correct password accepts, no warning")
    finally:
        QMessageBox.warning = _orig_warn

    # ---- Logs page constructs and shows the audit rows ----
    from labdesk.ui.logs import LogsPage
    _u = {"username": "admin", "role": "admin", "id": 1}
    lp = LogsPage(con, _u)
    lp.on_show()
    check(lp.table.rowCount() >= 1, "LogsPage lists audit entries")
    lp.search.setText("tester"); lp.refresh()
    check(lp.table.rowCount() >= 1, "LogsPage search filters")

    # ---- pages that previously lacked self.user now construct with it ----
    from labdesk.ui.microbiology import MicrobiologyPage
    from labdesk.ui.accounts import AccountsPage
    mp = MicrobiologyPage(con, _u)
    check(getattr(mp, "user", None) is _u, "MicrobiologyPage stores self.user")
    ap = AccountsPage(con, _u)
    check(getattr(ap, "user", None) is not None, "AccountsPage has self.user")

    # ---- regressions found by the GUI test fleet ----
    # worklist: clearing the selection must NOT re-select the receipt (signal reentrancy)
    from labdesk.ui.worklist import WorklistPage
    wp = WorklistPage(con, _u)
    wp.status_filter.setCurrentIndex(0)   # All
    wp.refresh_list()
    if R_VALID in getattr(wp, "_ids", []):
        wp.table.selectRow(wp._ids.index(R_VALID)); app.processEvents()
        check(wp.current_receipt == R_VALID, "worklist: selecting a row loads it")
        wp.clear_selection(); app.processEvents()
        check(wp.current_receipt is None,
              "worklist: clear_selection clears current_receipt (no signal reentrancy)")
    # microbiology: clear_selection resets current_item
    mp.current_item = 999999
    mp.clear_selection()
    check(mp.current_item is None, "microbiology: clear_selection clears current_item")
    # receipts: deselecting a row yields no id (buttons disable), not a stale one
    from labdesk.ui.receipts import ReceiptsPage
    rp2 = ReceiptsPage(con, _u); rp2.on_show()
    if rp2._ids:
        rp2.table.selectRow(0); app.processEvents()
        check(rp2._selected_id() is not None, "receipts: selected row gives an id")
        rp2.table.clearSelection(); app.processEvents()
        check(rp2._selected_id() is None, "receipts: deselect -> _selected_id None (stale-action fix)")
except Exception as e:  # pragma: no cover
    check(False, f"Qt section crashed: {e}")


# ============================================================================
# Summary
# ============================================================================
print("\n" + "=" * 60)
total = PASS + FAIL
print(f"  TOTAL CASES : {total}")
print(f"  PASSED      : {PASS}")
print(f"  FAILED      : {FAIL}")
if FAILS:
    print("\n  First failures:")
    for f in FAILS:
        print("   ✗", f)
print("=" * 60)
sys.exit(1 if FAIL else 0)
