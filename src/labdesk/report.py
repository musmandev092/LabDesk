"""Report & receipt generation — full HTML/CSS rendered to PDF by WeasyPrint.

The two documents follow the supplied design mockups exactly (modern CSS: a
branded letterhead, a rounded boxed patient card, a teal cumulative results
table with a highlighted CURRENT column and inline ↑/↓ flags for the lab
report; a slate "CASH RECEIPT" with an amount-in-words box and a totals panel
for the bill). Inter is bundled (assets/fonts/Inter.ttf) so it renders the same
offline. Printing rasterises the WeasyPrint PDF onto the chosen QPrinter.
"""
from __future__ import annotations

import contextlib
import html
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

import weasyprint

from . import db

# ---------------------------------------------------------------------------
# palette — matches the supplied design mockups
# ---------------------------------------------------------------------------
TEAL = "#005f73"          # report --brand-primary
TEAL_DARK = "#004d5c"     # highlighted CURRENT column
ACCENT = "#0a9396"        # report departments line
SLATE = "#005f73"         # receipt --brand-primary
BLUE = "#0a9396"          # receipt --brand-accent
GREEN = "#059669"
AMBER = "#d97706"         # below range ↓
RED = "#dc2626"           # above range ↑
BODY = "#1e293b"

ARROW_UP = "↑"            # above reference range (High)
ARROW_DOWN = "↓"          # below reference range (Low)

ASSETS = Path(__file__).with_name("assets")
INTER_TTF = ASSETS / "fonts" / "Inter.ttf"


def _esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _method_block(head) -> str:
    """The 'Method / Comments' footer for a test. One normalisation everywhere:
    collapse blank lines, then collapse runs of spaces (the two report variants
    used to differ)."""
    if not head or not head["method_note"]:
        return ""
    note = head["method_note"].replace("\r", "")
    note = re.sub(r"[ \t]*\n[ \t]*\n+", "\n", note)   # collapse blank lines
    note = re.sub(r"[ \t]{2,}", " ", note).strip()    # collapse runs of spaces
    return f"<div class='method'><b>Method / Comments:</b> {_esc(note)}</div>"


def _remarks_block(text) -> str:
    """The optional 'Remarks' box, newline → <br>. Shared by both report kinds."""
    text = (text or "").strip()
    if not text:
        return ""
    return (f"<div class='remarks-box'><b>Remarks:</b> "
            f"{_esc(text).replace(chr(10), '<br>')}</div>")


def _file_url(p: str | Path) -> str:
    return Path(p).resolve().as_uri()


def _img(path: str, css: str = "") -> str:
    p = (path or "").strip()
    if p and Path(p).exists():
        return f'<img src="{_esc(_file_url(p))}" style="{css}">'
    return ""


def _g(con):
    return lambda k, d="": db.get_setting(con, k, d)


def _user_display(con, username: str) -> str:
    """Show the staff member's full name (falling back to the username) so the
    receipt reads 'Registered by: Farhan Ali', not 'admin'."""
    username = (username or "").strip()
    if not username:
        return ""
    row = con.execute(
        "SELECT full_name FROM users WHERE username=?", (username,)
    ).fetchone()
    full = (row["full_name"] if row and row["full_name"] else "").strip()
    return full or username


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
    f = ((res["p_female"] if "p_female" in keys else None) or "").strip().replace("\n", " ")
    ref_text = (res["ref_text"] if "ref_text" in keys else "") or ""
    sx = (sex or "").strip().lower()
    if sx.startswith("m") and m:
        return _esc(m), m
    if sx.startswith("f") and f:
        return _esc(f), f
    if m and f and m != f:
        disp = (f"<span style='color:{TEAL_DARK};'>M:</span> {_esc(m)}<br>"
                f"<span style='color:{TEAL_DARK};'>F:</span> {_esc(f)}")
        return disp, ""          # ambiguous — show both, flag against neither
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
_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
         "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
         "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


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


# ---------------------------------------------------------------------------
# Shared header data
# ---------------------------------------------------------------------------
def _contacts(g) -> str:
    return " | ".join(x for x in [
        f"Ph: {_esc(g('phone'))}" if g("phone") else "",
        f"Mob: {_esc(g('mobile'))}" if g("mobile") else "",
        _esc(g("email")) if g("email") else "",
    ] if x)


def _regs(g) -> str:
    return " | ".join(x for x in [
        f"PHC Reg #: {_esc(g('phc_reg_no'))}" if g("phc_reg_no") else "",
        f"Lab Reg #: {_esc(g('lab_reg_no'))}" if g("lab_reg_no") else "",
    ] if x)


def _patient_pairs(r):
    title = (r["title"] + " ") if ("title" in r.keys() and r["title"]) else ""
    mr = r["mr_no"] if "mr_no" in r.keys() else ""
    lab = r["lab_no"] or (r["case_no"] if "case_no" in r.keys() else "")
    age_sex = f"{r['age']} {r['age_desc']} / {r['sex']}"
    received = (r["received_at"] or "")[:16]
    # use the stored reporting date so reprints/resends keep the original date
    rep_raw = (r["reported_at"] if "reported_at" in r.keys() and r["reported_at"] else "")
    reported = rep_raw[:16] if rep_raw else datetime.now().strftime("%Y-%m-%d %H:%M")
    return [
        ("Patient Name", title + (r["patient_name"] or "")),
        ("Lab No.", lab),
        ("Registration Date", received),
        ("Specimen", r["specimen"]),
        ("Age / Sex", age_sex),
        ("MR No.", mr),
        ("Referred By", r["dr_name"]),
        ("Reporting Date", reported),
    ]


def _patient_card(r) -> str:
    cells = "".join(
        f'<div class="ig"><span class="l">{_esc(lbl)}</span>'
        f'<span class="v">{_esc(val) if val else "—"}</span></div>'
        for lbl, val in _patient_pairs(r)
    )
    return f'<div class="patient-card">{cells}</div>'


# ---------------------------------------------------------------------------
# Cumulative history (previous results for the same patient & test)
# ---------------------------------------------------------------------------
def _history_for_item(con, item, receipt):
    """Up to 4 previous visits' results for the SAME patient & SAME test, oldest
    first. Patients matched on MR No (the cross-visit "same no"); falls back to
    patient_id. Returns (date_labels, [ {parameter_id: value}, … ])."""
    rk = receipt.keys()
    mr = (receipt["mr_no"] if "mr_no" in rk else None) or ""
    pid = receipt["patient_id"] if "patient_id" in rk else None
    received = receipt["received_at"] or ""
    rid = receipt["id"]
    conds, params = [], []
    if mr.strip():
        conds.append("rc.mr_no = ?"); params.append(mr)
    if pid is not None:
        conds.append("rc.patient_id = ?"); params.append(pid)
    if not conds:
        return [], []
    q = (f"""SELECT ri.id AS item_id, rc.received_at AS dt
             FROM receipt_items ri JOIN receipts rc ON rc.id = ri.receipt_id
             WHERE ri.test_id = ? AND rc.id != ? AND ({' OR '.join(conds)})
               AND (rc.received_at < ? OR (rc.received_at = ? AND rc.id < ?))
             ORDER BY rc.received_at DESC, rc.id DESC LIMIT 4""")
    rows = con.execute(q, [item["test_id"], rid, *params, received, received, rid]).fetchall()
    rows = list(reversed(rows))  # oldest → newest, left to right
    labels, maps = [], []
    for row in rows:
        vals = con.execute(
            "SELECT parameter_id, value FROM results WHERE receipt_item_id=?",
            (row["item_id"],),
        ).fetchall()
        maps.append({v["parameter_id"]: v["value"] for v in vals if v["value"]})
        labels.append((row["dt"] or "")[:10])
    return labels, maps


def _value_cell(value, ref, *, current=False):
    if not value:
        # no result entered → a clear placeholder rather than a blank cell
        return '<td style="color:#94a3b8;">—</td>'
    arrow = _flag_arrow(value, ref)
    cls = f' class="{arrow[1]}"' if arrow else ""
    arr = f' {arrow[0]}' if arrow else ""
    style = ' style="font-size:1.1em;"' if current else ""
    return f"<td{cls}{style}>{_esc(value)}{arr}</td>"


def _report_section(con, item, sex, receipt) -> str:
    """One test: teal title bar + the cumulative results table."""
    results = con.execute(
        """SELECT res.*, tp.ref_male AS p_male, tp.ref_female AS p_female
           FROM results res LEFT JOIN test_parameters tp ON tp.id = res.parameter_id
           WHERE res.receipt_item_id=? ORDER BY res.seq""",
        (item["id"],),
    ).fetchall()
    head = con.execute(
        "SELECT report_head, method_note FROM tests WHERE id=?", (item["test_id"],)
    ).fetchone()
    title = (head["report_head"] if head and head["report_head"] else item["test_name"]).title()
    hist_labels, hist_maps = _history_for_item(con, item, receipt)
    ncols = 3 + len(hist_labels) + 1

    prev_ths = "".join(f"<th>{_fmt_date(l)}</th>" for l in hist_labels)
    cur_date = _fmt_date((receipt["received_at"] or "")[:10])
    thead = (f"<tr><th class='test'>Test</th><th>Reference Range</th><th>Unit</th>"
             f"{prev_ths}<th class='cur'>Current<br>"
             f"<span style='font-weight:400;font-size:.85em;'>{cur_date}</span></th></tr>")

    rows = []
    for res in results:
        if "hidden" in res.keys() and res["hidden"]:
            continue  # parameter unticked in the entry screen → omit from the report
        if (res["part_type"] or "N").upper() == "H":
            rows.append(f"<tr class='subhead'><td colspan='{ncols}'>{_esc(res['name'])}</td></tr>")
            continue
        name = (res["name"] or "").strip()
        val = (str(res["value"]).strip() if res["value"] is not None else "")
        if not name and not val:
            continue  # skip blank filler rows (legacy padding parameters)
        ref_disp, ref_flag = _resolve_ref(res, sex)
        pid = res["parameter_id"] if "parameter_id" in res.keys() else None
        prev = "".join(_value_cell(m.get(pid), ref_flag) for m in hist_maps)
        cur = _value_cell(res["value"], ref_flag, current=True)
        rows.append(
            f"<tr><td class='test'>{_esc(res['name'])}</td>"
            f"<td class='ref'>{ref_disp}</td>"
            f"<td class='unit'>{_esc(res['units'])}</td>{prev}{cur}</tr>"
        )
    if not rows:
        rows.append(f"<tr><td colspan='{ncols}' style='color:#999;'><i>No result entered.</i></td></tr>")

    method = _method_block(head)
    remarks = _remarks_block(item["remarks"] if "remarks" in item.keys() else "")

    return (f"<div class='title-bar'>{_esc(title)}</div>"
            f"<table class='report'><thead>{thead}</thead><tbody>{''.join(rows)}</tbody></table>"
            f"{remarks}{method}")


def _culture_section(con, item) -> str:
    """Microbiology Culture & Sensitivity block for a culture test."""
    head = con.execute(
        "SELECT report_head, method_note FROM tests WHERE id=?", (item["test_id"],)
    ).fetchone()
    title = (head["report_head"] if head and head["report_head"] else item["test_name"]).title()
    cur = con.execute(
        "SELECT * FROM cultures WHERE receipt_item_id=? ORDER BY id DESC LIMIT 1", (item["id"],)
    ).fetchone()
    if not cur:
        return (f"<div class='title-bar'>{_esc(title)}</div>"
                "<table class='report'><tbody><tr><td style='color:#999;'>"
                "<i>No culture result entered.</i></td></tr></tbody></table>")
    findings = []
    for label, val in (("Specimen", cur["specimen"]), ("Growth", cur["growth"]),
                       ("Organism", cur["organism"]), ("Colony count", cur["colony_count"]),
                       ("Gram stain", cur["gram_stain"]), ("ZN stain", cur["zn_stain"])):
        if val:
            findings.append(
                f"<tr><td class='test' style='width:30%;'>{_esc(label)}</td>"
                f"<td style='text-align:left;'>{_esc(val)}</td></tr>")
    findings_tbl = (f"<table class='report'><tbody>{''.join(findings)}</tbody></table>"
                    if findings else "")

    sens = con.execute(
        "SELECT antibiotic, result FROM culture_sensitivity WHERE culture_id=? ORDER BY antibiotic",
        (cur["id"],),
    ).fetchall()
    sens_tbl = ""
    if sens:
        colour = {"S": GREEN, "I": AMBER, "R": RED}
        full = {"S": "Sensitive", "I": "Intermediate", "R": "Resistant"}
        rows = "".join(
            f"<tr><td class='test' style='text-align:left;'>{_esc(s['antibiotic'])}</td>"
            f"<td style='color:{colour.get((s['result'] or '').upper(), BODY)};font-weight:700;'>"
            f"{_esc((s['result'] or '').upper())} — {full.get((s['result'] or '').upper(), '')}</td></tr>"
            for s in sens
        )
        sens_tbl = (
            "<table class='report' style='margin-top:3mm;'><thead><tr>"
            "<th class='test'>Antibiotic</th><th>Sensitivity</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>")

    rk = item.keys()
    rem_txt = ((item["remarks"] if "remarks" in rk else "") or "").strip() or \
              ((cur["remarks"] or "").strip() if "remarks" in cur.keys() else "")
    remarks = _remarks_block(rem_txt)
    method = _method_block(head)
    return (f"<div class='title-bar'>{_esc(title)}</div>"
            f"{findings_tbl}{sens_tbl}{remarks}{method}")


def _signatures(con) -> str:
    g = _g(con)
    sigs = [(g(f"signatory_{i}_name"), g(f"signatory_{i}_title")) for i in (1, 2)]
    sigs = [(n, t) for n, t in sigs if n]
    if not sigs:
        return ""
    blocks = "".join(
        f"<div class='sig'><div class='line'>{_esc(n)}</div><div class='t'>{_esc(t)}</div></div>"
        for n, t in sigs
    )
    return f"<div class='sigs'>{blocks}</div>"


# ---------------------------------------------------------------------------
# CSS (colours inlined; only the Inter font URL is injected)
# ---------------------------------------------------------------------------
def _font_face() -> str:
    if INTER_TTF.exists():
        return (f"@font-face{{font-family:'Inter';src:url('{_file_url(INTER_TTF)}');"
                "font-weight:100 900;font-style:normal;}")
    return ""


_REPORT_CSS = """
*{box-sizing:border-box;margin:0;padding:0;}
/* The full letterhead + patient card repeat on EVERY page (running header);
   signatures + footer line + dept band repeat on every page (running footer).
   Each test starts on its own page. Top/bottom margins reserve the running
   blocks' height. */
@page{size:A4;margin:57mm 8mm 27mm 8mm;
  @top-center{content:element(rhead);}
  @bottom-center{content:element(rfoot);}
  @bottom-right{content:"Page " counter(page) " of " counter(pages);
    font-size:7pt;color:#94a3b8;vertical-align:bottom;}}
body{font-family:'Inter',sans-serif;color:#1e293b;font-size:9pt;line-height:1.3;}

/* ---- running header (letterhead + patient card) ---- */
.rhead{position:running(rhead);width:194mm;}
.letterhead{display:flex;justify-content:space-between;align-items:center;
  border-bottom:2px solid #005f73;padding-bottom:2.5mm;}
.brand{display:flex;align-items:center;}
.brand img{height:64px;margin-right:4mm;}
.clinic h1{font-size:17pt;font-weight:700;color:#005f73;letter-spacing:-.5px;line-height:1.05;}
.clinic .dept{font-size:8pt;color:#0a9396;font-weight:600;text-transform:uppercase;letter-spacing:.4px;}
.clinic p{font-size:7.3pt;color:#64748b;line-height:1.25;}
.topright{text-align:right;}
.topright img{height:40px;margin-bottom:1mm;}
.topright .reg{font-size:7.3pt;color:#64748b;}
.patient-card{background:#f8fafc;border:1px solid #cbd5e1;border-radius:5px;
  padding:2.4mm 5mm;margin-top:3mm;display:grid;grid-template-columns:repeat(4,1fr);gap:1.6mm 4mm;}
.ig{display:flex;flex-direction:column;}
.ig .l{font-size:6.6pt;text-transform:uppercase;color:#64748b;font-weight:600;}
.ig .v{font-size:8.4pt;font-weight:600;color:#1e293b;}

/* ---- running footer (signatures + footer line + dept band) ----
   kept narrower than the page so the bottom-right "Page x of y" margin box
   never overlaps the centred footer band. */
.rfoot{position:running(rfoot);width:160mm;margin:0 auto;}
.sigs{display:flex;justify-content:space-around;margin-bottom:1.5mm;}
.sig{text-align:center;min-width:40%;}
.sig .line{border-top:1px solid #1e293b;padding-top:1mm;font-weight:700;font-size:8.5pt;}
.sig .t{font-size:7.3pt;color:#64748b;}
.fline{text-align:center;font-size:7.3pt;color:#64748b;border-top:1px solid #cbd5e1;padding-top:1.5mm;}
.band{text-align:center;font-size:7.3pt;font-weight:700;color:#005f73;letter-spacing:.3px;margin-top:1mm;}

/* ---- one test per page ---- */
.section{break-before:page;}
.section.first{break-before:auto;}
.title-bar{background:#005f73;color:#fff;padding:2mm 4mm;font-size:11pt;font-weight:600;
  border-radius:4px 4px 0 0;break-after:avoid;}
table.report{width:100%;border-collapse:collapse;font-size:8.6pt;line-height:1.15;}
table.report th,table.report td{border:1px solid #cbd5e1;padding:1.2mm 2mm;text-align:center;}
table.report th{background:#005f73;color:#fff;font-size:7pt;text-transform:uppercase;
  font-weight:600;border-color:#004d5c;}
table.report thead{display:table-header-group;}
table.report th.cur{background:#004d5c;}
table.report th.test,table.report td.test{text-align:left;width:26%;}
table.report td{font-weight:600;}
table.report td.test{font-weight:500;}
table.report td.ref,table.report td.unit{color:#64748b;font-size:7.8pt;font-weight:400;}
table.report tbody tr:nth-child(even){background:#f8fafc;}
table.report tr{break-inside:avoid;}
table.report tr.subhead td{background:#e6eff1;color:#004d5c;font-weight:700;text-align:left;}
.high{color:#dc2626;}.low{color:#d97706;}
.method{font-size:7.5pt;color:#64748b;line-height:1.25;margin-top:2.5mm;}
.remarks-box{font-size:8pt;color:#1e293b;line-height:1.3;margin-top:2.5mm;
  padding:2mm 3mm;background:#f8fafc;border-left:3px solid #0a9396;border-radius:3px;}
"""

_RECEIPT_CSS = """
*{box-sizing:border-box;margin:0;padding:0;}
@page{size:A4;margin:8mm 8mm 14mm 8mm;
  @bottom-center{content:element(rfoot);}}
body{font-family:'Inter',sans-serif;color:#1e293b;font-size:10pt;line-height:1.5;}
.header{display:flex;justify-content:space-between;align-items:center;
  border-bottom:2px solid #005f73;padding-bottom:5mm;margin-bottom:7mm;}
.brand{display:flex;align-items:center;}
.brand img{height:62px;margin-right:4mm;}
.clinic h1{font-size:16pt;font-weight:700;color:#005f73;letter-spacing:-.5px;line-height:1.1;}
.clinic .dept{font-size:8.5pt;color:#0a9396;font-weight:600;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px;}
.clinic p{font-size:8.5pt;color:#64748b;line-height:1.4;}
.rtitle{text-align:right;}
.rtitle h2{font-size:13pt;font-weight:700;color:#005f73;text-transform:uppercase;letter-spacing:1px;}
.rtitle .meta{font-size:9pt;color:#64748b;}
.patient-card{background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;
  padding:5mm 6mm;margin-bottom:7mm;display:grid;grid-template-columns:repeat(4,1fr);gap:4mm 6mm;}
.ig{display:flex;flex-direction:column;}
.ig .l{font-size:7.5pt;text-transform:uppercase;color:#64748b;font-weight:600;}
.ig .v{font-size:9.5pt;font-weight:600;color:#1e293b;}
table.items{width:100%;border-collapse:collapse;margin-bottom:7mm;}
table.items th{border-bottom:2px solid #005f73;color:#005f73;font-size:8.5pt;
  font-weight:700;text-transform:uppercase;padding:3mm 2mm;text-align:left;}
table.items td{padding:3mm 2mm;border-bottom:1px solid #e2e8f0;font-size:10pt;}
.tc{text-align:center;}.tr{text-align:right;}
.summary{display:flex;justify-content:space-between;align-items:flex-start;}
.notes{width:55%;padding-right:10mm;}
.words{font-size:9.5pt;background:#f8fafc;padding:4mm;border-radius:4px;
  border-left:3px solid #0a9396;margin-bottom:6mm;}
.remarks{font-size:8.5pt;color:#64748b;line-height:1.5;}
.totals{width:45%;}
table.tot{width:100%;border-collapse:collapse;}
table.tot td{padding:2.4mm 2mm;font-size:10pt;}
table.tot .lbl{color:#64748b;}
table.tot .val{text-align:right;font-weight:600;}
table.tot .net td{border-top:1px solid #cbd5e1;border-bottom:1px solid #cbd5e1;
  padding:3.4mm 2mm;font-size:11pt;font-weight:700;color:#005f73;}
.rfoot{position:running(rfoot);width:194mm;border-collapse:collapse;
  padding-top:3mm;border-top:1px solid #e2e8f0;font-size:8pt;color:#64748b;}
.rfoot td{padding:0;}
"""


def _doc(css_body: str, body: str) -> str:
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
            f"{_font_face()}{css_body}</style></head><body>{body}</body></html>")


# ---------------------------------------------------------------------------
# Lab report
# ---------------------------------------------------------------------------
def build_report_html(con, receipt_id: int) -> str:
    r = con.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
    items = con.execute(
        "SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY id", (receipt_id,)
    ).fetchall()
    g = _g(con)
    sex = r["sex"]
    # ---- running header: letterhead (2 logos) + patient card ----
    main_logo = _img(g("logo_path"), "height:64px;margin-right:4mm;")
    sec_logo = _img(g("accred_logo_1"), "height:40px;")
    dept = (f"<div class='dept'>{_esc(g('lab_subtitle'))}</div>") if g("lab_subtitle") else ""
    regs = _regs(g)
    topright = ""
    if sec_logo or regs:
        reg_html = f"<div class='reg'>{regs}</div>" if regs else ""
        topright = f"<div class='topright'>{sec_logo}{reg_html}</div>"
    letterhead = (
        f"<div class='letterhead'><div class='brand'>{main_logo}<div class='clinic'>"
        f"<h1>{_esc(g('lab_name'))}</h1>{dept}"
        f"<p>{_esc(g('address'))}<br>{_contacts(g)}</p></div></div>{topright}</div>"
    )
    rhead = f"<div class='rhead'>{letterhead}{_patient_card(r)}</div>"
    # ---- running footer: signatures + footer line + dept band ----
    fline = g("report_footer")
    band = g("dept_band")
    rfoot = (
        f"<div class='rfoot'>{_signatures(con)}"
        f"{('<div class=fline>' + _esc(fline) + '</div>') if fline else ''}"
        f"{('<div class=band>' + _esc(band) + '</div>') if band else ''}</div>"
    )
    # ---- one test per page ----
    blocks = []
    for i, it in enumerate(items):
        cls = "section first" if i == 0 else "section"
        tc = con.execute("SELECT is_culture FROM tests WHERE id=?", (it["test_id"],)).fetchone()
        if tc and tc["is_culture"]:
            body = _culture_section(con, it)
        else:
            body = _report_section(con, it, sex, r)
        blocks.append(f"<div class='{cls}'>{body}</div>")
    if not blocks:
        blocks.append("<p style='color:#999;'>No tests on this receipt.</p>")
    return _doc(_REPORT_CSS, rhead + rfoot + "".join(blocks))


# ---------------------------------------------------------------------------
# Cash receipt
# ---------------------------------------------------------------------------
def build_receipt_html(con, receipt_id: int) -> str:
    r = con.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
    items = con.execute(
        "SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY id", (receipt_id,)
    ).fetchall()
    g = _g(con)
    cur = g("currency", "Rs.")
    # normalise money once: a NULL column must render as 0.00, never crash :,.2f
    subtotal = r["subtotal"] or 0
    net = r["net_amount"] or 0
    paid = r["paid"] or 0
    due = r["due"] or 0
    discount = subtotal - net
    reg_by = _user_display(con, r["created_by"] if "created_by" in r.keys() else "")
    year = (r["received_at"] or "")[:4] or datetime.now().strftime("%Y")
    due_col = RED if due else GREEN
    # change handed back when the customer overpaid (paid > net)
    change = max(0.0, paid - net)

    logo = _img(g("logo_path"))
    dept = (f"<div class='dept'>{_esc(g('lab_subtitle'))}</div>") if g("lab_subtitle") else ""
    addr = "<br>".join(x for x in [_esc(g("address")), _contacts(g), _regs(g)] if x)
    header = (
        f"<div class='header'><div class='brand'>{logo}<div class='clinic'>"
        f"<h1>{_esc(g('lab_name'))}</h1>{dept}<p>{addr}</p></div></div>"
        f"<div class='rtitle'><h2>Cash Receipt</h2>"
        f"<div class='meta'><b>Date:</b> {_esc((r['received_at'] or '')[:16])}"
        f"{('<br><b>Registered by:</b> ' + _esc(reg_by)) if reg_by else ''}</div></div></div>"
    )
    rows = "".join(
        f"<tr><td class='tc'>{i+1}</td><td>{_esc(it['test_name'])}</td>"
        f"<td class='tr'>{(it['charge'] or 0):,.2f}</td></tr>"
        for i, it in enumerate(items)
    )
    items_table = (
        f"<table class='items'><thead><tr><th class='tc' style='width:8%'>Sr.</th>"
        f"<th>Test Description</th><th class='tr' style='width:22%'>Rate ({_esc(cur)})</th></tr>"
        f"</thead><tbody>{rows}</tbody></table>"
    )
    summary = (
        f"<div class='summary'><div class='notes'>"
        f"<div class='words'><b>Amount in words:</b><br><i>{_esc(_amount_in_words(net))}</i></div>"
        f"<div class='remarks'><b>Remarks:</b><br>Please present this receipt to collect your report. "
        f"Reports are issued strictly following final verification and signature by the consultant pathologist.</div>"
        f"</div><div class='totals'><table class='tot'>"
        f"<tr><td class='lbl'>Total:</td><td class='val'>{subtotal:,.2f}</td></tr>"
        f"<tr><td class='lbl'>Discount:</td><td class='val'>{discount:,.2f}</td></tr>"
        f"<tr class='net'><td>To Be Paid:</td><td class='val'>{_esc(cur)} {net:,.2f}</td></tr>"
        f"<tr><td class='lbl'>Paid:</td><td class='val'>{paid:,.2f}</td></tr>"
        f"<tr><td class='lbl' style='color:{due_col};'>Balance:</td>"
        f"<td class='val' style='color:{due_col};'>{_esc(cur)} {due:,.2f}</td></tr>"
        + (f"<tr><td class='lbl' style='color:{GREEN};'>Change returned:</td>"
           f"<td class='val' style='color:{GREEN};'>{_esc(cur)} {change:,.2f}</td></tr>"
           if change > 0 else "")
        + "</table></div></div>"
    )
    footer = (
        f"<table class='rfoot'><tr><td>{_esc(g('lab_name'))} © {_esc(year)}</td>"
        f"<td style='text-align:right;'><i>Computer-generated document. No signature required.</i></td>"
        f"</tr></table>"
    )
    body = footer + header + _patient_card(r) + items_table + summary
    return _doc(_RECEIPT_CSS, body)


# ---------------------------------------------------------------------------
# Output — WeasyPrint PDF + raster-to-printer
# ---------------------------------------------------------------------------
def _pdf_bytes(html_text: str) -> bytes:
    return weasyprint.HTML(string=html_text, base_url=str(ASSETS)).write_pdf()


def export_pdf(html_text: str, path: str) -> None:
    """Render a prepared HTML document to a PDF file."""
    Path(path).write_bytes(_pdf_bytes(html_text))


def export_report_pdf(con, receipt_id: int, path: str) -> None:
    Path(path).write_bytes(_pdf_bytes(build_report_html(con, receipt_id)))


def export_receipt_pdf(con, receipt_id: int, path: str) -> None:
    Path(path).write_bytes(_pdf_bytes(build_receipt_html(con, receipt_id)))


# Build the PDF bytes — the slow (~1-2s) WeasyPrint step. These are safe to run
# on a background thread (see ui/tasks.py); the resulting bytes are then printed
# or previewed on the UI thread.
def build_report_bytes(con, receipt_id: int) -> bytes:
    return _pdf_bytes(build_report_html(con, receipt_id))


def build_receipt_bytes(con, receipt_id: int) -> bytes:
    return _pdf_bytes(build_receipt_html(con, receipt_id))


def build_test_page_bytes(printer_name: str = "") -> bytes:
    """A small printer-test page, as PDF bytes."""
    when = datetime.now().strftime("%d %b %Y %H:%M")
    target = printer_name or "Ask each time (print dialog)"
    body = (
        f"<div style='border:2px solid #005f73;border-radius:8px;padding:24px;margin:24px;'>"
        f"<h1 style='color:#005f73;margin:0 0 8px;'>LabDesk — Printer Test</h1>"
        f"<p style='font-size:12pt;'>If you can read this, your printer is working.</p>"
        f"<p style='color:#64748b;'>Printer: <b>{_esc(target)}</b><br>{_esc(when)}</p>"
        f"<p style='color:#005f73;font-size:13pt;font-weight:700;'>✓ ↑ ↓ Rs. 1,234.50</p>"
        f"</div>"
    )
    return _pdf_bytes(_doc("body{font-family:'Inter',sans-serif;color:#1e293b;}", body))


# Cap the raster DPI when sending to a hardware printer. At QPrinter's native
# 1200 dpi an A4 page is ~10000x14000 px (~7 MB JPEG) — printing to a PDF
# printer then yields 5-20 MB files. 200 dpi is crisp for text and ~50x smaller.
_PRINT_DPI = 200


def print_bytes(pdf: bytes, parent, title: str, printer_name: str = "") -> None:
    """Print already-built PDF bytes. MUST run on the UI thread (QPrinter/QPainter
    are not thread-safe) — callers build the bytes on a worker first (ui/tasks.py),
    then call this in the completion callback.

    If `printer_name` is set (a configured default printer), send straight to it —
    no dialog. Otherwise show the print dialog. Printing *to a PDF file* hands back
    the WeasyPrint vector PDF (tiny, sharp); a real printer gets each page
    rasterised at a sane DPI (not QPrinter's 1200)."""
    from PySide6.QtCore import QSize, QRectF
    from PySide6.QtGui import QPainter, QPageSize
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPrintSupport import QPrinter, QPrintDialog, QPrinterInfo

    printer = QPrinter(QPrinter.HighResolution)
    printer.setPageSize(QPageSize(QPageSize.A4))
    printer.setFullPage(True)
    # a configured default printer that still exists → print directly, no dialog
    have_default = bool(printer_name) and printer_name in QPrinterInfo.availablePrinterNames()
    if have_default:
        printer.setPrinterName(printer_name)
    else:
        dlg = QPrintDialog(printer, parent)
        dlg.setWindowTitle(title)
        if not dlg.exec():
            return
    # "Print to File (PDF)" → just write the vector PDF; no rasterising.
    if printer.outputFormat() == QPrinter.PdfFormat and printer.outputFileName():
        Path(printer.outputFileName()).write_bytes(pdf)
        return
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")  # 0600
    with os.fdopen(fd, "wb") as f:
        f.write(pdf)
    try:
        doc = QPdfDocument(parent)
        doc.load(tmp_path)
        dpi = min(printer.resolution(), _PRINT_DPI)
        painter = QPainter(printer)
        page_rect = printer.pageRect(QPrinter.DevicePixel)
        for i in range(doc.pageCount()):
            if i:
                printer.newPage()
            pt = doc.pagePointSize(i)
            w = max(1, int(pt.width() / 72.0 * dpi))
            h = max(1, int(pt.height() / 72.0 * dpi))
            img = doc.render(i, QSize(w, h))
            painter.drawImage(QRectF(page_rect), img)
        painter.end()
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)               # don't leave patient-PII PDF in temp


def print_report(con, receipt_id: int, parent=None) -> None:
    """Synchronous convenience (builds + prints on the caller's thread). UI code
    should build bytes on a worker then call print_bytes — see ui/tasks.py."""
    print_bytes(build_report_bytes(con, receipt_id), parent, "Print Report",
                db.get_setting(con, "default_printer", ""))


def print_receipt(con, receipt_id: int, parent=None) -> None:
    print_bytes(build_receipt_bytes(con, receipt_id), parent, "Print Receipt",
                db.get_setting(con, "default_printer", ""))


def print_test_page(parent=None, printer_name: str = "") -> None:
    """Print a small test page to verify the printer works (synchronous)."""
    print_bytes(build_test_page_bytes(printer_name), parent, "Print Test Page", printer_name)


def save_report_pdf(con, receipt_id: int, parent=None) -> str | None:
    from PySide6.QtWidgets import QFileDialog
    r = con.execute("SELECT lab_no FROM receipts WHERE id=?", (receipt_id,)).fetchone()
    default = f"{(r['lab_no'] if r else 'report')}.pdf"
    path, _ = QFileDialog.getSaveFileName(parent, "Save report PDF", default, "PDF (*.pdf)")
    if path:
        export_report_pdf(con, receipt_id, path)
        return path
    return None
