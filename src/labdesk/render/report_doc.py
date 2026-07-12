"""Lab report drawing: build_report + header/footer + test-table layout/paint."""

from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QImage

from ..catalog_render import category_for_test
from ..report.formatting import smart_title
from ._shared import _patient_card, centered_logo_left, fit_lab_name_font
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
    tx = x0
    # shrink the lab name so a long one stops short of the centred logo (no overlap)
    logo_left = centered_logo_left(d, g("logo_path"), x0)
    title_w = 130.0 if logo_left is None else max(45.0, logo_left - tx - 4.0)
    h1 = fit_lab_name_font(d, g("lab_name"), 17, title_w, min_pt=11.0)
    h1h = d.text_height("Xg", h1, title_w, wrap=False)
    addr_lines = [s for s in [g("address"), _rcontacts(g)] if s]
    d.text(tx, y, title_w, h1h + 1, g("lab_name"), h1, TEAL)
    cy = y + h1h + 0.8
    if g("lab_subtitle"):
        d.text(
            tx,
            cy,
            130,
            3.6,
            g("lab_subtitle").upper(),
            _font(8, bold=True, spacing_px=0.4),
            ACCENT,
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
        d.text(
            x0,
            ry,
            d.content_w,
            3.4,
            regs,
            _font(7.3),
            MUTED,
            Qt.AlignRight | Qt.AlignTop,
        )
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


def _report_footer(d: Doc, con, g, page_no: int, total: int, code: str = "") -> None:
    """Running footer: signatures + footer line + dept band + Page X of Y.
    ``code`` (when set) is the report's verification code, shown bottom-left."""
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
    if code:
        # verification code, bottom-left (shares the row with Page X of Y). Lets the
        # issuing lab confirm a presented printout matches its records (Receipts →
        # Verify report); a tampered value makes the recomputed code differ.
        d.text(
            x0,
            yb - 4,
            d.content_w,
            4,
            f"Verification code: {code}",
            _font(7),
            FAINT,
            Qt.AlignLeft | Qt.AlignVCenter,
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
        # Disclaimer: wrap across (almost) the full width instead of clipping a
        # single centred line at both ends ("This…proceedings" was losing its first
        # and last letters). The block bottom stays where the one-line version sat
        # and grows upward; the rule above it widens to match. One-line footers are
        # rendered identically to before.
        fw = d.content_w - 16
        fx = x0 + 8
        ff = _font(7.3)
        fh = max(4.0, d.text_height(fline, ff, fw, wrap=True))
        ftop = cy + 4 - fh
        d.text(
            fx,
            ftop,
            fw,
            fh,
            fline,
            ff,
            MUTED,
            Qt.AlignHCenter | Qt.AlignVCenter,
            wrap=True,
        )
        d.hline(fx, ftop - 0.5, fw, BORDER, 1)
        cy = ftop - 5
    if sigs:
        sw = (d.content_w - 34) / len(sigs)
        for i, (n, t) in enumerate(sigs):
            sx = x0 + 17 + i * sw
            # signatory (doctor) name — larger + bold so it reads as the signature
            d.text(
                sx,
                cy - 5.2,
                sw,
                4.5,
                n,
                _font(10, bold=True),
                INK,
                Qt.AlignHCenter | Qt.AlignTop,
            )
            d.text(
                sx,
                cy - 0.4,
                sw,
                3.5,
                t,
                _font(7.3),
                MUTED,
                Qt.AlignHCenter | Qt.AlignTop,
            )


def _ref_lines(res, sex: str | None) -> tuple[list[str], str]:
    """Reference-range cell as (list-of-lines, flag_range), plain text for QPainter."""
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
        return [m], m
    if sx.startswith("f") and f:
        return [f], f
    if m and f and m != f:
        return [f"M: {m}", f"F: {f}"], ""
    one = m or f
    if one:
        return [one], one
    return ref_text.split("\n") or [""], ref_text


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
    title = smart_title(
        head["report_head"] if head and head["report_head"] else item["test_name"]
    )
    hist_labels, hist_maps = R._history_for_item(con, item, receipt)
    cur_label = (receipt["received_at"] or "")[:10]

    # columns: Test(26%) | Reference Range | Unit(11%) | [hist...] | Current
    cw = {}
    cw["test"] = d.content_w * 0.26
    cw["unit"] = d.content_w * 0.11
    rest = d.content_w - cw["test"] - cw["unit"]
    cw["ref"] = rest * 0.46
    # width of one value column (history columns + the current column) — needed
    # up front so a long/descriptive value (e.g. an ultrasound finding) grows the
    # row enough to wrap instead of clipping. Mirrors the divisor in _draw_test_table.
    nval = len(hist_labels) + 1
    each = (d.content_w - cw["test"] - cw["ref"] - cw["unit"]) / max(nval, 1)
    rows = []
    name_f = _font(8.6)  # test name
    ref_f = _font(7.8)
    cur_f = _font(9.5, bold=True)  # current-value font (matches the draw side)
    for res in results:
        if "hidden" in res.keys() and res["hidden"]:
            continue
        if (res["part_type"] or "N").upper() == "H":
            rows.append({"kind": "subhead", "text": res["name"] or "", "h": 5.2})
            continue
        name = (res["name"] or "").strip()
        val = str(res["value"]).strip() if res["value"] is not None else ""
        pid = res["parameter_id"] if "parameter_id" in res.keys() else None
        hist = [m.get(pid) for m in hist_maps]
        has_hist = any(str(h).strip() for h in hist if h is not None)
        # Blank current value: omit the row entirely — UNLESS the patient has
        # previous results for this parameter. Then keep the row so the history
        # columns still print, and show "No result" in the current column instead
        # of a misleading empty cell.
        no_result = False
        if not val:
            if not has_hist:
                continue
            no_result = True
        if not name and not val and not has_hist:
            continue
        ref_ls, flag = _ref_lines(res, sex)
        unit = res["units"] or ""
        h_name = d.text_height(name, name_f, cw["test"] - 4)
        # measure the ref as one wrapped block and include the unit cell, so a long
        # reference range or unit grows the row instead of being clipped.
        h_ref = d.text_height("\n".join(ref_ls), ref_f, cw["ref"] - 4)
        h_unit = d.text_height(unit, ref_f, cw["unit"] - 2)
        h_val = d.text_height(val, cur_f, each - 2) if val else 0
        rh = max(h_name, h_ref, h_unit, h_val, 5.0) + 2.4
        rows.append(
            {
                "kind": "row",
                "name": name,
                "ref_lines": ref_ls,
                "flag": flag,
                "unit": unit,
                "pid": pid,
                "value": res["value"],
                "hist": hist,
                "no_result": no_result,
                "h": rh,
            }
        )
    rows = _drop_orphan_subheads(rows)
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
    # Stop the body at the reserved footer band — the previous "+24" reclaimed most
    # of that band, so on a full page the last rows overprinted the signatures /
    # disclaimer of an official medical report.
    body_bottom = A4_H_MM - d.mb - REPORT_FOOTER_MM
    # title bar — square edges + a matching 1px border so it lines up pixel-flush
    # with the result rows below (which carry a border); a rounded bar previously
    # left the rows ~1-2px wider at both ends.
    d.fill_rect(x0, y, d.content_w, 6.5, TEAL)
    d.rect(x0, y, d.content_w, 6.5, TEAL_DARK, 1)
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
            d.text(
                cx,
                y + 1.3,
                each,
                3.2,
                "CURRENT",
                thf,
                "#ffffff",
                Qt.AlignHCenter | Qt.AlignTop,
            )
            dd = _fmt_two(lay["cur_label"])
            d.text(
                cx,
                y + 4.6,
                each,
                6.0,
                dd,
                _font(6.2),
                "#ffffff",
                Qt.AlignHCenter | Qt.AlignTop,
            )
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
        # ref — one wrapped block (wraps long ranges instead of clipping them)
        d.rect(cx, y, cw["ref"], rh, BORDER, 1)
        d.text(
            cx + 2,
            y,
            cw["ref"] - 4,
            rh,
            "\n".join(row["ref_lines"]),
            ref_f,
            MUTED,
            Qt.AlignHCenter | Qt.AlignVCenter,
            wrap=True,
        )
        cx += cw["ref"]
        # unit — wrap so long units (e.g. "Minutes / Seconds") are not clipped
        d.rect(cx, y, cw["unit"], rh, BORDER, 1)
        d.text(
            cx + 1,
            y,
            cw["unit"] - 2,
            rh,
            row["unit"],
            ref_f,
            MUTED,
            Qt.AlignHCenter | Qt.AlignVCenter,
            wrap=True,
        )
        cx += cw["unit"]
        # history values + current
        vals = [*list(row["hist"]), row["value"]]
        for vi, v in enumerate(vals):
            is_cur = vi == len(vals) - 1
            d.rect(cx, y, each, rh, BORDER, 1)
            if is_cur and row.get("no_result"):
                # blank current value but prior results exist — label it instead of
                # leaving an empty cell (see _measure_test).
                d.text(
                    cx + 1,
                    y,
                    each - 2,
                    rh,
                    "No result",
                    _font(7.2),
                    MUTED,
                    Qt.AlignHCenter | Qt.AlignVCenter,
                    wrap=True,
                )
            else:
                _draw_value(
                    d, cx, y, each, rh, v, row["flag"], cur_f if is_cur else cell_f
                )
            cx += each
        y += rh
        i += 1
    return y, rows[i:]


# ---------------------------------------------------------------------------
# Category renderers: descriptive (imaging/narrative) + qualitative (serology).
# Both reuse the running header/footer + pagination shape of _draw_test_table so
# multi-page reports keep working; only the per-test table body differs. Numeric
# tabular tests (CBC/LFT/RFT) and cultures are unchanged.
# ---------------------------------------------------------------------------
def _drop_orphan_subheads(rows: list) -> list:
    """Remove section sub-headings that have no visible content row beneath them.
    Once blank parameters are skipped, a heading like "DIFFERENTIAL COUNT" can be
    left with nothing under it; this drops the dangling heading. A heading is kept
    only if a row / narrative / note follows it before the next heading."""
    content_kinds = {"row", "narrative", "note"}
    keep: list = []
    n = len(rows)
    for i, r in enumerate(rows):
        if r.get("kind") == "subhead":
            has_content = False
            for j in range(i + 1, n):
                if rows[j].get("kind") == "subhead":
                    break
                if rows[j].get("kind") in content_kinds:
                    has_content = True
                    break
            if not has_content:
                continue
        keep.append(r)
    return keep


def _result_rows(con, item) -> list:
    """Entered result rows for a receipt item, joined to their parameter's ranges."""
    return con.execute(
        """SELECT res.*, tp.ref_male AS p_male, tp.ref_female AS p_female
           FROM results res LEFT JOIN test_parameters tp ON tp.id = res.parameter_id
           WHERE res.receipt_item_id=? ORDER BY res.seq""",
        (item["id"],),
    ).fetchall()


def _head_title(con, item) -> tuple:
    head = con.execute(
        "SELECT report_head, method_note FROM tests WHERE id=?", (item["test_id"],)
    ).fetchone()
    title = smart_title(
        head["report_head"] if head and head["report_head"] else item["test_name"]
    )
    return head, title


def _draw_title_bar(d: Doc, x0: float, y: float, title: str) -> float:
    # square edges + matching border so the title bar lines up flush with the table
    d.fill_rect(x0, y, d.content_w, 6.5, TEAL)
    d.rect(x0, y, d.content_w, 6.5, TEAL_DARK, 1)
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
    return y + 6.5


# Names that designate the dedicated Impression/Conclusion block (rendered below the
# table, not as a finding row). Whole-name match (not substring) so a real organ row
# like "Impression of liver" is NOT swallowed. Keep in sync with worklist's grid.
_CONCLUSION_NAMES = {
    "conclusion",
    "impression",
    "conclusion / impression",
    "impression / conclusion",
    "interpretation",
}


def _is_conclusion_name(name: str) -> bool:
    low = (name or "").strip().lower().rstrip(":").strip()
    return low in _CONCLUSION_NAMES


def _polarity(value: object) -> str | None:
    """Colour for a qualitative result: GREEN (negative/non-reactive), RED
    (positive/reactive/detected), or None (blood group / unknown free text → INK).
    Negative phrases are checked first because 'non-reactive' contains 'reactive'."""
    s = str(value or "").strip().lower()
    if not s:
        return None
    # whole words only — "+ve"/"-ve" are deliberately excluded because they clash
    # with blood-group notation (e.g. "B+", "O-ve" is a group, not a pathology flag).
    neg = (
        "non-reactive",
        "non reactive",
        "not detected",
        "not seen",
        "negative",
        "absent",
        "nil",
    )
    pos = ("reactive", "positive", "detected", "present")
    if any(w in s for w in neg):
        return GREEN
    if any(w in s for w in pos):
        return RED
    return None


def _measure_descriptive(d: Doc, con, item, sex: str | None, receipt) -> dict:
    """Layout for an imaging / narrative report: ORGAN/PART | FINDINGS (wide,
    wrapping). The CONCLUSION/IMPRESSION line renders as a block below the table
    (from receipt_items.conclusion), not as a cramped row."""
    head, title = _head_title(con, item)
    cw = {"part": d.content_w * 0.28, "find": d.content_w * 0.72}
    part_f = _font(8.6, bold=True)
    find_f = _font(8.8)
    rows = []
    for res in _result_rows(con, item):
        if "hidden" in res.keys() and res["hidden"]:
            continue
        name = (res["name"] or "").strip()
        val = str(res["value"]).strip() if res["value"] is not None else ""
        pt = (res["part_type"] or "N").upper()
        pid = res["parameter_id"] if "parameter_id" in res.keys() else None
        if _is_conclusion_name(name):
            continue  # rendered as the impression block below
        if pt == "H":
            rows.append({"kind": "subhead", "text": name, "h": 5.2})
            continue
        # A free-text result (no parameter — histopathology, biopsy, cytology, a
        # plain narrative imaging report) is a full-width paragraph, not an
        # organ/finding row with a meaningless "Result" label.
        if pid is None and val:
            h = d.text_height(val, find_f, d.content_w - 6)
            rows.append({"kind": "narrative", "text": val, "h": h + 3})
            continue
        # blank findings → omit the organ/part row (no history on imaging reports)
        if not val:
            continue
        h_name = d.text_height(name, part_f, cw["part"] - 4)
        h_val = d.text_height(val, find_f, cw["find"] - 4) if val else 0
        rows.append(
            {
                "kind": "row",
                "name": name,
                "value": val,
                "h": max(h_name, h_val, 5.0) + 2.4,
            }
        )
    rows = _drop_orphan_subheads(rows)
    from . import report as R

    narrative = not any(r["kind"] == "row" for r in rows)
    return {
        "title": title,
        "cw": cw,
        "rows": rows,
        "head": head,
        "item": item,
        "hist_labels": [],
        "cur_label": (receipt["received_at"] or "")[:10],
        "conclusion_heading": "IMPRESSION",
        "narrative": narrative,
        "prev_impression": R._prev_impression(con, item, receipt),
    }


def _split_text_by_height(
    d: Doc, text: str, font: QFont, width: float, max_h: float
) -> tuple[str, str]:
    """Split ``text`` at a word boundary so the head's wrapped height (in a
    ``width``-mm box) fits within ``max_h`` mm. Returns ``(head, tail)`` with
    ``tail == ""`` when everything fits. Words are never cut mid-character, and
    the head always carries at least one word so pagination is guaranteed to
    make progress even when not a single line fits in ``max_h``."""
    import re

    tokens = re.findall(r"\S+\s*", text)  # words with their trailing whitespace
    if len(tokens) <= 1:
        return text, ""
    if d.text_height(text, font, width, wrap=True) <= max_h:
        return text, ""
    # wrapped height is monotonic in the prefix length → binary-search the
    # largest whole-word prefix that fits (floor of 1 token = forced progress).
    lo, hi, best = 1, len(tokens) - 1, 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if d.text_height("".join(tokens[:mid]).rstrip(), font, width, True) <= max_h:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    head = "".join(tokens[:best]).rstrip()
    tail = "".join(tokens[best:]).strip()
    return head, tail


def _draw_descriptive_table(
    d: Doc, lay: dict, x0: float, y: float
) -> tuple[float, list]:
    cw = lay["cw"]
    body_bottom = A4_H_MM - d.mb - REPORT_FOOTER_MM  # reserve the footer band
    y = _draw_title_bar(d, x0, y, lay["title"])
    # A pure narrative report (histopathology, biopsy, free-text imaging) has no
    # organ/finding columns — skip the column header band entirely.
    narrative = lay.get("narrative")
    th_h = 7.0
    thf = _font(7, bold=True, spacing_px=0.3)
    if not narrative:
        for label, w in (("ORGAN / PART", cw["part"]), ("FINDINGS", cw["find"])):
            cx = x0 if label == "ORGAN / PART" else x0 + cw["part"]
            d.fill_rect(cx, y, w, th_h, TEAL)
            d.rect(cx, y, w, th_h, TEAL_DARK, 1)
            d.text(
                cx + 2,
                y,
                w - 4,
                th_h,
                label,
                thf,
                "#ffffff",
                Qt.AlignLeft | Qt.AlignVCenter,
            )
        y += th_h
    else:
        y += 1
    part_f = _font(8.6, bold=True)
    find_f = _font(8.8)
    rows = lay["rows"]
    even = False
    i = 0
    while i < len(rows):
        row = rows[i]
        rh = row["h"]
        if row["kind"] == "narrative" and y + rh > body_bottom:
            # An oversized narrative paragraph (histopathology / biopsy free text)
            # is a single row and cannot rely on the row-level page break — split
            # it at a word boundary: draw what fits here, hand the rest back as a
            # new narrative row so it continues on the next page.
            avail = body_bottom - y - 3
            line_h = d.text_height("Xg", find_f, d.content_w - 6, wrap=False)
            if avail < line_h and i > 0:
                break  # not even one line fits — move the whole row to next page
            head, tail = _split_text_by_height(
                d, row["text"], find_f, d.content_w - 6, avail
            )
            if tail:
                hh = d.text_height(head, find_f, d.content_w - 6)
                d.text(
                    x0 + 2,
                    y + 1,
                    d.content_w - 4,
                    hh + 2,
                    head,
                    find_f,
                    INK,
                    Qt.AlignLeft | Qt.AlignTop,
                    wrap=True,
                )
                y += hh + 3
                th = d.text_height(tail, find_f, d.content_w - 6)
                rest = [{"kind": "narrative", "text": tail, "h": th + 3}]
                return y, rest + list(rows[i + 1 :])
            # the whole paragraph fits in the remaining space after all — fall
            # through and draw it as a normal narrative row.
        elif y + rh > body_bottom and i > 0:
            break
        if row["kind"] == "narrative":
            d.text(
                x0 + 2,
                y + 1,
                d.content_w - 4,
                rh,
                row["text"],
                find_f,
                INK,
                Qt.AlignLeft | Qt.AlignTop,
                wrap=True,
            )
            y += rh
            i += 1
            continue
        if row["kind"] == "subhead":
            d.fill_rect(x0, y, d.content_w, rh, SUBHEAD_BG)
            d.rect(x0, y, d.content_w, rh, BORDER, 1)
            d.text(
                x0 + 2,
                y,
                d.content_w - 4,
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
            d.fill_rect(x0, y, d.content_w, rh, LIGHT)
        even = not even
        d.rect(x0, y, cw["part"], rh, BORDER, 1)
        d.text(
            x0 + 2,
            y + 1,
            cw["part"] - 4,
            rh,
            row["name"],
            part_f,
            INK,
            Qt.AlignLeft | Qt.AlignTop,
            wrap=True,
        )
        d.rect(x0 + cw["part"], y, cw["find"], rh, BORDER, 1)
        d.text(
            x0 + cw["part"] + 2,
            y + 1,
            cw["find"] - 4,
            rh,
            row["value"] or "—",
            find_f,
            INK if row["value"] else FAINT,
            Qt.AlignLeft | Qt.AlignTop,
            wrap=True,
        )
        y += rh
        i += 1
    return y, rows[i:]


def _measure_qual(d: Doc, con, item, sex: str | None, receipt) -> dict:
    """Layout for a qualitative serology/immunology report: TEST | RESULT |
    REFERENCE. No unit column; result is polarity-coloured."""
    head, title = _head_title(con, item)
    cw = {
        "test": d.content_w * 0.42,
        "result": d.content_w * 0.34,
        "ref": d.content_w * 0.24,
    }
    name_f = _font(8.6)
    res_f = _font(9.2, bold=True)
    ref_f = _font(7.8)
    rows = []
    for res in _result_rows(con, item):
        if "hidden" in res.keys() and res["hidden"]:
            continue
        name = (res["name"] or "").strip()
        val = str(res["value"]).strip() if res["value"] is not None else ""
        ref = (res["ref_text"] or "").strip()
        pt = (res["part_type"] or "N").upper()
        if pt == "H":
            rows.append({"kind": "subhead", "text": name, "h": 5.2})
            continue
        # 'L' rows are legacy static "legend/interpretation" lines carried over from
        # the VB6 catalog (e.g. Typhidot's "IgG Positive only:", Mantoux's
        # "INTERPRETATION:"). They are never fillable — the worklist shows them
        # read-only — and the explanatory text that once followed each label did NOT
        # survive the catalog migration, so they printed as orphan half-lines under
        # the result table. Drop them: a real interpretation belongs in the test's
        # method note or the descriptive INTERPRETATION block, not as bare fragments.
        if pt == "L":
            continue
        if not name:
            note = ref
            if not note and not val:
                continue
            h = d.text_height(note, ref_f, d.content_w - 6)
            rows.append({"kind": "note", "text": note, "h": max(h, 4.5) + 1.5})
            continue
        # blank result → omit the row (qualitative serology has no history columns)
        if not val:
            continue
        h_name = d.text_height(name, name_f, cw["test"] - 4)
        h_res = d.text_height(val, res_f, cw["result"] - 4) if val else 0
        h_ref = d.text_height(ref, ref_f, cw["ref"] - 4) if ref else 0
        rows.append(
            {
                "kind": "row",
                "name": name,
                "value": val,
                "ref": ref,
                "h": max(h_name, h_res, h_ref, 5.0) + 2.4,
            }
        )
    rows = _drop_orphan_subheads(rows)
    return {
        "title": title,
        "cw": cw,
        "rows": rows,
        "head": head,
        "item": item,
        "hist_labels": [],
        "cur_label": (receipt["received_at"] or "")[:10],
        "conclusion_heading": "INTERPRETATION",
    }


def _draw_qual_table(d: Doc, lay: dict, x0: float, y: float) -> tuple[float, list]:
    cw = lay["cw"]
    body_bottom = A4_H_MM - d.mb - REPORT_FOOTER_MM  # reserve the footer band
    y = _draw_title_bar(d, x0, y, lay["title"])
    th_h = 7.0
    thf = _font(7, bold=True, spacing_px=0.3)
    cols = [
        ("TEST", cw["test"], Qt.AlignLeft),
        ("RESULT", cw["result"], Qt.AlignHCenter),
        ("REFERENCE", cw["ref"], Qt.AlignHCenter),
    ]
    cx = x0
    for label, w, al in cols:
        d.fill_rect(cx, y, w, th_h, TEAL)
        d.rect(cx, y, w, th_h, TEAL_DARK, 1)
        d.text(cx + 2, y, w - 4, th_h, label, thf, "#ffffff", al | Qt.AlignVCenter)
        cx += w
    y += th_h
    name_f = _font(8.6)
    res_f = _font(9.2, bold=True)
    ref_f = _font(7.8)
    rows = lay["rows"]
    even = False
    i = 0
    while i < len(rows):
        row = rows[i]
        rh = row["h"]
        if y + rh > body_bottom and i > 0:
            break
        if row["kind"] == "subhead":
            d.fill_rect(x0, y, d.content_w, rh, SUBHEAD_BG)
            d.rect(x0, y, d.content_w, rh, BORDER, 1)
            d.text(
                x0 + 2,
                y,
                d.content_w - 4,
                rh,
                row["text"],
                _font(8.6, bold=True),
                TEAL_DARK,
                Qt.AlignLeft | Qt.AlignVCenter,
            )
            y += rh
            i += 1
            continue
        if row["kind"] == "note":
            d.text(
                x0 + 3,
                y,
                d.content_w - 6,
                rh,
                row["text"],
                ref_f,
                MUTED,
                Qt.AlignLeft | Qt.AlignVCenter,
                wrap=True,
            )
            y += rh
            i += 1
            continue
        if even:
            d.fill_rect(x0, y, d.content_w, rh, LIGHT)
        even = not even
        cx = x0
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
        d.rect(cx, y, cw["result"], rh, BORDER, 1)
        col = _polarity(row["value"]) or INK
        d.text(
            cx + 2,
            y,
            cw["result"] - 4,
            rh,
            row["value"] or "—",
            res_f,
            col if row["value"] else FAINT,
            Qt.AlignHCenter | Qt.AlignVCenter,
            wrap=True,
        )
        cx += cw["result"]
        d.rect(cx, y, cw["ref"], rh, BORDER, 1)
        d.text(
            cx + 2,
            y,
            cw["ref"] - 4,
            rh,
            row["ref"],
            ref_f,
            MUTED,
            Qt.AlignHCenter | Qt.AlignVCenter,
            wrap=True,
        )
        y += rh
        i += 1
    return y, rows[i:]


def _measure_blood_bank(d: Doc, con, item, sex: str | None, receipt) -> dict:
    """Blood-bank report (group / cross-match / Coombs): TEST | RESULT only — no
    reference column (standard practice). Result is polarity-coloured."""
    head, title = _head_title(con, item)
    cw = {"test": d.content_w * 0.55, "result": d.content_w * 0.45}
    name_f = _font(8.6)
    res_f = _font(9.2, bold=True)
    rows = []
    for res in _result_rows(con, item):
        if "hidden" in res.keys() and res["hidden"]:
            continue
        name = (res["name"] or "").strip()
        val = str(res["value"]).strip() if res["value"] is not None else ""
        pt = (res["part_type"] or "N").upper()
        if pt == "H":
            rows.append({"kind": "subhead", "text": name, "h": 5.2})
            continue
        # Drop legacy static 'L' legend rows (see _measure_qual). On blood-bank
        # reports these were cross-match placeholder dashes ("-") — pure noise.
        if pt == "L":
            continue
        if not name:
            note = res["ref_text"] or ""
            if not note and not val:
                continue
            h = d.text_height(note, name_f, d.content_w - 6)
            rows.append({"kind": "note", "text": note, "h": max(h, 4.5) + 1.5})
            continue
        # blank result → omit the row (blood-bank report has no history columns)
        if not val:
            continue
        h_name = d.text_height(name, name_f, cw["test"] - 4)
        h_res = d.text_height(val, res_f, cw["result"] - 4) if val else 0
        rows.append(
            {
                "kind": "row",
                "name": name,
                "value": val,
                "h": max(h_name, h_res, 5.0) + 2.4,
            }
        )
    rows = _drop_orphan_subheads(rows)
    return {
        "title": title,
        "cw": cw,
        "rows": rows,
        "head": head,
        "item": item,
        "hist_labels": [],
        "cur_label": (receipt["received_at"] or "")[:10],
        "conclusion_heading": "INTERPRETATION",
    }


def _draw_blood_bank(d: Doc, lay: dict, x0: float, y: float) -> tuple[float, list]:
    cw = lay["cw"]
    body_bottom = A4_H_MM - d.mb - REPORT_FOOTER_MM  # reserve the footer band
    y = _draw_title_bar(d, x0, y, lay["title"])
    th_h = 7.0
    thf = _font(7, bold=True, spacing_px=0.3)
    for label, w, al in (
        ("TEST", cw["test"], Qt.AlignLeft),
        ("RESULT", cw["result"], Qt.AlignHCenter),
    ):
        cx = x0 if label == "TEST" else x0 + cw["test"]
        d.fill_rect(cx, y, w, th_h, TEAL)
        d.rect(cx, y, w, th_h, TEAL_DARK, 1)
        d.text(cx + 2, y, w - 4, th_h, label, thf, "#ffffff", al | Qt.AlignVCenter)
    y += th_h
    name_f = _font(8.6)
    res_f = _font(9.2, bold=True)
    rows = lay["rows"]
    even = False
    i = 0
    while i < len(rows):
        row = rows[i]
        rh = row["h"]
        if y + rh > body_bottom and i > 0:
            break
        if row["kind"] == "subhead":
            d.fill_rect(x0, y, d.content_w, rh, SUBHEAD_BG)
            d.rect(x0, y, d.content_w, rh, BORDER, 1)
            d.text(
                x0 + 2,
                y,
                d.content_w - 4,
                rh,
                row["text"],
                _font(8.6, bold=True),
                TEAL_DARK,
                Qt.AlignLeft | Qt.AlignVCenter,
            )
            y += rh
            i += 1
            continue
        if row["kind"] == "note":
            d.text(
                x0 + 3,
                y,
                d.content_w - 6,
                rh,
                row["text"],
                name_f,
                MUTED,
                Qt.AlignLeft | Qt.AlignVCenter,
                wrap=True,
            )
            y += rh
            i += 1
            continue
        if even:
            d.fill_rect(x0, y, d.content_w, rh, LIGHT)
        even = not even
        d.rect(x0, y, cw["test"], rh, BORDER, 1)
        d.text(
            x0 + 2,
            y,
            cw["test"] - 4,
            rh,
            row["name"],
            name_f,
            INK,
            Qt.AlignLeft | Qt.AlignVCenter,
            wrap=True,
        )
        d.rect(x0 + cw["test"], y, cw["result"], rh, BORDER, 1)
        # blood group / Rh are identity, not pathology — never colour them; only the
        # cross-match / Coombs verdict gets a polarity cue (Not Compatible = red).
        nm = row["name"].lower()
        neutral = "group" in nm or "rh" in nm
        col = INK if neutral else (_polarity(row["value"]) or INK)
        d.text(
            x0 + cw["test"] + 2,
            y,
            cw["result"] - 4,
            rh,
            row["value"] or "—",
            res_f,
            col if row["value"] else FAINT,
            Qt.AlignHCenter | Qt.AlignVCenter,
            wrap=True,
        )
        y += rh
        i += 1
    return y, rows[i:]


def _draw_value(
    d: Doc,
    x: float,
    y: float,
    w: float,
    h: float,
    value: object,
    flag: str,
    font: QFont,
) -> None:
    from . import report as R

    if not value:
        d.text(x, y, w, h, "—", font, FAINT, Qt.AlignHCenter | Qt.AlignVCenter)
        return
    arrow = R._flag_arrow(value, flag)
    s = str(value)
    if not arrow:
        # Wrap so a long descriptive value (ultrasound/x-ray finding, a sentence
        # of serology comment) flows onto multiple lines inside the cell instead
        # of overflowing and clipping on both sides. Short numeric values are
        # unaffected — they stay on one centred line. The 1mm inset keeps wrapped
        # text off the cell borders.
        d.text(
            x + 1,
            y,
            w - 2,
            h,
            s,
            font,
            INK,
            Qt.AlignHCenter | Qt.AlignVCenter,
            wrap=True,
        )
        return
    col = RED if arrow[1] == "high" else AMBER
    # center the "value + arrow" pair
    fm = d.fm(font)
    wv = fm.horizontalAdvance(s) / DPI * 25.4
    wa = fm.horizontalAdvance(" " + arrow[0]) / DPI * 25.4
    start = x + (w - (wv + wa)) / 2
    d.text(start, y, wv + 1, h, s, font, col, Qt.AlignLeft | Qt.AlignVCenter)
    d.text(
        start + wv,
        y,
        wa + 1,
        h,
        " " + arrow[0],
        font,
        col,
        Qt.AlignLeft | Qt.AlignVCenter,
    )


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


def _draw_conclusion(d: Doc, lay: dict, x0: float, y: float) -> float:
    """Impression / Interpretation block below the table (imaging, molecular,
    serology). Reads receipt_items.conclusion; emphasised with an accent bar."""
    item = lay["item"]
    concl = ((item["conclusion"] if "conclusion" in item.keys() else "") or "").strip()
    prev = lay.get("prev_impression")
    if not concl and not prev:
        return y
    heading = lay.get("conclusion_heading", "IMPRESSION")
    hf = _font(8.6, bold=True)
    bf = _font(8.2)
    inner = d.content_w - 8
    if concl:
        y += 2.5
        hh = d.text_height(heading, hf, inner)
        th = d.text_height(concl, bf, inner, True)
        bh = hh + th + 5
        d.rounded(x0, y, d.content_w, bh, 3, fill=SUBHEAD_BG)
        d.fill_rect(x0, y, px(3), bh, TEAL)
        d.text(
            x0 + 4,
            y + 2,
            inner,
            hh + 1,
            heading,
            hf,
            TEAL_DARK,
            Qt.AlignLeft | Qt.AlignTop,
        )
        d.text(
            x0 + 4,
            y + 2 + hh + 0.5,
            inner,
            th + 2,
            concl,
            bf,
            INK,
            Qt.AlignLeft | Qt.AlignTop,
            wrap=True,
        )
        y += bh
    # "Compared with previous study" note (imaging) — the prior impression, muted.
    if prev:
        pdate, ptext = prev
        note = f"Compared with previous study ({pdate}): {ptext}"
        pf = _font(7.5)
        ph = d.text_height(note, pf, inner, True)
        y += 1.5
        d.text(
            x0 + 4,
            y,
            inner,
            ph + 2,
            note,
            pf,
            MUTED,
            Qt.AlignLeft | Qt.AlignTop,
            wrap=True,
        )
        y += ph + 1.5
    return y


def _draw_blocks_after_table(d: Doc, lay: dict, x0: float, y: float) -> float:
    """Impression + remarks box + method note below a finished test table."""
    y = _draw_conclusion(d, lay, x0, y)
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
        text = f"Method / Comments: {note}"
        mf = _font(7.5)
        # measure the real wrapped height and ADVANCE y past it — otherwise the block's
        # reported height is short by the note and the next packed test overlaps it.
        mh = d.text_height(text, mf, d.content_w, wrap=True)
        d.text(
            x0,
            y,
            d.content_w,
            mh + 2,
            text,
            mf,
            MUTED,
            Qt.AlignLeft | Qt.AlignTop,
            wrap=True,
        )
        y += mh + 2
    return y


# Draw function per non-culture render category (culture has its own path).
_DRAW_BY_KIND = {
    "numeric": _draw_test_table,
    "descriptive": _draw_descriptive_table,
    "qualitative": _draw_qual_table,
    "blood_bank": _draw_blood_bank,
}


def _build_layouts(d: Doc, con, items, sex, r) -> list:
    """Pre-measure each receipt item into a (kind, layout) pair ready for drawing."""
    layouts = []
    for it in items:
        cat = category_for_test(con, it["test_id"])
        if cat == "culture":
            layouts.append(("culture", _measure_culture(d, con, it)))
        elif cat == "descriptive":
            layouts.append(("descriptive", _measure_descriptive(d, con, it, sex, r)))
        elif cat == "qualitative":
            layouts.append(("qualitative", _measure_qual(d, con, it, sex, r)))
        elif cat == "blood_bank":
            layouts.append(("blood_bank", _measure_blood_bank(d, con, it, sex, r)))
        else:
            layouts.append(("numeric", _measure_test(d, con, it, sex, r)))
    return layouts


# Vertical gap (mm) inserted between two test blocks that share a page.
_PACK_GAP_MM = 5.0


def _after_height(lay) -> float:
    """Height (mm) of the conclusion/remarks/method blocks drawn below a test table,
    measured on a throwaway buffer (0 for a culture layout, which has none)."""
    if "item" not in lay:  # culture layouts carry no after-table blocks
        return 0.0
    tmp = Doc(margin_mm=(8, 8, 8, 8), measure=True)
    y0 = tmp.mt
    try:
        return max(0.0, _draw_blocks_after_table(tmp, lay, tmp.ml, y0) - y0)
    finally:
        with contextlib.suppress(Exception):
            tmp.tobytes()


def _block_height(con, kind, lay) -> tuple[float, bool, float]:
    """Measure one test block on a throwaway buffer, in a SINGLE draw pass. Returns
    ``(height_mm, spans_multiple_pages, after_blocks_height_mm)`` — the block's intrinsic
    height (title bar + table + any conclusion/remarks/method blocks, or the whole
    culture block), whether it overflows one fresh page, and the height of just the
    trailing conclusion/remarks/method blocks (needed to decide, when a long table
    spills, whether those trailing blocks still fit). Row heights are absolute mm, so
    the figures are independent of where the block is finally placed."""
    tmp = Doc(margin_mm=(8, 8, 8, 8), measure=True)
    y0 = tmp.mt
    page_bottom = A4_H_MM - tmp.mb - REPORT_FOOTER_MM
    draw = _draw_culture if kind == "culture" else _DRAW_BY_KIND[kind]
    try:
        y, remaining = draw(tmp, lay, tmp.ml, y0)
        if remaining:
            # taller than a page → own page; after-blocks measured separately (rare).
            after = 0.0 if kind == "culture" else _after_height(lay)
            return (A4_H_MM, True, after)
        if kind == "culture":  # culture draws its own remarks/notes inline
            return (max(0.0, y - y0), y > page_bottom, 0.0)
        end = _draw_blocks_after_table(tmp, lay, tmp.ml, y)
        return (max(0.0, end - y0), end > page_bottom, max(0.0, end - y))
    finally:
        with contextlib.suppress(Exception):
            tmp.tobytes()  # finalise the throwaway painter/buffer


def _measure_blocks(d: Doc, con, items, sex, r) -> list:
    """Build ``(kind, layout, height_mm, spans_multiple_pages, after_blocks_height)``
    for each receipt item, ready for the packing pass. Everything is measured ONCE
    here so the two pagination passes (count + real) do no extra measurement."""
    blocks = []
    for kind, lay in _build_layouts(d, con, items, sex, r):
        h, multipage, after_h = _block_height(con, kind, lay)
        blocks.append((kind, lay, h, multipage, after_h))
    return blocks


def _paginate_report(
    d: Doc, con, blocks, *, pack: bool, total_pages, header_fn, footer_fn, empty_msg
) -> int:
    """Single source of truth for report pagination + drawing. Walks the pre-measured
    blocks in receipt order and, when ``pack`` is True, stacks as many test blocks onto a
    page as fit (first-fit) to save paper: a block that does not fit in the space left
    starts a fresh page, and a block taller than a page spills via the per-table
    remaining-rows path. When ``pack`` is False every test starts its own page (the 'one
    test per page' option). ``header_fn(d) -> body_top_y`` paints the page header and
    returns the first content y; ``footer_fn(d, page_no, total)`` paints the footer (a
    no-op for the plain letterhead-free copy). Returns the total page count.

    Run once against a throwaway Doc to learn the page count, then again against the real
    Doc with that ``total_pages`` so every footer's 'X of Y' agrees."""
    body_bottom = A4_H_MM - d.mb - REPORT_FOOTER_MM
    x0 = d.ml
    if not blocks:
        body_top = header_fn(d)
        if empty_msg:
            d.text(x0, body_top + 10, d.content_w, 10, empty_msg, _font(10), MUTED)
        footer_fn(d, 1, 1)
        return 1
    page_no = 1
    y = header_fn(d)
    first_on_page = True
    for kind, lay, h, multipage, after_h in blocks:
        if not first_on_page:
            need_break = (not pack) or multipage or (y + _PACK_GAP_MM + h > body_bottom)
            if need_break:
                footer_fn(d, page_no, max(total_pages or page_no, page_no))
                d.new_page()
                page_no += 1
                y = header_fn(d)
                first_on_page = True
            else:
                y += _PACK_GAP_MM
        draw = _draw_culture if kind == "culture" else _DRAW_BY_KIND[kind]
        yy, remaining = draw(d, lay, x0, y)
        while remaining:
            footer_fn(d, page_no, max(total_pages or page_no, page_no))
            d.new_page()
            page_no += 1
            body_top = header_fn(d)
            lay2 = dict(lay)
            lay2["rows"] = remaining
            yy, remaining = draw(d, lay2, x0, body_top)
        # culture draws its own remarks/notes inline; other kinds have conclusion/
        # remarks/method blocks below the table. If the table spilled to the very
        # bottom of its last page, move those blocks to a fresh page instead of
        # painting them over the signature/footer band. (after_h precomputed once.)
        if kind != "culture":
            if after_h and yy + after_h > body_bottom:
                footer_fn(d, page_no, max(total_pages or page_no, page_no))
                d.new_page()
                page_no += 1
                yy = header_fn(d)
            yy = _draw_blocks_after_table(d, lay, x0, yy)
        y = yy
        first_on_page = False
    footer_fn(d, page_no, max(total_pages or page_no, page_no))
    return page_no


def _build_report_letterfree(
    con, r, items, sex, g, device, images, pack: bool = True, img_scale: float = 1.0
):
    """Render the report with no clinic letterhead and no footer, so it can be printed
    onto the lab's own pre-printed letterhead paper. Tests pack onto shared pages just
    like the normal copy; each page opens with the patient card."""
    from . import report as R

    d = Doc(margin_mm=(8, 8, 8, 8), device=device, images=images, img_scale=img_scale)
    blocks = _measure_blocks(d, con, items, sex, r)

    def header_fn(dd: Doc) -> float:
        ch = _patient_card(
            dd,
            dd.ml,
            dd.mt,
            R._patient_pairs(r),
            card_pad=(2.4, 5),
            gap=(1.6, 4),
            l_pt=6.6,
            v_pt=8.4,
            radius=5,
            border=BORDER,
        )
        return dd.mt + ch + 4

    def footer_fn(dd: Doc, page_no: int, total: int) -> None:
        return None

    _paginate_report(
        d,
        con,
        blocks,
        pack=pack,
        total_pages=1,
        header_fn=header_fn,
        footer_fn=footer_fn,
        empty_msg="No tests on this receipt.",
    )
    return d.tobytes()


def build_report(
    con,
    receipt_id: int,
    device=None,
    images: bool = False,
    letterhead: bool = True,
    pack: bool = True,
    img_scale: float = 1.0,
) -> bytes | list[QImage] | None:
    """Render a patient's full report. With ``pack`` (default) several tests share a page
    whenever they fit, to save paper; ``pack=False`` prints one test per page.
    ``img_scale`` (< 1.0, images mode only) rasterises at a fraction of print resolution
    for a faster on-screen preview — layout is identical, only the pixel buffer shrinks."""
    from . import report as R

    g = R._g(con)
    r = con.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
    items = con.execute(
        "SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY id", (receipt_id,)
    ).fetchall()
    sex = r["sex"]
    # "Plain" copy for a pre-printed letterhead pad: no clinic header, no footer.
    if not letterhead:
        return _build_report_letterfree(
            con, r, items, sex, g, device, images, pack, img_scale
        )
    # verification code in the footer — only for a finalised report (results in)
    code = (
        R.verification_code(con, receipt_id)
        if ("reported_at" in r.keys() and r["reported_at"])
        else ""
    )

    d = Doc(margin_mm=(8, 8, 8, 8), device=device, images=images, img_scale=img_scale)
    blocks = _measure_blocks(d, con, items, sex, r)

    def header_fn(dd: Doc) -> float:
        return _report_header(dd, con, g, r)

    def footer_fn(dd: Doc, page_no: int, total: int) -> None:
        _report_footer(dd, con, g, page_no, total, code)

    # A throwaway pagination pass first to learn the true page count, so EVERY footer's
    # "X of Y" agrees even when packing / a long test spilling changes the total; then
    # the real render with that total. The count pass NEVER rasterises (no images/device)
    # — that would double preview/print cost for zero benefit; page breaks come from the
    # pre-measured absolute-mm block heights, and the footer total is clamped to
    # ``max(total, page_no)`` so it can never read less than the current page.
    tmp = Doc(margin_mm=(8, 8, 8, 8), measure=True)
    total_pages = _paginate_report(
        tmp,
        con,
        blocks,
        pack=pack,
        total_pages=None,
        header_fn=lambda dd: _report_header(dd, con, g, r),
        footer_fn=lambda dd, p, t: _report_footer(dd, con, g, p, t, code),
        empty_msg="No tests on this receipt.",
    )
    with contextlib.suppress(Exception):
        tmp.tobytes()  # finalise the throwaway painter/buffer
    _paginate_report(
        d,
        con,
        blocks,
        pack=pack,
        total_pages=total_pages,
        header_fn=header_fn,
        footer_fn=footer_fn,
        empty_msg="No tests on this receipt.",
    )
    return d.tobytes()


def _measure_culture(d: Doc, con, item) -> dict:
    """Pre-measure a culture report into a row list (title + fixed fields + antibiotic
    sensitivity grid + remarks) so it paginates like every other test kind. Row heights
    are absolute mm; the draw side paints as many as fit and returns the rest."""
    head = con.execute(
        "SELECT report_head, method_note FROM tests WHERE id=?", (item["test_id"],)
    ).fetchone()
    title = smart_title(
        head["report_head"] if head and head["report_head"] else item["test_name"]
    )
    cur = con.execute(
        "SELECT * FROM cultures WHERE receipt_item_id=? ORDER BY id DESC LIMIT 1",
        (item["id"],),
    ).fetchone()
    rows: list = []
    if not cur:
        rows.append({"kind": "empty", "h": 8.0})
        return {"title": title, "rows": rows}
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
        # Wrap long values instead of clipping at the right edge; grow the row to fit.
        valw = d.content_w * 0.7 - 4
        th = d.text_height(str(val), _font(8.6, bold=True), valw, wrap=True)
        rows.append(
            {
                "kind": "field",
                "label": label,
                "value": str(val),
                "h": max(6.5, th + 2.6),
            }
        )
    sens = con.execute(
        "SELECT antibiotic, result FROM culture_sensitivity WHERE culture_id=? ORDER BY antibiotic",
        (cur["id"],),
    ).fetchall()
    if sens:
        rows.append({"kind": "senshead", "h": 10.0})  # 3mm gap + 7mm header band
        for s in sens:
            ab = s["antibiotic"] or ""
            abw = d.content_w * 0.5 - 4
            th = d.text_height(ab, _font(8.6), abw, wrap=True)
            rows.append(
                {
                    "kind": "sensrow",
                    "ab": ab,
                    "res": (s["result"] or "").upper(),
                    "h": max(6.5, th + 2.6),
                }
            )
    # Culture remarks (entered on the Microbiology screen) render as a wrapped block.
    if cur["remarks"]:
        rw = d.content_w - 4
        th = d.text_height(cur["remarks"], _font(8.4), rw, wrap=True)
        rows.append({"kind": "remarks", "text": cur["remarks"], "h": 3 + 5 + th + 2})
    return {"title": title, "rows": rows}


def _draw_culture(d: Doc, lay: dict, x0: float, y: float) -> tuple[float, list]:
    """Draw the culture title bar + as many pre-measured rows as fit; returns
    (y_after, remaining_rows) so an oversized antibiotic panel continues on the next
    page (the title bar and the ANTIBIOTIC/SENSITIVITY header repeat)."""
    body_bottom = A4_H_MM - d.mb - REPORT_FOOTER_MM
    d.fill_rect(x0, y, d.content_w, 6.5, TEAL)  # square edges, flush with the table
    d.rect(x0, y, d.content_w, 6.5, TEAL_DARK, 1)
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
    colour = {"S": GREEN, "I": AMBER, "R": RED}
    full = {"S": "Sensitive", "I": "Intermediate", "R": "Resistant"}
    rows = lay["rows"]
    i = 0
    while i < len(rows):
        row = rows[i]
        rh = row["h"]
        if y + rh > body_bottom and i > 0:
            break  # overflow → continue on the next page
        kind = row["kind"]
        if kind == "empty":
            d.text(
                x0 + 2,
                y + 2,
                d.content_w,
                6,
                "No culture result entered.",
                _font(8.6),
                MUTED,
            )
            y += rh
        elif kind == "field":
            d.rect(x0, y, d.content_w * 0.3, rh, BORDER, 1)
            d.text(
                x0 + 2,
                y + 1,
                d.content_w * 0.3 - 4,
                rh - 1,
                row["label"],
                _font(8.6),
                INK,
                Qt.AlignLeft | Qt.AlignTop,
            )
            d.rect(x0 + d.content_w * 0.3, y, d.content_w * 0.7, rh, BORDER, 1)
            d.text(
                x0 + d.content_w * 0.3 + 2,
                y + 1,
                d.content_w * 0.7 - 4,
                rh - 1,
                row["value"],
                _font(8.6, bold=True),
                INK,
                Qt.AlignLeft | Qt.AlignTop,
                wrap=True,
            )
            y += rh
        elif kind == "senshead":
            y += 3
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
        elif kind == "sensrow":
            res = row["res"]
            d.rect(x0, y, d.content_w * 0.5, rh, BORDER, 1)
            d.text(
                x0 + 2,
                y + 1,
                d.content_w * 0.5 - 4,
                rh - 1,
                row["ab"],
                _font(8.6),
                INK,
                Qt.AlignLeft | Qt.AlignTop,
                wrap=True,
            )
            d.rect(x0 + d.content_w * 0.5, y, d.content_w * 0.5, rh, BORDER, 1)
            d.text(
                x0 + d.content_w * 0.5 + 2,
                y + 1,
                d.content_w * 0.5 - 4,
                rh - 1,
                f"{res} — {full.get(res, '')}",
                _font(8.6, bold=True),
                colour.get(res, INK),
                Qt.AlignLeft | Qt.AlignTop,
            )
            y += rh
        elif kind == "remarks":
            y += 3
            d.text(
                x0 + 2,
                y,
                d.content_w - 4,
                5,
                "Remarks",
                _font(8.6, bold=True),
                TEAL,
                Qt.AlignLeft | Qt.AlignTop,
            )
            y += 5
            rw = d.content_w - 4
            th = d.text_height(row["text"], _font(8.4), rw, wrap=True)
            d.text(
                x0 + 2,
                y,
                rw,
                th + 1,
                row["text"],
                _font(8.4),
                INK,
                Qt.AlignLeft | Qt.AlignTop,
                wrap=True,
            )
            y += th + 2
        i += 1
    remaining = rows[i:]
    # If we broke mid-grid, repeat the ANTIBIOTIC/SENSITIVITY header on the next page.
    if remaining and remaining[0]["kind"] == "sensrow":
        remaining = [{"kind": "senshead", "h": 10.0}, *remaining]
    return y, remaining
