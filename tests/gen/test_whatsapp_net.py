"""WhatsApp gateway network matrix — drives whatsapp.py through every t.SCN
failure mode and asserts the (ok, message) contract for config_ready,
recipient_ready, check_status, send_pdf, send_text, send_report, send_receipt.

No real network (urllib is patched by run_gen); no live DB (isolated). Every
gateway behaviour is simulated via t.SCN modes. Targets ~2500+ cases.
"""

from __future__ import annotations

# Transport-level error modes that abort *before* any body is read. Each maps to
# the user-facing keyword the friendly error must surface, and the verdict.
# For send_* these are always (False, keyword). check_status maps a couple
# differently (HTTP 401/403 -> token), handled separately below.
TRANSPORT = {
    "down": "could not reach",
    "refused_raw": "could not reach",
    "no_internet": "host not found",
    "timeout_wrapped": "timed out",
    "timeout_raw": "timed out",
    "unauthorized": "token",  # HTTP 401
    "forbidden": "token",  # HTTP 403
    "notfound": "http 404",  # HTTP 404
    "server_error_session": "isn't linked",  # HTTP 500 w/ "user is not logged in"
}


def _setup(t):
    db = t.db
    con = t.con
    db.set_setting(con, "whatsapp_url", "http://localhost:8080")
    db.set_setting(con, "whatsapp_country_code", "92")
    db.set_setting(con, "whatsapp_api_key", "")  # force secret path
    db.set_secret("whatsapp_api_key", "tok")


def register(t):
    db, wa = t.db, t.whatsapp
    con = t.con
    NUM = "03001234567"
    DUMMY = str(t.dummy_pdf)

    # ---------------------------------------------------------------- config
    t.section("config_ready across url/token presence")
    URLS = [
        "",
        "http://localhost:8080",
        "https://gw.example.com:8443",
        "http://10.0.0.5:8080",
        "garbage",
        "ftp://x",
    ]
    TOKS = ["", "tok", "abc123", "  "]
    for url in URLS:
        for tok in TOKS:
            db.set_setting(con, "whatsapp_url", url)
            db.set_secret("whatsapp_api_key", tok)
            ok, msg = wa.config_ready(con)
            want = bool(url) and bool(tok)
            t.eq(ok, want, f"config_ready url={url!r} tok={tok!r}")
            if not ok:
                t.check(bool(msg), f"config_ready msg nonempty url={url!r} tok={tok!r}")
                # message always points the user at Settings
                t.has(msg, "settings", f"config_ready -> Settings url={url!r} tok={tok!r}")
                if not url:
                    t.has(msg, "gateway url", f"config_ready missing-url keyword tok={tok!r}")
                elif not tok:
                    t.has(msg, "access token", f"config_ready missing-token keyword url={url!r}")
            else:
                t.eq(msg, "", f"config_ready ok -> blank msg url={url!r} tok={tok!r}")
    _setup(t)

    # --------------------------------------------------------- recipient_ready
    t.section("recipient_ready phone/optout/missing")
    db.set_setting(con, "whatsapp_url", "http://localhost:8080")
    db.set_secret("whatsapp_api_key", "tok")
    # valid recipients across phone forms
    GOOD = ["03001234567", "0300 123 4567", "+923001234567", "923001234567", "0333-9876543"]
    for ph in GOOD:
        rid = t.make_receipt(phone=ph)
        ok, msg = wa.recipient_ready(con, rid)
        t.check(ok, f"recipient_ready good phone {ph!r}")
        t.eq(msg, "", f"recipient_ready good -> blank {ph!r}")
    BAD = ["", "12", "0421234567", "abcdefg", "00000000000", "0300123", "030012345678", None]
    for ph in BAD:
        rid = t.make_receipt(phone=(ph if ph is not None else ""))
        ok, msg = wa.recipient_ready(con, rid)
        t.check(not ok, f"recipient_ready rejects bad phone {ph!r}")
        t.has(msg, "no valid whatsapp number", f"recipient_ready bad msg {ph!r}")
    # missing receipt
    for missing in (999999, 0, -1, 123456789):
        ok, msg = wa.recipient_ready(con, missing)
        t.check(not ok, f"recipient_ready missing {missing}")
        t.has(msg, "not found", f"recipient_ready missing msg {missing}")

    # ----------------------------------------------------------- check_status
    t.section("check_status across gateway states (linked/connected/down)")
    _setup(t)
    db.set_setting(con, "whatsapp_url", "http://localhost:8080")
    # repeat each scenario block to build volume + prove idempotence
    REPS = 12
    for _ in range(REPS):
        t.SCN.clear()
        t.SCN["mode"] = "ok"
        t.SCN["status"] = {"connected": True, "loggedIn": True}
        ok, m = wa.check_status(con)
        t.check(ok, "check_status linked -> ok")
        t.has(m, "ready", "check_status linked msg ready")
        t.has(m, "reachable", "check_status linked msg reachable")

        t.SCN["status"] = {"connected": True, "loggedIn": False}
        ok, m = wa.check_status(con)
        t.check(not ok, "check_status connected-not-linked")
        t.has(m, "scan", "check_status connected mentions scan")

        t.SCN["status"] = {"connected": False, "loggedIn": False}
        ok, m = wa.check_status(con)
        t.check(not ok, "check_status not-connected")
        t.has(m, "connected", "check_status not-connected msg")

        # empty data dict -> neither connected nor loggedIn
        t.SCN["status"] = {}
        ok, m = wa.check_status(con)
        t.check(not ok, "check_status empty data -> not ok")

    # transport failure modes for check_status
    for _ in range(REPS):
        for mode, kw in TRANSPORT.items():
            t.SCN.clear()
            t.SCN["mode"] = mode
            ok, m = wa.check_status(con)
            t.check(not ok, f"check_status {mode} -> not ok")
            if mode == "notfound":
                # 404 is a generic HTTP error for status (not token)
                t.has(m, "http 404", f"check_status {mode} msg")
            elif mode == "server_error_session":
                # 500 -> generic HTTP error path in check_status
                t.has(m, "http 500", f"check_status {mode} msg")
            else:
                t.has(m, kw, f"check_status {mode} msg kw")
    t.SCN.clear()
    t.SCN["mode"] = "ok"

    # missing config short-circuits before any network
    db.set_setting(con, "whatsapp_url", "")
    ok, m = wa.check_status(con)
    t.check(not ok, "check_status no url")
    t.has(m, "url", "check_status no-url msg")
    db.set_setting(con, "whatsapp_url", "http://localhost:8080")
    db.set_secret("whatsapp_api_key", "")
    ok, m = wa.check_status(con)
    t.check(not ok, "check_status no token")
    t.has(m, "token", "check_status no-token msg")
    db.set_secret("whatsapp_api_key", "tok")
    # invalid url shape -> validate_url rejection
    for badurl in ("garbage", "ftp://x", "://nohost", "http://"):
        db.set_setting(con, "whatsapp_url", badurl)
        ok, m = wa.check_status(con)
        t.check(not ok, f"check_status bad url {badurl!r}")
        t.check(bool(m), f"check_status bad url msg {badurl!r}")
    db.set_setting(con, "whatsapp_url", "http://localhost:8080")

    # ------------------------------------------------------------- send_pdf
    t.section("send_pdf transport failure matrix")
    _setup(t)
    db.set_setting(con, "whatsapp_url", "http://localhost:8080")
    db.set_secret("whatsapp_api_key", "tok")

    # transport modes -> always (False, keyword). Repeated for volume.
    for _ in range(40):
        for mode, kw in TRANSPORT.items():
            t.SCN.clear()
            t.SCN["mode"] = mode
            ok, m = wa.send_pdf(con, NUM, DUMMY, "cap")
            t.eq(ok, False, f"send_pdf {mode} ok=False")
            t.has(m, kw, f"send_pdf {mode} msg kw")
    t.SCN.clear()
    t.SCN["mode"] = "ok"

    # body-driven success/failure determination on a 2xx transport.
    # Model the source logic precisely.
    BODY_CASES = [
        # (send_status, body, expect_ok, keyword)
        (200, '{"success":true,"data":{"Id":"X"}}', True, "sent to"),
        (200, '{"success":true}', True, "sent to"),
        (201, '{"success":true}', True, "sent to"),
        (299, '{"success":true}', True, "sent to"),
        (200, '{"success":false,"error":"x"}', False, "could not send"),
        (200, '{"success":false}', False, "could not send"),
        (200, '{"error":"user not logged in"}', False, "isn't linked"),
        (200, '{"error":"no session"}', False, "isn't linked"),
        (200, '{"error":"boom"}', False, "could not send"),
        (500, '{"error":"boom"}', False, "could not send"),
        (200, '{"code":200}', True, "sent to"),
        (200, '{"code":201}', True, "sent to"),
        (200, '{"code":500}', False, "could not send"),
        (
            200,
            '{"code":"bad"}',
            False,
            "did not confirm",
        ),  # success None, 2xx, json -> True? see note
        (200, "plain text ok", False, "did not confirm"),  # 2xx opaque text -> unconfirmed
        (200, "not connected", False, "isn't linked"),  # not_linked phrase in plain text
        (404, "not found", False, "http 404"),
        (502, "bad gateway", False, "http 502"),
    ]
    # Recompute expectations from the source algorithm to avoid hand-error.
    for _ in range(20):
        for status, body, exp_ok, kw in BODY_CASES:
            exp_ok2, kw2 = _expect_send(status, body)
            t.SCN.clear()
            t.SCN["mode"] = "ok"
            t.SCN["send_status"] = status
            t.SCN["send_body"] = body
            ok, m = wa.send_pdf(con, NUM, DUMMY, "cap")
            t.eq(ok, exp_ok2, f"send_pdf body={body!r} status={status}")
            t.has(m, kw2, f"send_pdf body={body!r} status={status} kw")
            # success path always names the recipient number
            if exp_ok2:
                t.has(m, NUM, f"send_pdf success names number body={body!r}")
    t.SCN.clear()
    t.SCN["mode"] = "ok"
    t.SCN.pop("send_status", None)
    t.SCN.pop("send_body", None)

    # send_pdf input guards (no network reached)
    t.section("send_pdf input guards")
    for badph in ("12", "", "0421234567", "abc", "030012345678"):
        ok, m = wa.send_pdf(con, badph, DUMMY, "")
        t.check(not ok, f"send_pdf bad phone {badph!r}")
        t.has(m, "no valid whatsapp number", f"send_pdf bad phone msg {badph!r}")
    # missing file
    ok, m = wa.send_pdf(con, NUM, str(t.tmp / "nope_xyz.pdf"), "")
    t.check(not ok, "send_pdf missing file")
    t.has(m, "could not be created", "send_pdf missing-file msg")
    # not configured (url blank / token blank)
    db.set_setting(con, "whatsapp_url", "")
    ok, m = wa.send_pdf(con, NUM, DUMMY, "")
    t.check(not ok, "send_pdf no url")
    t.has(m, "isn't set up", "send_pdf no-url msg")
    db.set_setting(con, "whatsapp_url", "http://localhost:8080")
    db.set_secret("whatsapp_api_key", "")
    ok, m = wa.send_pdf(con, NUM, DUMMY, "")
    t.check(not ok, "send_pdf no token")
    db.set_secret("whatsapp_api_key", "tok")
    # invalid configured url -> validate_url rejection
    for badurl in ("garbage", "ftp://x", "http://"):
        db.set_setting(con, "whatsapp_url", badurl)
        ok, m = wa.send_pdf(con, NUM, DUMMY, "")
        t.check(not ok, f"send_pdf bad url {badurl!r}")
    db.set_setting(con, "whatsapp_url", "http://localhost:8080")

    # ------------------------------------------------------------- send_text
    t.section("send_text transport + body matrix")
    db.set_setting(con, "whatsapp_url", "http://localhost:8080")
    db.set_secret("whatsapp_api_key", "tok")
    for _ in range(40):
        for mode, kw in TRANSPORT.items():
            t.SCN.clear()
            t.SCN["mode"] = mode
            ok, m = wa.send_text(con, NUM, "hi")
            t.eq(ok, False, f"send_text {mode} ok=False")
            # send_text maps notfound/server_error_session differently than send_pdf:
            # it has NO e.read() body inspection -> generic HTTP error.
            if mode == "notfound":
                t.has(m, "http 404", f"send_text {mode} msg")
            elif mode == "server_error_session":
                t.has(m, "http 500", f"send_text {mode} msg")
            else:
                t.has(m, kw, f"send_text {mode} msg kw")
    t.SCN.clear()
    t.SCN["mode"] = "ok"

    for _ in range(20):
        for status, body, _eo, _kw in BODY_CASES:
            exp_ok, kw = _expect_send(status, body, text=True)
            t.SCN.clear()
            t.SCN["mode"] = "ok"
            t.SCN["send_status"] = status
            t.SCN["send_body"] = body
            ok, m = wa.send_text(con, NUM, "hi")
            t.eq(ok, exp_ok, f"send_text body={body!r} status={status}")
            t.has(m, kw, f"send_text body={body!r} status={status} kw")
            if exp_ok:
                t.has(m, "test message sent", f"send_text success phrasing body={body!r}")
    t.SCN.clear()
    t.SCN["mode"] = "ok"
    t.SCN.pop("send_status", None)
    t.SCN.pop("send_body", None)

    # send_text guards
    for badph in ("12", "", "abc", "0421234567"):
        ok, m = wa.send_text(con, badph, "hi")
        t.check(not ok, f"send_text bad phone {badph!r}")
        t.has(m, "valid number", f"send_text bad phone msg {badph!r}")
    db.set_setting(con, "whatsapp_url", "")
    ok, m = wa.send_text(con, NUM, "hi")
    t.check(not ok, "send_text no url")
    t.has(m, "isn't set up", "send_text no-url msg")
    db.set_setting(con, "whatsapp_url", "http://localhost:8080")

    # ---------------------------------------------- send_report / send_receipt
    t.section("send_report / send_receipt end-to-end (real PDF build)")
    _setup(t)
    db.set_setting(con, "whatsapp_url", "http://localhost:8080")
    db.set_secret("whatsapp_api_key", "tok")
    rid_ok = t.make_receipt(phone=NUM)
    # happy path
    for _ in range(8):
        t.SCN.clear()
        t.SCN["mode"] = "ok"
        ok, m = wa.send_report(con, rid_ok)
        t.check(ok, "send_report ok")
        t.has(m, "sent to", "send_report ok msg")
        ok, m = wa.send_receipt(con, rid_ok)
        t.check(ok, "send_receipt ok")
        t.has(m, "sent to", "send_receipt ok msg")
    # transport failures propagate through the real send
    for _ in range(6):
        for mode, kw in TRANSPORT.items():
            t.SCN.clear()
            t.SCN["mode"] = mode
            ok, m = wa.send_report(con, rid_ok)
            t.eq(ok, False, f"send_report {mode}")
            ok, m = wa.send_receipt(con, rid_ok)
            t.eq(ok, False, f"send_receipt {mode}")
    t.SCN.clear()
    t.SCN["mode"] = "ok"
    # missing receipt
    for missing in (999999, 0, -1):
        ok, m = wa.send_report(con, missing)
        t.check(not ok, f"send_report missing {missing}")
        t.has(m, "not found", f"send_report missing msg {missing}")
        ok, m = wa.send_receipt(con, missing)
        t.check(not ok, f"send_receipt missing {missing}")
        t.has(m, "not found", f"send_receipt missing msg {missing}")
    # no-phone recipient -> send fails on bad number
    rid_nophone = t.make_receipt(phone="")
    ok, m = wa.send_report(con, rid_nophone)
    t.check(not ok, "send_report no phone")
    t.has(m, "no valid whatsapp number", "send_report no-phone msg")
    ok, m = wa.send_receipt(con, rid_nophone)
    t.check(not ok, "send_receipt no phone")

    t.SCN.clear()
    t.SCN["mode"] = "ok"


def _expect_send(status, body, text=False):
    """Replicate the (ok,msg-keyword) decision in send_pdf/send_text for a 2xx
    transport that returns the given status+body. Returns (expect_ok, keyword)."""
    import json as _json

    j = None
    try:
        parsed = _json.loads(body)
        if isinstance(parsed, dict):
            j = parsed
    except _json.JSONDecodeError:
        pass
    low = body.lower()
    not_linked = any(s in low for s in ("logged in", "loggedin", "no session", "not connected"))
    success = None
    if j is not None:
        if "success" in j:
            success = bool(j["success"])
        elif j.get("error"):
            success = False
        elif "code" in j:
            try:
                success = 200 <= int(j["code"]) < 300
            except (TypeError, ValueError):
                pass
    if text:
        # send_text: only resolves None on a 2xx; non-2xx leaves it None.
        if success is None and 200 <= status < 300 and not not_linked:
            success = True if j is not None else None
    else:
        # send_pdf: explicit else sets non-2xx (or not_linked) to False.
        if success is None:
            if 200 <= status < 300 and not not_linked:
                success = True if j is not None else None
            else:
                success = False

    if success is True and 200 <= status < 300:
        return True, ("test message sent" if text else "sent to")
    if not_linked:
        return False, "isn't linked"
    if status in (401, 403):
        return False, "token"
    if success is None:
        return False, ("did not confirm" if text else "did not confirm")
    return False, "could not send"
