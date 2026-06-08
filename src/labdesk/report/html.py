"""HTML document builders for the lab report and cash receipt.

The HTML builders here are retained for content tests and are not used for
rendering (rendering is native Qt; see :mod:`..render`).

Imports :mod:`.constants`, :mod:`.formatting` and :mod:`.content`.
"""

from __future__ import annotations

from datetime import datetime

from .constants import GREEN, INTER_TTF, RED
from .content import (
    _contacts,
    _culture_section,
    _g,
    _patient_card,
    _regs,
    _report_section,
    _signatures,
    _user_display,
)
from .formatting import _amount_in_words, _esc, _file_url, _img


# ---------------------------------------------------------------------------
# CSS (colours inlined; only the Inter font URL is injected)
# ---------------------------------------------------------------------------
def _font_face() -> str:
    if INTER_TTF.exists():
        return (
            f"@font-face{{font-family:'Inter';src:url('{_file_url(INTER_TTF)}');"
            "font-weight:100 900;font-style:normal;}"
        )
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
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
        f"{_font_face()}{css_body}</style></head><body>{body}</body></html>"
    )


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
        f"<div class='remarks'><b>Remarks:</b><br>{_esc(g('receipt_remarks'))}</div>"
        f"</div><div class='totals'><table class='tot'>"
        f"<tr><td class='lbl'>Total:</td><td class='val'>{subtotal:,.2f}</td></tr>"
        f"<tr><td class='lbl'>Discount:</td><td class='val'>{discount:,.2f}</td></tr>"
        f"<tr class='net'><td>To Be Paid:</td><td class='val'>{_esc(cur)} {net:,.2f}</td></tr>"
        f"<tr><td class='lbl'>Paid:</td><td class='val'>{paid:,.2f}</td></tr>"
        f"<tr><td class='lbl' style='color:{due_col};'>Balance:</td>"
        f"<td class='val' style='color:{due_col};'>{_esc(cur)} {due:,.2f}</td></tr>"
        + (
            f"<tr><td class='lbl' style='color:{GREEN};'>Change returned:</td>"
            f"<td class='val' style='color:{GREEN};'>{_esc(cur)} {change:,.2f}</td></tr>"
            if change > 0
            else ""
        )
        + "</table></div></div>"
    )
    note = g("receipt_footer_note")
    footer = (
        f"<table class='rfoot'><tr><td>{_esc(g('lab_name'))} © {_esc(year)}</td>"
        f"<td style='text-align:right;'><i>{_esc(note)}</i></td>"
        f"</tr></table>"
    )
    body = footer + header + _patient_card(r, include_reporting=False) + items_table + summary
    return _doc(_RECEIPT_CSS, body)
