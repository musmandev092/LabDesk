"""Lab report drawing: build_report + header/footer + test-table layout/paint."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QImage

from ._shared import _patient_card
from .constants import (
    A4_H_MM,
    ACCENT,
    AMBER,
    BORDER,
    DPI,
    FAINT,
    GREEN,
    INK,
    LIGHT,
    MUTED,
    RED,
    REPORT_FOOTER_MM,
    SUBHEAD_BG,
    TEAL,
    TEAL_DARK,
    px,
)
from .fonts import _font
from .primitives import Doc


# ---------------------------------------------------------------------------
# Lab report
# ---------------------------------------------------------------------------
def _report_letterhead(d: Doc, g, x0: float, y: float) -> float:
    """Draw letterhead (logo + clinic + optional accred/regs) + the 2px rule.
    Returns y just below the rule."""
    h1 = _font(17, bold=True, spacing_px=-0.5)
    h1h = d.text_height("Xg", h1, 120, wrap=False)
    addr_lines = [s for s in [g("address"), _rcontacts(g)] if s]
    tx = x0
    d.text(tx, y, 130, h1h + 1, g("lab_name"), h1, TEAL)
    cy = y + h1h + 0.8
    if g("lab_subtitle"):
        d.text(
            tx, cy, 130, 3.6, g("lab_subtitle").upper(), _font(8, bold=True, spacing_px=0.4), ACCENT
        )
        cy += 3.8
    pf = _font(7.3)
    for line in addr_lines:
        d.text(tx, cy, 140, 3.4, line, pf, MUTED)
        cy += 3.2
    # top-right: accreditation logo + reg lines
    regs = _rregs(g)
    al = (g("accred_logo_1") or "").strip()
    ry = y
    if al and Path(al).exists():
        d.image(x0 + d.content_w - 20, ry, al, 40)
        ry += px(40) + 1
    if regs:
        d.text(x0, ry, d.content_w, 3.4, regs, _font(7.3), MUTED, Qt.AlignRight | Qt.AlignTop)
        ry += 3.4
    # centre: main logo, horizontally AND vertically centred within the header band
    lp = (g("logo_path") or "").strip()
    if lp and Path(lp).exists():
        header_h = max(cy, ry) - y
        logo_y = y + max(0.0, (header_h - px(48)) / 2)
        d.image(x0, logo_y, lp, 48, center_w=d.content_w)
    bottom = max(cy, ry, y + 16) + 2.5
    d.hline(x0, bottom, d.content_w, TEAL, 2)
    return bottom + 0.5


def _rcontacts(g) -> str:
    parts = [
        f"Ph: {g('phone')}" if g("phone") else "",
        f"Mob: {g('mobile')}" if g("mobile") else "",
        g("email") if g("email") else "",
    ]
    return " | ".join(p for p in parts if p)


def _rregs(g) -> str:
    parts = [
        f"PHC Reg #: {g('phc_reg_no')}" if g("phc_reg_no") else "",
        f"Lab Reg #: {g('lab_reg_no')}" if g("lab_reg_no") else "",
    ]
    return " | ".join(p for p in parts if p)


def _report_header(d: Doc, con, g, r) -> float:
    """Full running header: letterhead + small patient card. Returns body-top y."""
    from . import report as R

    x0 = d.ml
    y = _report_letterhead(d, g, x0, d.mt)
    y += 3
    ch = _patient_card(
        d,
        x0,
        y,
        R._patient_pairs(r),
        card_pad=(2.4, 5),
        gap=(1.6, 4),
        l_pt=6.6,
        v_pt=8.4,
        radius=5,
        border=BORDER,
    )
    return y + ch + 3


def _report_footer(d: Doc, con, g, page_no: int, total: int) -> None:
    """Running footer: signatures + footer line + dept band + Page X of Y."""
    x0 = d.ml
    sigs = [(g(f"signatory_{i}_name"), g(f"signatory_{i}_title")) for i in (1, 2)]
    sigs = [(n, t) for n, t in sigs if n]
    band = g("dept_band")
    fline = g("report_footer")
    # build bottom-up from page bottom (+4mm: sit the footer a little lower on the page)
    yb = A4_H_MM - d.mb + 4
    # Page X of Y (bottom-right, below everything)
    d.text(
        x0,
        yb - 4,
        d.content_w,
        4,
        f"Page {page_no} of {total}",
        _font(7),
        FAINT,
        Qt.AlignRight | Qt.AlignVCenter,
    )
    cy = yb - 8
    if band:
        d.text(
            x0,
            cy,
            d.content_w,
            4,
            band,
            _font(7.3, bold=True, spacing_px=0.3),
            TEAL,
            Qt.AlignHCenter | Qt.AlignVCenter,
        )
        cy -= 4.5
    if fline:
        d.text(
            x0 + 17,
            cy,
            d.content_w - 34,
            4,
            fline,
            _font(7.3),
            MUTED,
            Qt.AlignHCenter | Qt.AlignVCenter,
        )
        d.hline(x0 + 17, cy - 0.5, d.content_w - 34, BORDER, 1)
        cy -= 5
    if sigs:
        sw = (d.content_w - 34) / len(sigs)
        for i, (n, t) in enumerate(sigs):
            sx = x0 + 17 + i * sw
            # signatory (doctor) name — larger + bold so it reads as the signature
            d.text(
                sx, cy - 5.2, sw, 4.5, n, _font(10, bold=True), INK, Qt.AlignHCenter | Qt.AlignTop
            )
            d.text(sx, cy - 0.4, sw, 3.5, t, _font(7.3), MUTED, Qt.AlignHCenter | Qt.AlignTop)


def _ref_lines(res, sex: str | None) -> tuple[list[str], str]:
    """Reference-range cell as (list-of-lines, flag_range), plain text for QPainter."""
    keys = res.keys()
    m = ((res["p_male"] if "p_male" in keys else None) or "").strip().replace("\n", " ")
    f = ((res["p_female"] if "p_female" in keys else None) or "").strip().replace("\n", " ")
    ref_text = (res["ref_text"] if "ref_text" in keys else "") or ""
    sx = (sex or "").strip().lower()
    if sx.startswith("m") and m:
        return [m], m
    if sx.startswith("f") and f:
        return [f], f
    if m and f and m != f:
        return [f"M: {m}", f"F: {f}"], ""
    one = m or f
    if one:
        return [one], one
    return [ln for ln in ref_text.split("\n")] or [""], ref_text


def _measure_test(d: Doc, con, item, sex: str | None, receipt) -> dict[str, object]:
    """Return a layout dict for one (non-culture) test: title + columns + rows,
    with per-row heights, so we can paginate."""
    from . import report as R

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
    hist_labels, hist_maps = R._history_for_item(con, item, receipt)
    cur_label = (receipt["received_at"] or "")[:10]

    # columns: Test(26%) | Reference Range | Unit(11%) | [hist...] | Current
    cw = {}
    cw["test"] = d.content_w * 0.26
    cw["unit"] = d.content_w * 0.11
    rest = d.content_w - cw["test"] - cw["unit"]
    cw["ref"] = rest * 0.46
    rows = []
    name_f = _font(8.6)  # test name
    ref_f = _font(7.8)
    for res in results:
        if "hidden" in res.keys() and res["hidden"]:
            continue
        if (res["part_type"] or "N").upper() == "H":
            rows.append({"kind": "subhead", "text": res["name"] or "", "h": 5.2})
            continue
        name = (res["name"] or "").strip()
        val = str(res["value"]).strip() if res["value"] is not None else ""
        if not name and not val:
            continue
        ref_ls, flag = _ref_lines(res, sex)
        pid = res["parameter_id"] if "parameter_id" in res.keys() else None
        h_name = d.text_height(name, name_f, cw["test"] - 4)
        h_ref = sum(d.text_height(l, ref_f, cw["ref"] - 4) for l in ref_ls)
        rh = max(h_name, h_ref, 5.0) + 2.4
        rows.append(
            {
                "kind": "row",
                "name": name,
                "ref_lines": ref_ls,
                "flag": flag,
                "unit": res["units"] or "",
                "pid": pid,
                "value": res["value"],
                "hist": [m.get(pid) for m in hist_maps],
                "h": rh,
            }
        )
    return {
        "title": title,
        "cw": cw,
        "hist_labels": hist_labels,
        "cur_label": cur_label,
        "rows": rows,
        "head": head,
        "item": item,
    }


def _draw_test_table(d: Doc, lay: dict, x0: float, y: float) -> tuple[float, list]:
    """Draw the title bar + as many rows as fit; returns (y_after, remaining_rows).
    remaining_rows is a list to continue on the next page (header repeats)."""
    cw = lay["cw"]
    body_bottom = A4_H_MM - d.mb - REPORT_FOOTER_MM + 24  # body may use most of page
    # title bar
    d.top_rounded(x0, y, d.content_w, 6.5, 4, TEAL)
    d.text(
        x0 + 4,
        y,
        d.content_w - 8,
        6.5,
        lay["title"],
        _font(11, bold=True),
        "#ffffff",
        Qt.AlignLeft | Qt.AlignVCenter,
    )
    y += 6.5
    # header row
    cols = [
        ("TEST", cw["test"], Qt.AlignLeft),
        ("REFERENCE RANGE", cw["ref"], Qt.AlignHCenter),
        ("UNIT", cw["unit"], Qt.AlignHCenter),
    ]
    valcols = lay["hist_labels"] + [None]  # None => current
    each = (d.content_w - cw["test"] - cw["ref"] - cw["unit"]) / len(valcols)
    th_h = 11.0  # tall enough for "CURRENT" + a two-line date without clipping
    cx = x0
    thf = _font(7, bold=True, spacing_px=0.3)
    for label, w, al in cols:
        d.fill_rect(cx, y, w, th_h, TEAL)
        d.rect(cx, y, w, th_h, TEAL_DARK, 1)
        d.text(cx + 2, y, w - 4, th_h, label, thf, "#ffffff", al | Qt.AlignVCenter)
        cx += w
    for j, vl in enumerate(valcols):
        is_cur = vl is None
        d.fill_rect(cx, y, each, th_h, TEAL_DARK if is_cur else TEAL)
        d.rect(cx, y, each, th_h, TEAL_DARK, 1)
        if is_cur:
            d.text(cx, y + 1.3, each, 3.2, "CURRENT", thf, "#ffffff", Qt.AlignHCenter | Qt.AlignTop)
            dd = _fmt_two(lay["cur_label"])
            d.text(cx, y + 4.6, each, 6.0, dd, _font(6.2), "#ffffff", Qt.AlignHCenter | Qt.AlignTop)
        else:
            d.text(
                cx,
                y,
                each,
                th_h,
                _fmt_one(vl),
                _font(6.4),
                "#ffffff",
                Qt.AlignHCenter | Qt.AlignVCenter,
            )
        cx += each
    y += th_h

    name_f = _font(8.6)
    cell_f = _font(8.6, bold=True)
    ref_f = _font(7.8)
    cur_f = _font(9.5, bold=True)
    ncols_w = d.content_w
    even = False
    rows = lay["rows"]
    i = 0
    while i < len(rows):
        row = rows[i]
        rh = row["h"]
        if y + rh > body_bottom and i > 0:
            break  # overflow → continue next page
        if row["kind"] == "subhead":
            d.fill_rect(x0, y, ncols_w, rh, SUBHEAD_BG)
            d.rect(x0, y, ncols_w, rh, BORDER, 1)
            d.text(
                x0 + 2,
                y,
                ncols_w - 4,
                rh,
                row["text"],
                _font(8.6, bold=True),
                TEAL_DARK,
                Qt.AlignLeft | Qt.AlignVCenter,
            )
            y += rh
            i += 1
            continue
        if even:
            d.fill_rect(x0, y, ncols_w, rh, LIGHT)
        even = not even
        cx = x0
        # test name
        d.rect(cx, y, cw["test"], rh, BORDER, 1)
        d.text(
            cx + 2,
            y,
            cw["test"] - 4,
            rh,
            row["name"],
            name_f,
            INK,
            Qt.AlignLeft | Qt.AlignVCenter,
            wrap=True,
        )
        cx += cw["test"]
        # ref (possibly 2 lines)
        d.rect(cx, y, cw["ref"], rh, BORDER, 1)
        nlines = len(row["ref_lines"])
        lh = rh / max(nlines, 1)
        for k, line in enumerate(row["ref_lines"]):
            d.text(
                cx + 2,
                y + k * lh,
                cw["ref"] - 4,
                lh,
                line,
                ref_f,
                MUTED,
                Qt.AlignHCenter | Qt.AlignVCenter,
            )
        cx += cw["ref"]
        # unit
        d.rect(cx, y, cw["unit"], rh, BORDER, 1)
        d.text(cx, y, cw["unit"], rh, row["unit"], ref_f, MUTED, Qt.AlignHCenter | Qt.AlignVCenter)
        cx += cw["unit"]
        # history values + current
        vals = list(row["hist"]) + [row["value"]]
        for vi, v in enumerate(vals):
            is_cur = vi == len(vals) - 1
            d.rect(cx, y, each, rh, BORDER, 1)
            _draw_value(d, cx, y, each, rh, v, row["flag"], cur_f if is_cur else cell_f)
            cx += each
        y += rh
        i += 1
    return y, rows[i:]


def _draw_value(
    d: Doc, x: float, y: float, w: float, h: float, value: object, flag: str, font: QFont
) -> None:
    from . import report as R

    if not value:
        d.text(x, y, w, h, "—", font, FAINT, Qt.AlignHCenter | Qt.AlignVCenter)
        return
    arrow = R._flag_arrow(value, flag)
    s = str(value)
    if not arrow:
        d.text(x, y, w, h, s, font, INK, Qt.AlignHCenter | Qt.AlignVCenter)
        return
    col = RED if arrow[1] == "high" else AMBER
    # center the "value + arrow" pair
    fm = d.fm(font)
    wv = fm.horizontalAdvance(s) / DPI * 25.4
    wa = fm.horizontalAdvance(" " + arrow[0]) / DPI * 25.4
    start = x + (w - (wv + wa)) / 2
    d.text(start, y, wv + 1, h, s, font, col, Qt.AlignLeft | Qt.AlignVCenter)
    d.text(start + wv, y, wa + 1, h, " " + arrow[0], font, col, Qt.AlignLeft | Qt.AlignVCenter)


def _fmt_two(iso: str | None) -> str:
    from datetime import datetime

    s = (iso or "")[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d %b\n%Y")
    except ValueError:
        return s


def _fmt_one(iso: str | None) -> str:
    from datetime import datetime

    s = (iso or "")[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        return s


def _draw_blocks_after_table(d: Doc, lay: dict, x0: float, y: float) -> float:
    """Remarks box + method note below a finished test table."""
    item = lay["item"]
    rem = ((item["remarks"] if "remarks" in item.keys() else "") or "").strip()
    if rem:
        y += 2.5
        bf = _font(8)
        inner = d.content_w - 6
        th = d.text_height(f"Remarks: {rem}", bf, inner, True)
        bh = th + 4
        d.rounded(x0, y, d.content_w, bh, 3, fill=LIGHT)
        d.fill_rect(x0, y, px(3), bh, ACCENT)
        d.text(
            x0 + 3,
            y + 2,
            inner,
            bh,
            f"Remarks: {rem}",
            bf,
            INK,
            Qt.AlignLeft | Qt.AlignTop,
            wrap=True,
        )
        y += bh
    head = lay["head"]
    if head and head["method_note"]:
        import re

        note = re.sub(r"[ \t]*\n[ \t]*\n+", "\n", head["method_note"].replace("\r", ""))
        note = re.sub(r"[ \t]{2,}", " ", note).strip()
        y += 2.5
        d.text(
            x0,
            y,
            d.content_w,
            40,
            f"Method / Comments: {note}",
            _font(7.5),
            MUTED,
            Qt.AlignLeft | Qt.AlignTop,
            wrap=True,
        )
    return y


def build_report(
    con, receipt_id: int, device=None, images: bool = False
) -> bytes | list[QImage] | None:
    from . import report as R

    g = R._g(con)
    r = con.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
    items = con.execute(
        "SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY id", (receipt_id,)
    ).fetchall()
    sex = r["sex"]

    d = Doc(margin_mm=(8, 8, 8, 8), device=device, images=images)
    # Pre-measure: each item → list of "page chunks" (one test may span pages)
    # First a dry layout to count pages.
    layouts = []
    for it in items:
        tc = con.execute("SELECT is_culture FROM tests WHERE id=?", (it["test_id"],)).fetchone()
        if tc and tc["is_culture"]:
            layouts.append(("culture", it))
        else:
            layouts.append(("test", _measure_test(d, con, it, sex, r)))
    total_pages = max(1, len(layouts))  # one test per page (overflow adds pages, rare)

    page_no = 0
    for idx, (kind, lay) in enumerate(layouts):
        if page_no > 0:
            d.new_page()
        page_no += 1
        body_top = _report_header(d, con, g, r)
        if kind == "culture":
            _draw_culture(d, con, lay, d.ml, body_top)
        else:
            y, remaining = _draw_test_table(d, lay, d.ml, body_top)
            while remaining:
                _report_footer(d, con, g, page_no, total_pages + 1)  # will fix total below
                d.new_page()
                page_no += 1
                body_top = _report_header(d, con, g, r)
                lay2 = dict(lay)
                lay2["rows"] = remaining
                y, remaining = _draw_test_table(d, lay2, d.ml, body_top)
            _draw_blocks_after_table(d, lay, d.ml, y)
        _report_footer(d, con, g, page_no, max(total_pages, page_no))
    if not layouts:
        body_top = _report_header(d, con, g, r)
        d.text(d.ml, body_top + 10, d.content_w, 10, "No tests on this receipt.", _font(10), MUTED)
        _report_footer(d, con, g, 1, 1)
    return d.tobytes()


def _draw_culture(d: Doc, con, item, x0: float, y: float) -> float:
    head = con.execute(
        "SELECT report_head, method_note FROM tests WHERE id=?", (item["test_id"],)
    ).fetchone()
    title = (head["report_head"] if head and head["report_head"] else item["test_name"]).title()
    d.top_rounded(x0, y, d.content_w, 6.5, 4, TEAL)
    d.text(
        x0 + 4,
        y,
        d.content_w - 8,
        6.5,
        title,
        _font(11, bold=True),
        "#ffffff",
        Qt.AlignLeft | Qt.AlignVCenter,
    )
    y += 6.5
    cur = con.execute(
        "SELECT * FROM cultures WHERE receipt_item_id=? ORDER BY id DESC LIMIT 1", (item["id"],)
    ).fetchone()
    if not cur:
        d.text(x0 + 2, y + 2, d.content_w, 6, "No culture result entered.", _font(8.6), MUTED)
        return y + 8
    for label, val in (
        ("Specimen", cur["specimen"]),
        ("Growth", cur["growth"]),
        ("Organism", cur["organism"]),
        ("Colony count", cur["colony_count"]),
        ("Gram stain", cur["gram_stain"]),
        ("ZN stain", cur["zn_stain"]),
    ):
        if not val:
            continue
        rh = 6.5
        d.rect(x0, y, d.content_w * 0.3, rh, BORDER, 1)
        d.text(
            x0 + 2,
            y,
            d.content_w * 0.3 - 4,
            rh,
            label,
            _font(8.6),
            INK,
            Qt.AlignLeft | Qt.AlignVCenter,
        )
        d.rect(x0 + d.content_w * 0.3, y, d.content_w * 0.7, rh, BORDER, 1)
        d.text(
            x0 + d.content_w * 0.3 + 2,
            y,
            d.content_w * 0.7 - 4,
            rh,
            str(val),
            _font(8.6, bold=True),
            INK,
            Qt.AlignLeft | Qt.AlignVCenter,
        )
        y += rh
    sens = con.execute(
        "SELECT antibiotic, result FROM culture_sensitivity WHERE culture_id=? ORDER BY antibiotic",
        (cur["id"],),
    ).fetchall()
    if sens:
        y += 3
        colour = {"S": GREEN, "I": AMBER, "R": RED}
        full = {"S": "Sensitive", "I": "Intermediate", "R": "Resistant"}
        d.fill_rect(x0, y, d.content_w, 7, TEAL)
        d.text(
            x0 + 2,
            y,
            d.content_w * 0.5,
            7,
            "ANTIBIOTIC",
            _font(7, bold=True),
            "#ffffff",
            Qt.AlignLeft | Qt.AlignVCenter,
        )
        d.text(
            x0 + d.content_w * 0.5,
            y,
            d.content_w * 0.5,
            7,
            "SENSITIVITY",
            _font(7, bold=True),
            "#ffffff",
            Qt.AlignLeft | Qt.AlignVCenter,
        )
        y += 7
        for s in sens:
            rh = 6.5
            res = (s["result"] or "").upper()
            d.rect(x0, y, d.content_w * 0.5, rh, BORDER, 1)
            d.text(
                x0 + 2,
                y,
                d.content_w * 0.5 - 4,
                rh,
                s["antibiotic"] or "",
                _font(8.6),
                INK,
                Qt.AlignLeft | Qt.AlignVCenter,
            )
            d.rect(x0 + d.content_w * 0.5, y, d.content_w * 0.5, rh, BORDER, 1)
            d.text(
                x0 + d.content_w * 0.5 + 2,
                y,
                d.content_w * 0.5 - 4,
                rh,
                f"{res} — {full.get(res, '')}",
                _font(8.6, bold=True),
                colour.get(res, INK),
                Qt.AlignLeft | Qt.AlignVCenter,
            )
            y += rh
    return y
