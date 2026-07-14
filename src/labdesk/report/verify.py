"""Per-lab report verification code: keyed HMAC over a canonical fingerprint of the report's content."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from .. import db
from ..db import sqlite3

_SEP = "\x1f"  # unit separator, won't occur in field text
_CULT_COLS = (
    "specimen",
    "growth",
    "organism",
    "colony_count",
    "gram_stain",
    "zn_stain",
    "remarks",
)


def _verify_key(con: sqlite3.Connection) -> str:
    """The per-lab HMAC key (hex), generated once on first use and persisted."""
    key = db.get_setting(con, "report_verify_key", "")
    if not key:
        con.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES('report_verify_key', ?)",
            (secrets.token_hex(32),),
        )
        con.commit()
        key = db.get_setting(
            con, "report_verify_key", ""
        )  # another writer may have won
    return key


def report_fingerprint(
    con: sqlite3.Connection, receipt_id: int, version: str = "v2"
) -> str:
    """Canonical, reproducible serialization of a report's verifiable content. "v2" also covers per-item impression/remarks; "v1" is the legacy scheme."""
    r = con.execute(
        "SELECT lab_no, patient_name, reported_at FROM receipts WHERE id=?",
        (receipt_id,),
    ).fetchone()
    if not r:
        return ""
    parts = [
        version,
        r["lab_no"] or "",
        r["patient_name"] or "",
        r["reported_at"] or "",
    ]
    for row in con.execute(
        "SELECT name, value, hidden FROM results res "
        "JOIN receipt_items ri ON ri.id = res.receipt_item_id "
        "WHERE ri.receipt_id=? "
        "ORDER BY res.receipt_item_id, res.seq, COALESCE(res.parameter_id, -1)",
        (receipt_id,),
    ):
        parts.append(f"{row['name'] or ''}={row['value'] or ''}#{row['hidden'] or 0}")
    if version != "v1":
        for it in con.execute(
            "SELECT id, conclusion, remarks FROM receipt_items "
            "WHERE receipt_id=? ORDER BY id",
            (receipt_id,),
        ):
            c = (it["conclusion"] or "").strip()
            rm = (it["remarks"] or "").strip()
            if c or rm:
                parts.append(f"I:{it['id']}={c}#{rm}")
    for cu in con.execute(
        "SELECT cu.* FROM cultures cu JOIN receipt_items ri ON ri.id = cu.receipt_item_id "
        "WHERE ri.receipt_id=? ORDER BY cu.id",
        (receipt_id,),
    ):
        parts.append("C:" + "|".join((cu[k] or "") for k in _CULT_COLS))
        for s in con.execute(
            "SELECT antibiotic, result FROM culture_sensitivity WHERE culture_id=? ORDER BY id",
            (cu["id"],),
        ):
            parts.append(f"S:{s['antibiotic'] or ''}={s['result'] or ''}")
    return _SEP.join(parts)


def verification_code(
    con: sqlite3.Connection, receipt_id: int, version: str = "v2"
) -> str:
    """The footer code, e.g. '7F3A-9C21'. Returns '' when there's nothing to verify."""
    fp = report_fingerprint(con, receipt_id, version)
    if not fp:
        return ""
    mac = hmac.new(bytes.fromhex(_verify_key(con)), fp.encode("utf-8"), hashlib.sha256)
    h = mac.hexdigest().upper()
    return f"{h[:4]}-{h[4:8]}"


def verify(con: sqlite3.Connection, receipt_id: int, code: str) -> bool:
    """True iff `code` matches the recomputed v2 or legacy v1 code for this receipt (constant-time)."""
    given = "".join((code or "").upper().split()).replace("-", "")
    if not given:
        return False
    for version in ("v2", "v1"):
        expected = verification_code(con, receipt_id, version).replace("-", "")
        if expected and hmac.compare_digest(expected, given):
            return True
    return False
