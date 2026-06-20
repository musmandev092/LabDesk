"""Cash receipt drawing (build_receipt + receipt-only helpers)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QImage

from ._shared import _patient_card, centered_logo_left, fit_lab_name_font
from .constants import (
    A4_H_MM,
    ACCENT,
    BORDER,
    BORDER2,
    GREEN,
    INK,
    LIGHT,
    MUTED,
    RED,
    TEAL,
    px,
)
from .fonts import _font
from .primitives import Doc


# ---------------------------------------------------------------------------
# Cash receipt
# ---------------------------------------------------------------------------
def build_receipt(
    con, receipt_id: int, device=None, images: bool = False
) -> bytes | list[QImage] | None:
    from . import report as R

    g = R._g(con)
    r = con.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
    items = con.execute(
        "SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY id", (receipt_id,)
    ).fetchall()
    cur = g("currency", "Rs.")
    subtotal = r["subtotal"] or 0
    net = r["net_amount"] or 0
    paid = r["paid"] or 0
    due = r["due"] or 0
    discount = subtotal - net
    change = max(0.0, paid - net)
    reg_by = R._user_display(con, r["created_by"] if "created_by" in r.keys() else "")
    from datetime import datetime

    year = (r["received_at"] or "")[:4] or datetime.now().strftime("%Y")

    d = Doc(margin_mm=(8, 8, 8, 8), device=device, images=images)
    x0 = d.ml
    y = d.mt

    # ---- header ---- clinic info LEFT, CASH RECEIPT RIGHT, logo CENTRED both ways
    tx = x0
    # shrink the lab name so a long one stops short of the centred logo (no overlap)
    logo_left = centered_logo_left(d, g("logo_path"), x0)
    title_w = 120.0 if logo_left is None else max(45.0, logo_left - tx - 4.0)
    h1 = fit_lab_name_font(d, g("lab_name"), 16, title_w, min_pt=11.0)
    title_h = d.text_height("Xg", h1, title_w, wrap=False)
    addr_lines = [s for s in [g("address"), R._contacts(g), R._regs(g)] if s]
    d.text(tx, y, title_w, title_h + 1, g("lab_name"), h1, TEAL)
    cy = y + title_h + 1.2
    if g("lab_subtitle"):
        dept_f = _font(8.5, bold=True, spacing_px=0.6)
        d.text(tx, cy, 120, 4, g("lab_subtitle").upper(), dept_f, ACCENT)
        cy += 4.2
    addr_f = _font(8.5)
    for line in addr_lines:
        d.text(tx, cy, 130, 4, line, addr_f, MUTED)
        cy += 3.9
    # right: CASH RECEIPT title + meta
    h2 = _font(11, bold=True, spacing_px=1.0)
    d.text(x0, y, d.content_w, 7, "CASH RECEIPT", h2, TEAL, Qt.AlignRight | Qt.AlignTop)
    meta_f = _font(9)
    d.text(
        x0,
        y + 7.5,
        d.content_w,
        5,
        f"Date: {(r['received_at'] or '')[:16]}",
        meta_f,
        MUTED,
        Qt.AlignRight | Qt.AlignTop,
    )
    ry = y + 12.5
    if reg_by:
        d.text(
            x0,
            y + 12,
            d.content_w,
            5,
            f"Registered by: {reg_by}",
            meta_f,
            MUTED,
            Qt.AlignRight | Qt.AlignTop,
        )
        ry = y + 17
    # centre: logo, horizontally AND vertically centred within the header band
    logo_path = (g("logo_path") or "").strip()
    if logo_path and Path(logo_path).exists():
        header_h = max(cy, ry) - y
        logo_y = y + max(0.0, (header_h - px(48)) / 2)
        d.image(x0, logo_y, logo_path, 48, center_w=d.content_w)
    header_bottom = max(cy, ry, y + 16) + 1.5
    d.hline(x0, header_bottom, d.content_w, TEAL, 2)
    y = header_bottom + 5

    # ---- patient card ----
    # A cash receipt is a billing document issued at registration — results don't
    # exist yet, so it never shows a "Reporting Date".
    pairs = R._patient_pairs(r, include_reporting=False)
    ch = _patient_card(d, x0, y, pairs)
    y += ch + 7

    # ---- items table ----
    sr_w = d.content_w * 0.08
    rate_w = d.content_w * 0.22
    desc_w = d.content_w - sr_w - rate_w
    th_f = _font(8.5, bold=True, spacing_px=0.3)
    d.text(x0, y, sr_w, 6, "SR.", th_f, TEAL, Qt.AlignHCenter | Qt.AlignVCenter)
    d.text(
        x0 + sr_w,
        y,
        desc_w,
        6,
        "TEST DESCRIPTION",
        th_f,
        TEAL,
        Qt.AlignLeft | Qt.AlignVCenter,
    )
    d.text(
        x0 + sr_w + desc_w,
        y,
        rate_w,
        6,
        f"RATE ({cur})",
        th_f,
        TEAL,
        Qt.AlignRight | Qt.AlignVCenter,
    )
    y += 6.5
    d.hline(x0, y, d.content_w, TEAL, 2)
    y += 0.5
    row_f = _font(10)
    for i, it in enumerate(items):
        rh = 8.5
        d.text(
            x0, y, sr_w, rh, str(i + 1), row_f, INK, Qt.AlignHCenter | Qt.AlignVCenter
        )
        d.text(
            x0 + sr_w,
            y,
            desc_w,
            rh,
            it["test_name"] or "",
            row_f,
            INK,
            Qt.AlignLeft | Qt.AlignVCenter,
        )
        d.text(
            x0 + sr_w + desc_w,
            y,
            rate_w,
            rh,
            f"{(it['charge'] or 0):,.2f}",
            row_f,
            INK,
            Qt.AlignRight | Qt.AlignVCenter,
        )
        y += rh
        d.hline(x0, y, d.content_w, BORDER2, 1)
    y += 7

    # ---- summary: notes (left 55%) + totals (right 45%) ----
    notes_w = d.content_w * 0.55 - 10  # padding-right 10mm
    tot_x = x0 + d.content_w * 0.55
    tot_w = d.content_w * 0.45
    # amount in words box
    words = R._amount_in_words(net)
    wf_lbl = _font(9.5, bold=True)
    wf_val = _font(9.5)
    words_inner = notes_w - 8
    wh = (
        4
        + d.text_height("X", wf_lbl, words_inner, False)
        + 1
        + d.text_height(words, wf_val, words_inner, True)
        + 4
    )
    ny = y
    d.rounded(x0, ny, notes_w, wh, 4, fill=LIGHT)
    d.fill_rect(x0, ny, px(3), wh, ACCENT)  # left accent bar
    d.text(x0 + 4, ny + 4, words_inner, 5, "Amount in words:", wf_lbl, INK)
    d.text(
        x0 + 4,
        ny + 4 + d.text_height("X", wf_lbl, words_inner, False) + 1,
        words_inner,
        10,
        words,
        wf_val,
        INK,
        Qt.AlignLeft | Qt.AlignTop,
        wrap=True,
    )
    ry = ny + wh + 6
    rem_lbl = _font(8.5, bold=True)
    rem_f = _font(8.5)
    rem_txt = g("receipt_remarks")  # lab-editable in Settings → Receipt footer
    d.text(x0, ry, notes_w, 4, "Remarks:", rem_lbl, MUTED)
    d.text(
        x0,
        ry + 4,
        notes_w,
        30,
        rem_txt,
        rem_f,
        MUTED,
        Qt.AlignLeft | Qt.AlignTop,
        wrap=True,
    )

    # totals table
    tf = _font(10)
    tfb = _font(10, bold=True)
    lbl_x = tot_x
    ty = y

    def totrow(
        label: str,
        value: str,
        *,
        lbl_color: str = MUTED,
        val_color: str = INK,
        val_font: QFont = tfb,
        net_row: bool = False,
        lbl_font: QFont = tf,
    ) -> None:
        nonlocal ty
        rh = 8.5 if net_row else 6.5
        if net_row:
            d.hline(tot_x, ty, tot_w, BORDER, 1)
        d.text(
            lbl_x,
            ty,
            tot_w * 0.5,
            rh,
            label,
            lbl_font,
            lbl_color,
            Qt.AlignLeft | Qt.AlignVCenter,
        )
        d.text(
            tot_x,
            ty,
            tot_w,
            rh,
            value,
            val_font,
            val_color,
            Qt.AlignRight | Qt.AlignVCenter,
        )
        ty += rh
        if net_row:
            d.hline(tot_x, ty, tot_w, BORDER, 1)

    totrow("Total:", f"{subtotal:,.2f}")
    totrow("Discount:", f"{discount:,.2f}")
    totrow(
        "To Be Paid:",
        f"{cur} {net:,.2f}",
        lbl_color=TEAL,
        val_color=TEAL,
        val_font=_font(11, bold=True),
        lbl_font=_font(11, bold=True),
        net_row=True,
    )
    totrow("Paid:", f"{paid:,.2f}")
    due_col = RED if due else GREEN
    totrow("Balance:", f"{cur} {due:,.2f}", lbl_color=due_col, val_color=due_col)
    if change > 0:
        totrow(
            "Change returned:", f"{cur} {change:,.2f}", lbl_color=GREEN, val_color=GREEN
        )

    # ---- footer at page bottom ----
    fy = A4_H_MM - d.mb - 6
    d.hline(x0, fy, d.content_w, BORDER2, 1)
    ff = _font(8)
    ffi = _font(8)
    d.text(
        x0,
        fy + 1.5,
        d.content_w,
        5,
        f"{g('lab_name')} © {year}",
        ff,
        MUTED,
        Qt.AlignLeft | Qt.AlignVCenter,
    )
    d.text(
        x0,
        fy + 1.5,
        d.content_w,
        5,
        g("receipt_footer_note"),  # lab-editable in Settings
        ffi,
        MUTED,
        Qt.AlignRight | Qt.AlignVCenter,
    )
    return d.tobytes()
