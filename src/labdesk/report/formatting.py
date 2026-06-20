"""Low-level value formatting: escaping, method/remarks blocks, image/file URLs,
reference-range resolution, abnormal flags, date formatting and amount-in-words.

Imports only :mod:`.constants`.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

from .constants import AMBER, ARROW_DOWN, ARROW_UP, GREEN, RED, TEAL_DARK


def _esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _method_block(head) -> str:
    """The 'Method / Comments' footer for a test. One normalisation everywhere:
    collapse blank lines, then collapse runs of spaces (the two report variants
    used to differ)."""
    if not head or not head["method_note"]:
        return ""
    note = head["method_note"].replace("\r", "")
    note = re.sub(r"[ \t]*\n[ \t]*\n+", "\n", note)  # collapse blank lines
    note = re.sub(r"[ \t]{2,}", " ", note).strip()  # collapse runs of spaces
    return f"<div class='method'><b>Method / Comments:</b> {_esc(note)}</div>"


def _remarks_block(text) -> str:
    """The optional 'Remarks' box, newline → <br>. Shared by both report kinds."""
    text = (text or "").strip()
    if not text:
        return ""
    return (
        f"<div class='remarks-box'><b>Remarks:</b> "
        f"{_esc(text).replace(chr(10), '<br>')}</div>"
    )


def _file_url(p: str | Path) -> str:
    return Path(p).resolve().as_uri()


def _img(path: str, css: str = "") -> str:
    p = (path or "").strip()
    if p and Path(p).exists():
        return f'<img src="{_esc(_file_url(p))}" style="{css}">'
    return ""


# ---------------------------------------------------------------------------
# Reference range + abnormal flag (numeric)
# ---------------------------------------------------------------------------
def _resolve_ref(res, sex: str = "") -> tuple[str, str]:
    """Resolve the reference range to (display_html, flag_range).

    ``flag_range`` is the single numeric range a result is judged against. It is
    "" — meaning *no* abnormal flag — when the display shows both the M and F
    ranges (sex unknown, ranges differ), so we never flag a value against the
    wrong sex's range while showing both."""
    keys = res.keys()
    m = ((res["p_male"] if "p_male" in keys else None) or "").strip().replace("\n", " ")
    f = (
        ((res["p_female"] if "p_female" in keys else None) or "")
        .strip()
        .replace("\n", " ")
    )
    ref_text = (res["ref_text"] if "ref_text" in keys else "") or ""
    sx = (sex or "").strip().lower()
    if sx.startswith("m") and m:
        return _esc(m), m
    if sx.startswith("f") and f:
        return _esc(f), f
    if m and f and m != f:
        disp = (
            f"<span style='color:{TEAL_DARK};'>M:</span> {_esc(m)}<br>"
            f"<span style='color:{TEAL_DARK};'>F:</span> {_esc(f)}"
        )
        return disp, ""  # ambiguous — show both, flag against neither
    one = m or f
    if one:
        return _esc(one), one
    return _esc(ref_text).replace("\n", "<br>"), ref_text


def _flag(value, ref):
    """Return (label, colour) for an out-of-range numeric result, else None."""
    if value is None:
        return None
    vs = str(value).replace(",", "").strip()
    try:
        v = float(vs)
    except ValueError:
        return None
    ref = (ref or "").replace("–", "-").replace("≤", "<=").replace("≥", ">=").strip()
    # A leading operator means an open bound; resolve it BEFORE the a-b range
    # pattern so "< 200 (ideal 0-99)" is judged on <200, not the parenthetical.
    mlt = re.match(r"^<\s*=?\s*(-?\d+\.?\d*)", ref)
    if mlt:
        return ("High", RED) if v > float(mlt.group(1)) else ("Normal", GREEN)
    mgt = re.match(r"^>\s*=?\s*(-?\d+\.?\d*)", ref)
    if mgt:
        return ("Low", AMBER) if v < float(mgt.group(1)) else ("Normal", GREEN)
    m = re.search(r"(-?\d+\.?\d*)\s*-\s*(-?\d+\.?\d*)", ref)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        if v < lo:
            return ("Low", AMBER)
        if v > hi:
            return ("High", RED)
        return ("Normal", GREEN)
    m = re.search(r"<\s*=?\s*(-?\d+\.?\d*)", ref)
    if m:
        return ("High", RED) if v > float(m.group(1)) else ("Normal", GREEN)
    m = re.search(r">\s*=?\s*(-?\d+\.?\d*)", ref)
    if m:
        return ("Low", AMBER) if v < float(m.group(1)) else ("Normal", GREEN)
    return None


def _flag_arrow(value, ref):
    """(arrow, css_class) when a numeric result is out of range, else None."""
    fl = _flag(value, ref)
    if not fl:
        return None
    label = fl[0]
    if label == "High":
        return (ARROW_UP, "high")
    if label == "Low":
        return (ARROW_DOWN, "low")
    return None


def _fmt_date(iso: str) -> str:
    """ISO date → compact 'dd Mon<br>yyyy' for a result column header."""
    s = (iso or "")[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d %b<br>%Y")
    except ValueError:
        return _esc(s)


# ---------------------------------------------------------------------------
# amount in words (Pakistani numbering)
# ---------------------------------------------------------------------------
_ONES = [
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
]
_TENS = [
    "",
    "",
    "Twenty",
    "Thirty",
    "Forty",
    "Fifty",
    "Sixty",
    "Seventy",
    "Eighty",
    "Ninety",
]


def _two(n):
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + ((" " + _ONES[n % 10]) if n % 10 else "")).strip()


def _three(n):
    out = ""
    if n >= 100:
        out = _ONES[n // 100] + " Hundred"
        n %= 100
        if n:
            out += " "
    return (out + _two(n)).strip()


def _amount_in_words(amount) -> str:
    n = round(amount or 0)
    if n == 0:
        return "Zero Rupees Only"
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    if crore:
        parts.append(_two(crore) + " Crore")
    if lakh:
        parts.append(_two(lakh) + " Lakh")
    if thousand:
        parts.append(_two(thousand) + " Thousand")
    if n:
        parts.append(_three(n))
    return " ".join(parts).strip() + " Rupees Only"
