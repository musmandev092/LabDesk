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
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path

from . import db
from .constants import normalize_phone

# Timeouts (seconds). Kept modest so a dead gateway fails fast instead of
# hanging. The send runs on a background thread (ui/wa.py), so these only bound
# how long until the user sees a result — they never freeze the window.
_TIMEOUT_POST = 40  # document upload (PDF base64) — generous but bounded
_TIMEOUT_GET = 8  # status / quick checks


def _cfg(con):
    try:
        timeout = int(float(db.get_setting(con, "whatsapp_timeout", "") or _TIMEOUT_POST))
    except (TypeError, ValueError, OverflowError):
        # OverflowError: int(float('inf')) — a user typed 'inf' in the timeout field.
        timeout = _TIMEOUT_POST
    timeout = max(5, min(timeout, 120))  # keep it sane (5-120s)
    return {
        "url": db.get_setting(con, "whatsapp_url", "").rstrip("/"),
        # token lives in the 0600 secret file (not the DB); fall back to a legacy
        # DB value so existing installs keep working until the next Settings save.
        "token": db.get_secret("whatsapp_api_key") or db.get_setting(con, "whatsapp_api_key", ""),
        "cc": db.get_setting(con, "whatsapp_country_code", "92") or "92",
        "timeout": timeout,
    }


def _caption(con, key: str, fallback: str, **vals) -> str:
    """Render a caption template (with {lab}/{lab_no}/{name}); blank -> fallback."""
    tpl = (db.get_setting(con, key, "") or "").strip()
    if not tpl:
        return fallback
    # Plain placeholder substitution — NOT str.format (which would let a crafted
    # template reach object internals, e.g. {lab.__class__}). Only the known
    # whole tokens are replaced.
    out = tpl
    for k, v in vals.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def _headers(cfg):
    # wuzapi authenticates user requests with the `token` header
    return {"Content-Type": "application/json", "token": cfg["token"]}


class _NoCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse a redirect that changes host (or downgrades https→http).

    The gateway request carries the auth token and a base64 patient PDF; a
    redirect to another host would silently exfiltrate both. Same-host (and
    http→https upgrade) redirects are still followed normally."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        import urllib.parse

        o = urllib.parse.urlparse(req.full_url)
        n = urllib.parse.urlparse(newurl)
        same_host = (n.hostname or "").lower() == (o.hostname or "").lower()
        downgrade = o.scheme == "https" and n.scheme != "https"
        if not same_host or downgrade:
            raise urllib.error.HTTPError(
                req.full_url,
                code,
                "Gateway tried to redirect to a different host — blocked to "
                "protect your access token and patient data.",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Install as the process default so urllib.request.urlopen routes through it: a
# redirect to another host then can't leak the token/PDF. (We still CALL urlopen
# by name so it stays patchable/mockable.)
urllib.request.install_opener(urllib.request.build_opener(_NoCrossHostRedirect))


def _post(cfg, path, payload, timeout=None):
    ok, why = validate_url(cfg["url"])
    if not ok:
        raise ValueError(why)
    req = urllib.request.Request(
        f"{cfg['url']}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(cfg),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout or cfg.get("timeout", _TIMEOUT_POST)) as r:
        return r.status, r.read().decode("utf-8", "replace")


def _get(cfg, path, timeout=_TIMEOUT_GET):
    ok, why = validate_url(cfg["url"])
    if not ok:
        raise ValueError(why)
    req = urllib.request.Request(f"{cfg['url']}{path}", headers=_headers(cfg), method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def _friendly_url_error(e) -> str:
    """Turn a low-level URLError/timeout into something a receptionist understands."""
    reason = getattr(e, "reason", e)
    text = str(reason).lower()
    if isinstance(reason, socket.timeout) or "timed out" in text:
        return (
            "The WhatsApp gateway is not responding (timed out). "
            "Check that it is running, then try again."
        )
    if isinstance(reason, ConnectionRefusedError) or "refused" in text:
        return (
            "Could not reach the WhatsApp gateway. Make sure it (the Docker "
            "container) is running and the Gateway URL in Settings is correct."
        )
    if "name or service not known" in text or "nodename nor servname" in text:
        return "The WhatsApp Gateway URL in Settings looks wrong (host not found)."
    return f"Could not reach the WhatsApp gateway: {reason}"


def validate_url(url: str) -> tuple[bool, str]:
    """Sanity-check a gateway URL: must be http/https with a host. Guards against
    pasting garbage or an exfiltration URL into Settings."""
    import urllib.parse

    try:
        p = urllib.parse.urlparse((url or "").strip())
    except ValueError:
        return False, "That gateway URL is not valid."
    if p.scheme not in ("http", "https"):
        return False, "Gateway URL must start with http:// or https://"
    if not p.hostname:
        return False, "Gateway URL is missing a host (e.g. http://localhost:8080)."
    return True, ""


def is_loopback_url(url: str) -> bool:
    """True only for strict loopback (localhost/127.0.0.1/::1) — the single case
    where plain http carries no on-the-wire exposure (it never leaves the box).
    Used to decide whether to warn about unencrypted http transport."""
    import urllib.parse

    try:
        host = (urllib.parse.urlparse(url or "").hostname or "").lower()
    except ValueError:
        return False  # malformed bracket/IPv6 host → not loopback (fail safe)
    return host in ("localhost", "127.0.0.1", "::1")


def is_local_url(url: str) -> bool:
    """True if the URL points at loopback or a private (RFC1918) address — the
    intended self-hosted deployment. Non-local hosts get a warning before sending."""
    import ipaddress
    import urllib.parse

    try:
        host = (urllib.parse.urlparse(url or "").hostname or "").lower()
    except ValueError:
        return False  # malformed bracket/IPv6 host → treat as non-local (warn)
    if host in ("localhost", "127.0.0.1", "::1", ""):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or ip.is_private
    except ValueError:
        return False  # a hostname we can't resolve here → treat as non-local


def wa_number(raw: str, cc: str) -> str | None:
    """Local phone → wuzapi recipient (digits, country code, no +/@), e.g.
    03001234567 → 923001234567. Returns None if the number isn't plausible."""
    local = normalize_phone(raw, cc)  # canonical 03XXXXXXXXX
    if not local:
        return None
    national = local.lstrip("0")  # drop the leading 0
    num = cc + national  # 92 + national
    if not num.isdigit():
        return None
    if cc == "92":
        # Pakistan mobile: national is exactly 3XXXXXXXXX (10 digits) — reject
        # malformed/landline/wrong-length numbers so reports don't mis-send.
        return num if re.fullmatch(r"3\d{9}", national) else None
    return num if 9 <= len(national) <= 13 else None


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
        "SELECT r.telephone, p.wa_optout FROM receipts r "
        "LEFT JOIN patients p ON p.id = r.patient_id WHERE r.id=?",
        (receipt_id,),
    ).fetchone()
    if not row:
        return False, "Receipt not found."
    if "wa_optout" in row.keys() and row["wa_optout"]:
        return False, (
            "This patient hasn't agreed to receive WhatsApp messages " "(enable it in Reception)."
        )
    if wa_number(row["telephone"] or "", _cfg(con)["cc"]) is None:
        return (
            False,
            "This patient has no valid WhatsApp number. "
            "Add or correct the phone (03XXXXXXXXX) in Reception.",
        )
    return True, ""


def _log_wa(con, receipt_id, kind, number, filename, ok, message) -> None:
    """Record a WhatsApp send attempt in the delivery log (best-effort)."""
    try:
        con.execute(
            "INSERT INTO wa_messages(receipt_id,kind,number,filename,ok,message) "
            "VALUES (?,?,?,?,?,?)",
            (receipt_id, kind, number, filename, 1 if ok else 0, (message or "")[:200]),
        )
        con.commit()
    except Exception:
        pass


def check_status(con) -> tuple[bool, str]:
    cfg = _cfg(con)
    if not cfg["url"]:
        return False, "Set the WhatsApp gateway URL in Settings first."
    if not cfg["token"]:
        return False, "Set the WhatsApp access token in Settings first."
    ok, why = validate_url(cfg["url"])
    if not ok:
        return False, why
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
        return False, f"The gateway returned an error (HTTP {e.code})."
    except urllib.error.URLError as e:
        return False, _friendly_url_error(e)
    except OSError as e:  # raw socket timeout / connection / DNS errors (no internet)
        return False, _friendly_url_error(e)
    except Exception as e:
        return False, f"Error: {e}"


def _safe_filename(name: str, fallback: str = "report") -> str:
    """A friendly, filesystem-safe PDF name for the WhatsApp attachment."""
    base = "".join(c for c in (name or "") if c.isalnum() or c in "-_") or fallback
    return base + ".pdf"


def send_pdf(
    con, number: str, pdf_path: str, caption: str = "", filename: str = ""
) -> tuple[bool, str]:
    cfg = _cfg(con)
    if not cfg["url"] or not cfg["token"]:
        return False, "WhatsApp isn't set up yet (Settings → WhatsApp)."
    ok, why = validate_url(cfg["url"])
    if not ok:
        return False, why
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
        # show a meaningful name to the recipient, not the random temp filename
        "FileName": filename or p.name,
        "Caption": caption or "Your laboratory report",
    }
    try:
        status, body = _post(cfg, "/chat/send/document", payload)
        # Prefer the gateway's authoritative JSON fields over scanning the raw
        # body for English phrases — a changed/spoofed gateway could otherwise
        # make a failed send read as success (or vice-versa) via crafted text.
        j = None
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                j = parsed
        except json.JSONDecodeError:
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
        if success is None:
            # No authoritative JSON signal. Trust a 2xx ONLY if the reply was
            # valid JSON (a genuine gateway response); a 2xx with an opaque text
            # body is treated as UNCONFIRMED rather than assumed-delivered.
            if 200 <= status < 300 and not not_linked:
                success = True if j is not None else None
            else:
                success = False
        if success is True and 200 <= status < 300:
            return True, f"Sent to {number} on WhatsApp."
        if not_linked:
            return False, (
                "WhatsApp isn't linked. Open Settings → WhatsApp → "
                "Test connection and scan the QR code, then try again."
            )
        if status in (401, 403):
            return False, "Access token is wrong (Settings → WhatsApp)."
        if success is None:
            return False, (
                "The gateway accepted the upload but did not confirm "
                "delivery — please check the patient's WhatsApp before "
                "relying on this."
            )
        return False, f"The gateway could not send the message (HTTP {status})."
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace").lower()
        if e.code in (401, 403):
            return False, "Access token is wrong (Settings → WhatsApp)."
        if "logged in" in detail or "session" in detail:
            return False, (
                "WhatsApp isn't linked. Open Settings → WhatsApp → "
                "Test connection and scan the QR code, then try again."
            )
        return False, f"The gateway returned an error (HTTP {e.code})."
    except urllib.error.URLError as e:
        return False, _friendly_url_error(e)
    except OSError as e:  # raw socket timeout / connection / DNS errors (no internet)
        return False, _friendly_url_error(e)
    except Exception as e:
        return False, f"Could not send on WhatsApp: {e}"


def _send_built_pdf(con, receipt_id, build_fn, caption_key, label, fname_suffix=""):
    """Build a PDF into a private 0600 temp file, send it, and always delete it
    (no patient-PII residue in a shared/world-readable temp dir)."""
    import os
    import tempfile

    from . import report

    r = con.execute(
        "SELECT lab_no, patient_name, telephone FROM receipts WHERE id=?", (receipt_id,)
    ).fetchone()
    if not r:
        return False, "Receipt not found."
    fd, tmp = tempfile.mkstemp(suffix=".pdf")  # mode 0600, unpredictable name
    os.close(fd)
    try:
        try:
            getattr(report, build_fn)(con, receipt_id, tmp)
        except Exception as e:
            return False, f"Could not build the {label} PDF: {e}"
        lab = db.get_setting(con, "lab_name", "")
        cap = _caption(
            con,
            caption_key,
            f"{lab} — {label.capitalize()} {r['lab_no']} for {r['patient_name']}".strip(" —"),
            lab=lab,
            lab_no=r["lab_no"] or "",
            name=r["patient_name"] or "",
        )
        fname = _safe_filename((r["lab_no"] or label) + fname_suffix, label)
        ok, msg = send_pdf(con, r["telephone"] or "", tmp, cap, filename=fname)
        _log_wa(
            con,
            receipt_id,
            "receipt" if "receipt" in build_fn else "report",
            r["telephone"] or "",
            fname,
            ok,
            msg,
        )
        return ok, msg
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def send_report(con, receipt_id: int, parent=None, *, silent: bool = False):
    """Build the report PDF for a receipt and send it to the patient. Returns (ok,msg)."""
    return _send_built_pdf(
        con, receipt_id, "export_report_pdf", "whatsapp_report_caption", "lab report"
    )


def send_receipt(con, receipt_id: int, parent=None, *, silent: bool = False):
    """Build the cash-receipt (bill) PDF for a receipt and send it to the patient."""
    return _send_built_pdf(
        con,
        receipt_id,
        "export_receipt_pdf",
        "whatsapp_receipt_caption",
        "cash receipt",
        fname_suffix="-receipt",
    )


def send_text(con, raw_number: str, text: str) -> tuple[bool, str]:
    """Send a plain WhatsApp text message (used by the Settings 'send test' button)."""
    cfg = _cfg(con)
    if not cfg["url"] or not cfg["token"]:
        return False, "WhatsApp isn't set up yet (Settings → WhatsApp)."
    ok, why = validate_url(cfg["url"])
    if not ok:
        return False, why
    phone = wa_number(raw_number, cfg["cc"])
    if not phone:
        return False, "Enter a valid number (03XXXXXXXXX) to send a test to."
    try:
        status, body = _post(cfg, "/chat/send/text", {"Phone": phone, "Body": text})
        # Prefer the gateway's JSON verdict over scanning the raw body for phrases
        # (a changed/spoofed gateway could otherwise fake success/failure).
        j = None
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                j = parsed
        except json.JSONDecodeError:
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
        if success is None and 200 <= status < 300 and not not_linked:
            success = True if j is not None else None
        if success is True and 200 <= status < 300:
            return True, f"Test message sent to {raw_number}."
        if not_linked:
            return False, (
                "WhatsApp isn't linked. Open Settings → WhatsApp → "
                "Test connection and scan the QR code, then try again."
            )
        if status in (401, 403):
            return False, "Access token is wrong (Settings → WhatsApp)."
        if success is None:
            return False, (
                "The gateway accepted the request but did not confirm "
                "it was sent — please check before relying on this."
            )
        return False, f"The gateway could not send the message (HTTP {status})."
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, "Access token is wrong (Settings → WhatsApp)."
        return False, f"The gateway returned an error (HTTP {e.code})."
    except urllib.error.URLError as e:
        return False, _friendly_url_error(e)
    except OSError as e:
        return False, _friendly_url_error(e)
    except Exception as e:
        return False, f"Could not send on WhatsApp: {e}"
