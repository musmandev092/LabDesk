"""WhatsApp delivery via a self-hosted **wuzapi** gateway
(https://github.com/asternic/wuzapi) — a free, open-source whatsmeow REST API
that can send PDF documents (unlike WAHA Core, whose file sending is paid).

Run it (one container, SQLite, no DB):
    docker run -d --name wuzapi -p 8080:8080 \
        -e WUZAPI_ADMIN_TOKEN=... -v wuzapi-data:/app/dbdata asternic/wuzapi
then create a user token and scan the QR (see app/WHATSAPP_SETUP.md).

LabDesk settings used:
    whatsapp_url           e.g. http://localhost:8080
    whatsapp_api_key       the wuzapi *user token* (sent as the `token` header)
    whatsapp_country_code  e.g. 92
Uses only the stdlib so the AppImage stays lean.
"""
from __future__ import annotations

import base64
import json
import socket
import urllib.request
import urllib.error
from pathlib import Path

from . import db
from .constants import normalize_phone

# Timeouts (seconds). Kept modest so a dead gateway fails fast instead of
# hanging. The send runs on a background thread (ui/wa.py), so these only bound
# how long until the user sees a result — they never freeze the window.
_TIMEOUT_POST = 40          # document upload (PDF base64) — generous but bounded
_TIMEOUT_GET = 8            # status / quick checks


def _cfg(con):
    return {
        "url": db.get_setting(con, "whatsapp_url", "").rstrip("/"),
        "token": db.get_setting(con, "whatsapp_api_key", ""),      # wuzapi user token
        "cc": db.get_setting(con, "whatsapp_country_code", "92") or "92",
    }


def _headers(cfg):
    # wuzapi authenticates user requests with the `token` header
    return {"Content-Type": "application/json", "token": cfg["token"]}


def _post(cfg, path, payload, timeout=_TIMEOUT_POST):
    req = urllib.request.Request(
        f"{cfg['url']}{path}", data=json.dumps(payload).encode("utf-8"),
        headers=_headers(cfg), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def _get(cfg, path, timeout=_TIMEOUT_GET):
    req = urllib.request.Request(f"{cfg['url']}{path}", headers=_headers(cfg), method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def _friendly_url_error(e) -> str:
    """Turn a low-level URLError/timeout into something a receptionist understands."""
    reason = getattr(e, "reason", e)
    text = str(reason).lower()
    if isinstance(reason, socket.timeout) or "timed out" in text:
        return ("The WhatsApp gateway is not responding (timed out). "
                "Check that it is running, then try again.")
    if isinstance(reason, ConnectionRefusedError) or "refused" in text:
        return ("Could not reach the WhatsApp gateway. Make sure it (the Docker "
                "container) is running and the Gateway URL in Settings is correct.")
    if "name or service not known" in text or "nodename nor servname" in text:
        return "The WhatsApp Gateway URL in Settings looks wrong (host not found)."
    return f"Could not reach the WhatsApp gateway: {reason}"


def wa_number(raw: str, cc: str) -> str | None:
    """Local phone → wuzapi recipient (digits, country code, no +/@), e.g.
    03001234567 → 923001234567. Returns None if the number isn't plausible."""
    local = normalize_phone(raw, cc)            # canonical 03XXXXXXXXX
    if not local:
        return None
    num = cc + local.lstrip("0")                # 92 + national
    return num if num.isdigit() and 10 <= len(num) <= 15 else None


# ---------------------------------------------------------------------------
# Instant (no-network) pre-flight checks — used by the UI before it spawns the
# background send, so the user gets immediate feedback instead of a frozen wait.
# ---------------------------------------------------------------------------
def config_ready(con) -> tuple[bool, str]:
    cfg = _cfg(con)
    if not cfg["url"]:
        return False, "WhatsApp isn't set up yet. Add the Gateway URL in Settings → WhatsApp."
    if not cfg["token"]:
        return False, "WhatsApp isn't set up yet. Add the Access token in Settings → WhatsApp."
    return True, ""


def recipient_ready(con, receipt_id: int) -> tuple[bool, str]:
    row = con.execute(
        "SELECT telephone FROM receipts WHERE id=?", (receipt_id,)
    ).fetchone()
    if not row:
        return False, "Receipt not found."
    if wa_number(row["telephone"] or "", _cfg(con)["cc"]) is None:
        return (False, "This patient has no valid WhatsApp number. "
                       "Add or correct the phone (03XXXXXXXXX) in Reception.")
    return True, ""


def check_status(con) -> tuple[bool, str]:
    cfg = _cfg(con)
    if not cfg["url"]:
        return False, "Set the WhatsApp gateway URL in Settings first."
    if not cfg["token"]:
        return False, "Set the WhatsApp access token in Settings first."
    try:
        _, body = _get(cfg, "/session/status")
        data = json.loads(body).get("data", {})
        if data.get("loggedIn"):
            return True, "Gateway reachable — WhatsApp is linked and ready."
        if data.get("connected"):
            return False, "Gateway reachable, but WhatsApp isn't linked — scan the QR code."
        return False, "Gateway reachable, but the session isn't connected. Start/scan it."
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, "Access token is wrong (gateway returned Unauthorized)."
        return False, f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:160]}"
    except urllib.error.URLError as e:
        return False, _friendly_url_error(e)
    except Exception as e:  # noqa: BLE001
        return False, f"Error: {e}"


def send_pdf(con, number: str, pdf_path: str, caption: str = "") -> tuple[bool, str]:
    cfg = _cfg(con)
    if not cfg["url"] or not cfg["token"]:
        return False, "WhatsApp isn't set up yet (Settings → WhatsApp)."
    phone = wa_number(number, cfg["cc"])
    if not phone:
        return False, "This patient has no valid WhatsApp number (03XXXXXXXXX)."
    p = Path(pdf_path)
    if not p.exists():
        return False, "The PDF could not be created, so nothing was sent."
    document = "data:application/pdf;base64," + base64.b64encode(p.read_bytes()).decode("ascii")
    payload = {
        "Phone": phone,
        "Document": document,
        "FileName": p.name,
        "Caption": caption or "Your laboratory report",
    }
    try:
        status, body = _post(cfg, "/chat/send/document", payload)
        ok = True
        try:
            ok = json.loads(body).get("success", True)
        except json.JSONDecodeError:
            pass
        if 200 <= status < 300 and ok:
            return True, f"Sent to {number} on WhatsApp."
        low = body.lower()
        if "logged in" in low or "no session" in low or "not connected" in low or "loggedin" in low:
            return False, ("WhatsApp isn't linked. Open Settings → WhatsApp → "
                           "Test connection and scan the QR code, then try again.")
        if status in (401, 403):
            return False, "Access token is wrong (Settings → WhatsApp)."
        return False, f"The gateway could not send the message (HTTP {status}). {body[:140]}"
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace").lower()
        if e.code in (401, 403):
            return False, "Access token is wrong (Settings → WhatsApp)."
        if "logged in" in detail or "session" in detail:
            return False, ("WhatsApp isn't linked. Open Settings → WhatsApp → "
                           "Test connection and scan the QR code, then try again.")
        return False, f"The gateway returned an error (HTTP {e.code})."
    except urllib.error.URLError as e:
        return False, _friendly_url_error(e)
    except Exception as e:  # noqa: BLE001
        return False, f"Could not send on WhatsApp: {e}"


def send_report(con, receipt_id: int, parent=None, *, silent: bool = False):
    """Build the report PDF for a receipt and send it to the patient. Returns (ok,msg)."""
    import tempfile
    from . import report

    r = con.execute(
        "SELECT lab_no, patient_name, telephone FROM receipts WHERE id=?", (receipt_id,)
    ).fetchone()
    if not r:
        return False, "Receipt not found."
    tmp = Path(tempfile.gettempdir()) / f"{r['lab_no'] or 'report'}.pdf"
    try:
        report.export_report_pdf(con, receipt_id, str(tmp))
    except Exception as e:  # noqa: BLE001
        return False, f"Could not build the report PDF: {e}"
    lab = db.get_setting(con, "lab_name", "")
    cap = f"{lab} — Lab report {r['lab_no']} for {r['patient_name']}".strip(" —")
    return send_pdf(con, r["telephone"] or "", str(tmp), cap)


def send_receipt(con, receipt_id: int, parent=None, *, silent: bool = False):
    """Build the cash-receipt (bill) PDF for a receipt and send it to the patient."""
    import tempfile
    from . import report

    r = con.execute(
        "SELECT lab_no, patient_name, telephone FROM receipts WHERE id=?", (receipt_id,)
    ).fetchone()
    if not r:
        return False, "Receipt not found."
    tmp = Path(tempfile.gettempdir()) / f"{(r['lab_no'] or 'receipt')}-bill.pdf"
    try:
        report.export_receipt_pdf(con, receipt_id, str(tmp))
    except Exception as e:  # noqa: BLE001
        return False, f"Could not build the receipt PDF: {e}"
    lab = db.get_setting(con, "lab_name", "")
    cap = f"{lab} — Cash receipt {r['lab_no']} for {r['patient_name']}".strip(" —")
    return send_pdf(con, r["telephone"] or "", str(tmp), cap)
