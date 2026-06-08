"""Native Qt rendering of the lab report & cash receipt (QPainter → QPdfWriter).

A pixel-faithful reproduction of the former WeasyPrint HTML/CSS design, using only
Qt (which the app already bundles) — no WeasyPrint / Pango / Cairo / fontTools /
Pillow. All data/business logic still lives in report.py; this module only draws.

Coordinate model: paint at 300 dpi, position everything in millimetres. Helpers
mm() (mm→device units) and px() (CSS px@96 → mm) map the old CSS values exactly.
"""
from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QMarginsF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPageLayout, QPageSize,
    QPainter, QPainterPath, QPdfWriter, QPen, qAlpha, qBlue, qGreen, qRed,
)

ASSETS = Path(__file__).with_name("assets")
INTER_TTF = ASSETS / "fonts" / "Inter.ttf"


def autocrop_image(img: QImage) -> QImage:
    """Trim near-white / transparent padding baked into a logo so its content fills
    the space it's drawn in, instead of floating tiny inside its own margins. Shared
    by the sidebar brand mark AND the printed report/receipt letterhead.

    Safe for white-label use (every lab uploads a different logo):
      * background sampled from the 4 corners (majority) — a logo touching one corner
        won't fool it;
      * a colour TOLERANCE treats JPEG noise / off-white as background;
      * ONLY near-white or transparent padding is trimmed — a solid-COLOUR badge tile
        is part of the design and is kept (trimming it could leave a white mark
        invisible on the white page);
      * returns the original if there's no clear margin, so it's never worse.

    QImage-only (no QPixmap) so it is safe to call from the off-thread PDF builder.
    """
    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    if w < 8 or h < 8:
        return img
    corners = [img.pixel(0, 0), img.pixel(w - 1, 0), img.pixel(0, h - 1), img.pixel(w - 1, h - 1)]
    bg = max(set(corners), key=corners.count)
    br, bgc, bb, ba = qRed(bg), qGreen(bg), qBlue(bg), qAlpha(bg)
    is_transparent = ba < 16
    is_white = ba >= 16 and br >= 235 and bgc >= 235 and bb >= 235
    if not (is_transparent or is_white):
        return img
    TOL = 24

    def near_bg(px):
        a = qAlpha(px)
        if a < 16 and ba < 16:
            return True
        if abs(a - ba) > 40:
            return False
        return (abs(qRed(px) - br) <= TOL and abs(qGreen(px) - bgc) <= TOL
                and abs(qBlue(px) - bb) <= TOL)

    xs = range(0, w, max(1, w // 64))
    ys = range(0, h, max(1, h // 64))
    row_bg = lambda y: all(near_bg(img.pixel(x, y)) for x in xs)
    col_bg = lambda x: all(near_bg(img.pixel(x, y)) for y in ys)
    top = 0
    while top < h - 1 and row_bg(top):
        top += 1
    bot = h - 1
    while bot > top and row_bg(bot):
        bot -= 1
    left = 0
    while left < w - 1 and col_bg(left):
        left += 1
    right = w - 1
    while right > left and col_bg(right):
        right -= 1
    cw, ch = right - left + 1, bot - top + 1
    if cw < w * 0.05 or ch < h * 0.05 or (cw >= w * 0.98 and ch >= h * 0.98):
        return img
    pad = max(2, int(min(cw, ch) * 0.05))
    left = max(0, left - pad); top = max(0, top - pad)
    right = min(w - 1, right + pad); bot = min(h - 1, bot + pad)
    return img.copy(left, top, right - left + 1, bot - top + 1)

DPI = 300
A4_W_MM, A4_H_MM = 210.0, 297.0


def mm(v: float) -> float:
    return v / 25.4 * DPI


def px(v: float) -> float:
    """CSS px (at 96 dpi reference) → mm."""
    return v / 96.0 * 25.4


# palette (identical hex to the former CSS)
TEAL = "#005f73"
TEAL_DARK = "#004d5c"
ACCENT = "#0a9396"
GREEN = "#059669"
AMBER = "#d97706"
RED = "#dc2626"
INK = "#1e293b"
MUTED = "#64748b"
FAINT = "#94a3b8"
LIGHT = "#f8fafc"
BORDER = "#cbd5e1"
BORDER2 = "#e2e8f0"
SUBHEAD_BG = "#e6eff1"

_FAMILY = None


def _ensure_app():
    """Qt painting/font APIs need a QGuiApplication. The GUI always has one; this
    only kicks in for headless use (a script/test that exports a PDF directly)."""
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        import sys
        QApplication(sys.argv[:1])


def _family() -> str:
    global _FAMILY
    if _FAMILY is None:
        _ensure_app()
        fid = QFontDatabase.addApplicationFont(str(INTER_TTF))
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        _FAMILY = fams[0] if fams else "sans-serif"
    return _FAMILY


def preload():
    """Load the bundled font once on the main thread (call at app startup) so the
    PDF-building worker thread never touches QFontDatabase off-thread."""
    _family()


def _font(size_pt, *, bold=False, spacing_px=0.0):
    f = QFont(_family())
    f.setPointSizeF(size_pt)
    f.setBold(bold)
    f.setHintingPreference(QFont.PreferNoHinting)
    if spacing_px:
        # CSS letter-spacing px@96 → points (font logical units are points here)
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing_px / 96.0 * 72.0)
    return f


class Doc:
    """A QPdfWriter + QPainter wrapper that draws in millimetres at 300 dpi."""

    def __init__(self, margin_mm=(8, 8, 8, 8), device=None, images=False):
        _ensure_app()
        self._images_mode = images
        self._images = []
        self._owns = device is None and not images
        if images:
            # paint each page onto an A4 QImage at 300 dpi (for on-screen preview,
            # so we need no QtPdf viewer). new_page() finalises one and starts next.
            self._buf = self._dev = self.w = None
        elif self._owns:
            self._buf = QByteArray()
            self._dev = QBuffer(self._buf)
            self._dev.open(QBuffer.WriteOnly)
            self.w = QPdfWriter(self._dev)
        else:
            # an external QPagedPaintDevice (e.g. a QPrinter) — paint straight onto
            # it so printing needs no QtPdf round-trip and emits vector output
            self._buf = self._dev = None
            self.w = device
        self.ml, self.mt, self.mr, self.mb = margin_mm
        self.content_w = A4_W_MM - self.ml - self.mr
        if images:
            self._start_image()
        else:
            self.w.setResolution(DPI)
            self.w.setPageSize(QPageSize(QPageSize.A4))
            with contextlib.suppress(Exception):
                self.w.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)
            with contextlib.suppress(Exception):
                self.w.setFullPage(True)      # QPrinter: paint the whole sheet ourselves
            self.p = QPainter(self.w)
            self._hints()

    def _hints(self):
        self.p.setRenderHint(QPainter.Antialiasing, True)
        self.p.setRenderHint(QPainter.TextAntialiasing, True)
        self.p.setRenderHint(QPainter.SmoothPixmapTransform, True)

    def _start_image(self):
        img = QImage(int(mm(A4_W_MM)), int(mm(A4_H_MM)), QImage.Format_RGB888)
        img.fill(QColor("#ffffff"))
        img.setDotsPerMeterX(int(DPI / 25.4 * 1000))
        img.setDotsPerMeterY(int(DPI / 25.4 * 1000))
        self._cur_img = img
        self.p = QPainter(img)
        self._hints()

    # -- finish: PDF bytes (owned QPdfWriter), list[QImage] (images), or None --
    def finish(self):
        self.p.end()
        if self._images_mode:
            self._images.append(self._cur_img)
            return self._images
        if self._owns:
            self._dev.close()
            return bytes(self._buf)
        return None

    def tobytes(self) -> bytes:
        return self.finish()

    def new_page(self):
        if self._images_mode:
            self.p.end()
            self._images.append(self._cur_img)
            self._start_image()
        else:
            self.w.newPage()

    # -- primitives (all args in mm) --
    def fm(self, font) -> QFontMetricsF:
        return QFontMetricsF(font, self.p.device())

    def fill_rect(self, x, y, w, h, color):
        self.p.fillRect(QRectF(mm(x), mm(y), mm(w), mm(h)), QColor(color))

    def rect(self, x, y, w, h, color, width_px=1.0):
        self.p.setBrush(Qt.NoBrush)
        self.p.setPen(QPen(QColor(color), mm(px(width_px))))
        self.p.drawRect(QRectF(mm(x), mm(y), mm(w), mm(h)))

    def rounded(self, x, y, w, h, radius_px, fill=None, border=None, border_px=1.0):
        r = mm(px(radius_px))
        path = QPainterPath()
        path.addRoundedRect(QRectF(mm(x), mm(y), mm(w), mm(h)), r, r)
        if fill:
            self.p.fillPath(path, QColor(fill))
        if border:
            self.p.setPen(QPen(QColor(border), mm(px(border_px))))
            self.p.setBrush(Qt.NoBrush)
            self.p.drawPath(path)

    def top_rounded(self, x, y, w, h, radius_px, fill):
        """Rectangle with only the top two corners rounded (title bar)."""
        r = mm(px(radius_px))
        path = QPainterPath()
        path.moveTo(mm(x), mm(y + h))
        path.lineTo(mm(x), mm(y) + r)
        path.quadTo(mm(x), mm(y), mm(x) + r, mm(y))
        path.lineTo(mm(x + w) - r, mm(y))
        path.quadTo(mm(x + w), mm(y), mm(x + w), mm(y) + r)
        path.lineTo(mm(x + w), mm(y + h))
        path.closeSubpath()
        self.p.fillPath(path, QColor(fill))

    def hline(self, x, y, w, color, width_px=1.0):
        self.p.setPen(QPen(QColor(color), mm(px(width_px))))
        self.p.drawLine(QRectF(mm(x), mm(y), mm(w), 0).topLeft(),
                        QRectF(mm(x), mm(y), mm(w), 0).topRight())

    def text(self, x, y, w, h, s, font, color, align=Qt.AlignLeft | Qt.AlignVCenter,
             wrap=False):
        self.p.setFont(font)
        self.p.setPen(QColor(color))
        flags = int(align)
        if wrap:
            flags |= int(Qt.TextWordWrap)
        self.p.drawText(QRectF(mm(x), mm(y), mm(w), mm(h)), flags, s or "")

    def text_runs(self, x, y, h, runs, align_left=True):
        """Draw a sequence of (text, font, color) runs on one baseline-centred row,
        left to right. Returns total width in mm. Used for value + colored arrow."""
        cx = x
        for s, font, color in runs:
            fmpx = self.fm(font)
            adv = fmpx.horizontalAdvance(s) / DPI * 25.4
            self.p.setFont(font)
            self.p.setPen(QColor(color))
            self.p.drawText(QRectF(mm(cx), mm(y), mm(adv + 1), mm(h)),
                            int(Qt.AlignLeft | Qt.AlignVCenter), s)
            cx += adv
        return cx - x

    def image(self, x, y, path, h_px, center_w=None):
        img = QImage(str(path))
        if img.isNull():
            return 0.0
        img = autocrop_image(img)          # trim baked-in white/transparent margins
        target_h = mm(px(h_px))
        scaled = img.scaledToHeight(int(target_h), Qt.SmoothTransformation)
        w_mm = scaled.width() / DPI * 25.4
        if center_w is not None:           # horizontally centre within [x, x+center_w]
            x = x + (center_w - w_mm) / 2
        self.p.drawImage(QRectF(mm(x), mm(y), scaled.width(), scaled.height()).topLeft(), scaled)
        return w_mm                        # drawn width in mm

    def text_height(self, s, font, w, wrap=True) -> float:
        """Measured height in mm for text in a width-w (mm) box."""
        fmpx = self.fm(font)
        flags = int(Qt.AlignLeft | Qt.AlignTop)
        if wrap:
            flags |= int(Qt.TextWordWrap)
        br = fmpx.boundingRect(QRectF(0, 0, mm(w), mm(10000)), flags, s or "")
        return br.height() / DPI * 25.4


# ---------------------------------------------------------------------------
# Shared: letterhead + patient card
# ---------------------------------------------------------------------------
def _wrap_value(fm: QFontMetricsF, text: str, max_px: float, max_lines: int = 2):
    """Greedy word-wrap `text` to fit `max_px` device units across up to `max_lines`
    lines. If content still overflows, the last line is elided with '…' so long
    values (e.g. a full specimen) are shown completely instead of cut to one line."""
    words = (text or "").split()
    if not words:
        return ["—"]
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if cur and fm.horizontalAdvance(trial) > max_px:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    # elide any single word wider than the cell
    lines = [ln if fm.horizontalAdvance(ln) <= max_px
             else fm.elidedText(ln, Qt.ElideRight, max_px) for ln in lines]
    if len(lines) > max_lines:
        keep = lines[:max_lines]
        keep[-1] = fm.elidedText(" ".join(lines[max_lines - 1:]), Qt.ElideRight, max_px)
        lines = keep
    return lines


def _patient_card(d: Doc, x, y, pairs, *, card_pad=(5, 6), gap=(4, 6),
                  l_pt=7.5, v_pt=9.5, radius=6, border=BORDER2, max_value_lines=2):
    """4-column patient card with word-wrapped values. Returns total height in mm."""
    cols = 4
    rows = (len(pairs) + cols - 1) // cols
    pv, ph = card_pad
    gv, gh = gap
    inner_w = d.content_w - 2 * ph
    col_w = (inner_w - (cols - 1) * gh) / cols
    l_font = _font(l_pt, bold=True, spacing_px=0.3)
    v_font = _font(v_pt, bold=True)
    vfm = d.fm(v_font)
    l_h = d.text_height("X", l_font, col_w, wrap=False)
    v_h = d.text_height("X", v_font, col_w, wrap=False)
    line_gap = 0.3
    # let a long value spill into the column gap (not the last column) so names
    # like "Muhammad Usman Khan" don't clip, matching the CSS grid overflow
    wrapped = []
    for i, (lbl, val) in enumerate(pairs):
        c = i % cols
        vw = col_w + (gh - 1) if c < cols - 1 else col_w
        lines = _wrap_value(vfm, str(val) if val else "", mm(vw), max_value_lines)
        wrapped.append((lbl, lines, vw))
    # per-row height adapts to the tallest (most-wrapped) value in that row
    row_h = []
    for r in range(rows):
        n = max((len(wrapped[r * cols + c][1])
                 for c in range(cols) if r * cols + c < len(wrapped)), default=1)
        row_h.append(l_h + 0.6 + n * v_h + (n - 1) * line_gap)
    card_h = 2 * pv + sum(row_h) + (rows - 1) * gv
    d.rounded(x, y, d.content_w, card_h, radius, fill=LIGHT, border=border)
    cy = y + pv
    for r in range(rows):
        for c in range(cols):
            i = r * cols + c
            if i >= len(wrapped):
                continue
            lbl, lines, vw = wrapped[i]
            cx = x + ph + c * (col_w + gh)
            d.text(cx, cy, col_w, l_h, lbl.upper(), l_font, MUTED,
                   Qt.AlignLeft | Qt.AlignVCenter)
            vy = cy + l_h + 0.6
            for ln in lines:
                d.text(cx, vy, vw, v_h, ln, v_font, INK, Qt.AlignLeft | Qt.AlignVCenter)
                vy += v_h + line_gap
        cy += row_h[r] + gv
    return card_h


# ---------------------------------------------------------------------------
# Cash receipt
# ---------------------------------------------------------------------------
def build_receipt(con, receipt_id: int, device=None, images=False):
    from . import report as R
    g = R._g(con)
    r = con.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
    items = con.execute(
        "SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY id", (receipt_id,)).fetchall()
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
    h1 = _font(16, bold=True, spacing_px=-0.5)
    title_h = d.text_height("Xg", h1, 120, wrap=False)
    addr_lines = [s for s in [g("address"), R._contacts(g), R._regs(g)] if s]
    d.text(tx, y, 120, title_h + 1, g("lab_name"), h1, TEAL)
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
    d.text(x0, y + 7.5, d.content_w, 5, f"Date: {(r['received_at'] or '')[:16]}", meta_f, MUTED,
           Qt.AlignRight | Qt.AlignTop)
    ry = y + 12.5
    if reg_by:
        d.text(x0, y + 12, d.content_w, 5, f"Registered by: {reg_by}", meta_f, MUTED,
               Qt.AlignRight | Qt.AlignTop)
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
    d.text(x0 + sr_w, y, desc_w, 6, "TEST DESCRIPTION", th_f, TEAL, Qt.AlignLeft | Qt.AlignVCenter)
    d.text(x0 + sr_w + desc_w, y, rate_w, 6, f"RATE ({cur})", th_f, TEAL,
           Qt.AlignRight | Qt.AlignVCenter)
    y += 6.5
    d.hline(x0, y, d.content_w, TEAL, 2)
    y += 0.5
    row_f = _font(10)
    for i, it in enumerate(items):
        rh = 8.5
        d.text(x0, y, sr_w, rh, str(i + 1), row_f, INK, Qt.AlignHCenter | Qt.AlignVCenter)
        d.text(x0 + sr_w, y, desc_w, rh, it["test_name"] or "", row_f, INK,
               Qt.AlignLeft | Qt.AlignVCenter)
        d.text(x0 + sr_w + desc_w, y, rate_w, rh, f"{(it['charge'] or 0):,.2f}", row_f, INK,
               Qt.AlignRight | Qt.AlignVCenter)
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
    wh = 4 + d.text_height("X", wf_lbl, words_inner, False) + 1 + \
        d.text_height(words, wf_val, words_inner, True) + 4
    ny = y
    d.rounded(x0, ny, notes_w, wh, 4, fill=LIGHT)
    d.fill_rect(x0, ny, px(3), wh, ACCENT)  # left accent bar
    d.text(x0 + 4, ny + 4, words_inner, 5, "Amount in words:", wf_lbl, INK)
    d.text(x0 + 4, ny + 4 + d.text_height("X", wf_lbl, words_inner, False) + 1, words_inner, 10,
           words, wf_val, INK, Qt.AlignLeft | Qt.AlignTop, wrap=True)
    ry = ny + wh + 6
    rem_lbl = _font(8.5, bold=True)
    rem_f = _font(8.5)
    rem_txt = g("receipt_remarks")          # lab-editable in Settings → Receipt footer
    d.text(x0, ry, notes_w, 4, "Remarks:", rem_lbl, MUTED)
    d.text(x0, ry + 4, notes_w, 30, rem_txt, rem_f, MUTED, Qt.AlignLeft | Qt.AlignTop, wrap=True)

    # totals table
    tf = _font(10)
    tfb = _font(10, bold=True)
    lbl_x = tot_x
    ty = y
    def totrow(label, value, *, lbl_color=MUTED, val_color=INK, val_font=tfb,
               net_row=False, lbl_font=tf):
        nonlocal ty
        rh = 8.5 if net_row else 6.5
        if net_row:
            d.hline(tot_x, ty, tot_w, BORDER, 1)
        d.text(lbl_x, ty, tot_w * 0.5, rh, label, lbl_font, lbl_color, Qt.AlignLeft | Qt.AlignVCenter)
        d.text(tot_x, ty, tot_w, rh, value, val_font, val_color, Qt.AlignRight | Qt.AlignVCenter)
        ty += rh
        if net_row:
            d.hline(tot_x, ty, tot_w, BORDER, 1)
    totrow("Total:", f"{subtotal:,.2f}")
    totrow("Discount:", f"{discount:,.2f}")
    totrow("To Be Paid:", f"{cur} {net:,.2f}", lbl_color=TEAL, val_color=TEAL,
           val_font=_font(11, bold=True), lbl_font=_font(11, bold=True), net_row=True)
    totrow("Paid:", f"{paid:,.2f}")
    due_col = RED if due else GREEN
    totrow("Balance:", f"{cur} {due:,.2f}", lbl_color=due_col, val_color=due_col)
    if change > 0:
        totrow("Change returned:", f"{cur} {change:,.2f}", lbl_color=GREEN, val_color=GREEN)

    # ---- footer at page bottom ----
    fy = A4_H_MM - d.mb - 6
    d.hline(x0, fy, d.content_w, BORDER2, 1)
    ff = _font(8)
    ffi = _font(8)
    d.text(x0, fy + 1.5, d.content_w, 5, f"{g('lab_name')} © {year}", ff, MUTED,
           Qt.AlignLeft | Qt.AlignVCenter)
    d.text(x0, fy + 1.5, d.content_w, 5, g("receipt_footer_note"),  # lab-editable in Settings
           ffi, MUTED, Qt.AlignRight | Qt.AlignVCenter)
    return d.tobytes()


# ---------------------------------------------------------------------------
# Lab report
# ---------------------------------------------------------------------------
REPORT_HEADER_MM = 57.0    # reserved running-header band (matches CSS @page margin)
REPORT_FOOTER_MM = 27.0    # reserved running-footer band


def _report_letterhead(d: Doc, g, x0, y):
    """Draw letterhead (logo + clinic + optional accred/regs) + the 2px rule.
    Returns y just below the rule."""
    h1 = _font(17, bold=True, spacing_px=-0.5)
    h1h = d.text_height("Xg", h1, 120, wrap=False)
    addr_lines = [s for s in [g("address"), _rcontacts(g)] if s]
    tx = x0
    d.text(tx, y, 130, h1h + 1, g("lab_name"), h1, TEAL)
    cy = y + h1h + 0.8
    if g("lab_subtitle"):
        d.text(tx, cy, 130, 3.6, g("lab_subtitle").upper(), _font(8, bold=True, spacing_px=0.4), ACCENT)
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


def _rcontacts(g):
    parts = [f"Ph: {g('phone')}" if g("phone") else "",
             f"Mob: {g('mobile')}" if g("mobile") else "",
             g("email") if g("email") else ""]
    return " | ".join(p for p in parts if p)


def _rregs(g):
    parts = [f"PHC Reg #: {g('phc_reg_no')}" if g("phc_reg_no") else "",
             f"Lab Reg #: {g('lab_reg_no')}" if g("lab_reg_no") else ""]
    return " | ".join(p for p in parts if p)


def _report_header(d: Doc, con, g, r):
    """Full running header: letterhead + small patient card. Returns body-top y."""
    from . import report as R
    x0 = d.ml
    y = _report_letterhead(d, g, x0, d.mt)
    y += 3
    ch = _patient_card(d, x0, y, R._patient_pairs(r),
                       card_pad=(2.4, 5), gap=(1.6, 4), l_pt=6.6, v_pt=8.4,
                       radius=5, border=BORDER)
    return y + ch + 3


def _report_footer(d: Doc, con, g, page_no, total):
    """Running footer: signatures + footer line + dept band + Page X of Y."""
    x0 = d.ml
    sigs = [(g(f"signatory_{i}_name"), g(f"signatory_{i}_title")) for i in (1, 2)]
    sigs = [(n, t) for n, t in sigs if n]
    band = g("dept_band")
    fline = g("report_footer")
    # build bottom-up from page bottom (+4mm: sit the footer a little lower on the page)
    yb = A4_H_MM - d.mb + 4
    # Page X of Y (bottom-right, below everything)
    d.text(x0, yb - 4, d.content_w, 4, f"Page {page_no} of {total}", _font(7), FAINT,
           Qt.AlignRight | Qt.AlignVCenter)
    cy = yb - 8
    if band:
        d.text(x0, cy, d.content_w, 4, band, _font(7.3, bold=True, spacing_px=0.3), TEAL,
               Qt.AlignHCenter | Qt.AlignVCenter)
        cy -= 4.5
    if fline:
        d.text(x0 + 17, cy, d.content_w - 34, 4, fline, _font(7.3), MUTED,
               Qt.AlignHCenter | Qt.AlignVCenter)
        d.hline(x0 + 17, cy - 0.5, d.content_w - 34, BORDER, 1)
        cy -= 5
    if sigs:
        sw = (d.content_w - 34) / len(sigs)
        for i, (n, t) in enumerate(sigs):
            sx = x0 + 17 + i * sw
            # signatory (doctor) name — larger + bold so it reads as the signature
            d.text(sx, cy - 5.2, sw, 4.5, n, _font(10, bold=True), INK, Qt.AlignHCenter | Qt.AlignTop)
            d.text(sx, cy - 0.4, sw, 3.5, t, _font(7.3), MUTED, Qt.AlignHCenter | Qt.AlignTop)


def _ref_lines(res, sex):
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


def _measure_test(d: Doc, con, item, sex, receipt):
    """Return a layout dict for one (non-culture) test: title + columns + rows,
    with per-row heights, so we can paginate."""
    from . import report as R
    results = con.execute(
        """SELECT res.*, tp.ref_male AS p_male, tp.ref_female AS p_female
           FROM results res LEFT JOIN test_parameters tp ON tp.id = res.parameter_id
           WHERE res.receipt_item_id=? ORDER BY res.seq""", (item["id"],)).fetchall()
    head = con.execute("SELECT report_head, method_note FROM tests WHERE id=?",
                       (item["test_id"],)).fetchone()
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
    name_f = _font(8.6)            # test name
    ref_f = _font(7.8)
    for res in results:
        if "hidden" in res.keys() and res["hidden"]:
            continue
        if (res["part_type"] or "N").upper() == "H":
            rows.append({"kind": "subhead", "text": res["name"] or "", "h": 5.2})
            continue
        name = (res["name"] or "").strip()
        val = (str(res["value"]).strip() if res["value"] is not None else "")
        if not name and not val:
            continue
        ref_ls, flag = _ref_lines(res, sex)
        pid = res["parameter_id"] if "parameter_id" in res.keys() else None
        h_name = d.text_height(name, name_f, cw["test"] - 4)
        h_ref = sum(d.text_height(l, ref_f, cw["ref"] - 4) for l in ref_ls)
        rh = max(h_name, h_ref, 5.0) + 2.4
        rows.append({"kind": "row", "name": name, "ref_lines": ref_ls, "flag": flag,
                     "unit": res["units"] or "", "pid": pid, "value": res["value"],
                     "hist": [m.get(pid) for m in hist_maps], "h": rh})
    return {"title": title, "cw": cw, "hist_labels": hist_labels, "cur_label": cur_label,
            "rows": rows, "head": head, "item": item}


def _draw_test_table(d: Doc, lay, x0, y):
    """Draw the title bar + as many rows as fit; returns (y_after, remaining_rows).
    remaining_rows is a list to continue on the next page (header repeats)."""
    cw = lay["cw"]
    body_bottom = A4_H_MM - d.mb - REPORT_FOOTER_MM + 24  # body may use most of page
    # title bar
    d.top_rounded(x0, y, d.content_w, 6.5, 4, TEAL)
    d.text(x0 + 4, y, d.content_w - 8, 6.5, lay["title"], _font(11, bold=True), "#ffffff",
           Qt.AlignLeft | Qt.AlignVCenter)
    y += 6.5
    # header row
    cols = [("TEST", cw["test"], Qt.AlignLeft), ("REFERENCE RANGE", cw["ref"], Qt.AlignHCenter),
            ("UNIT", cw["unit"], Qt.AlignHCenter)]
    valcols = lay["hist_labels"] + [None]   # None => current
    each = (d.content_w - cw["test"] - cw["ref"] - cw["unit"]) / len(valcols)
    th_h = 11.0   # tall enough for "CURRENT" + a two-line date without clipping
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
            d.text(cx, y + 4.6, each, 6.0, dd, _font(6.2), "#ffffff",
                   Qt.AlignHCenter | Qt.AlignTop)
        else:
            d.text(cx, y, each, th_h, _fmt_one(vl), _font(6.4), "#ffffff",
                   Qt.AlignHCenter | Qt.AlignVCenter)
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
            d.text(x0 + 2, y, ncols_w - 4, rh, row["text"], _font(8.6, bold=True), TEAL_DARK,
                   Qt.AlignLeft | Qt.AlignVCenter)
            y += rh
            i += 1
            continue
        if even:
            d.fill_rect(x0, y, ncols_w, rh, LIGHT)
        even = not even
        cx = x0
        # test name
        d.rect(cx, y, cw["test"], rh, BORDER, 1)
        d.text(cx + 2, y, cw["test"] - 4, rh, row["name"], name_f, INK,
               Qt.AlignLeft | Qt.AlignVCenter, wrap=True)
        cx += cw["test"]
        # ref (possibly 2 lines)
        d.rect(cx, y, cw["ref"], rh, BORDER, 1)
        nlines = len(row["ref_lines"])
        lh = rh / max(nlines, 1)
        for k, line in enumerate(row["ref_lines"]):
            d.text(cx + 2, y + k * lh, cw["ref"] - 4, lh, line, ref_f, MUTED,
                   Qt.AlignHCenter | Qt.AlignVCenter)
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


def _draw_value(d: Doc, x, y, w, h, value, flag, font):
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


def _fmt_two(iso):
    from datetime import datetime
    s = (iso or "")[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d %b\n%Y")
    except ValueError:
        return s


def _fmt_one(iso):
    from datetime import datetime
    s = (iso or "")[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        return s


def _draw_blocks_after_table(d: Doc, lay, x0, y):
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
        d.text(x0 + 3, y + 2, inner, bh, f"Remarks: {rem}", bf, INK,
               Qt.AlignLeft | Qt.AlignTop, wrap=True)
        y += bh
    head = lay["head"]
    if head and head["method_note"]:
        import re
        note = re.sub(r"[ \t]*\n[ \t]*\n+", "\n", head["method_note"].replace("\r", ""))
        note = re.sub(r"[ \t]{2,}", " ", note).strip()
        y += 2.5
        d.text(x0, y, d.content_w, 40, f"Method / Comments: {note}", _font(7.5), MUTED,
               Qt.AlignLeft | Qt.AlignTop, wrap=True)
    return y


def build_report(con, receipt_id: int, device=None, images=False):
    from . import report as R
    g = R._g(con)
    r = con.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
    items = con.execute("SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY id",
                        (receipt_id,)).fetchall()
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
    total_pages = max(1, len(layouts))   # one test per page (overflow adds pages, rare)

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
                d.new_page(); page_no += 1
                body_top = _report_header(d, con, g, r)
                lay2 = dict(lay); lay2["rows"] = remaining
                y, remaining = _draw_test_table(d, lay2, d.ml, body_top)
            _draw_blocks_after_table(d, lay, d.ml, y)
        _report_footer(d, con, g, page_no, max(total_pages, page_no))
    if not layouts:
        body_top = _report_header(d, con, g, r)
        d.text(d.ml, body_top + 10, d.content_w, 10, "No tests on this receipt.",
               _font(10), MUTED)
        _report_footer(d, con, g, 1, 1)
    return d.tobytes()


def _draw_culture(d: Doc, con, item, x0, y):
    head = con.execute("SELECT report_head, method_note FROM tests WHERE id=?",
                       (item["test_id"],)).fetchone()
    title = (head["report_head"] if head and head["report_head"] else item["test_name"]).title()
    d.top_rounded(x0, y, d.content_w, 6.5, 4, TEAL)
    d.text(x0 + 4, y, d.content_w - 8, 6.5, title, _font(11, bold=True), "#ffffff",
           Qt.AlignLeft | Qt.AlignVCenter)
    y += 6.5
    cur = con.execute("SELECT * FROM cultures WHERE receipt_item_id=? ORDER BY id DESC LIMIT 1",
                      (item["id"],)).fetchone()
    if not cur:
        d.text(x0 + 2, y + 2, d.content_w, 6, "No culture result entered.", _font(8.6), MUTED)
        return y + 8
    for label, val in (("Specimen", cur["specimen"]), ("Growth", cur["growth"]),
                       ("Organism", cur["organism"]), ("Colony count", cur["colony_count"]),
                       ("Gram stain", cur["gram_stain"]), ("ZN stain", cur["zn_stain"])):
        if not val:
            continue
        rh = 6.5
        d.rect(x0, y, d.content_w * 0.3, rh, BORDER, 1)
        d.text(x0 + 2, y, d.content_w * 0.3 - 4, rh, label, _font(8.6), INK, Qt.AlignLeft | Qt.AlignVCenter)
        d.rect(x0 + d.content_w * 0.3, y, d.content_w * 0.7, rh, BORDER, 1)
        d.text(x0 + d.content_w * 0.3 + 2, y, d.content_w * 0.7 - 4, rh, str(val), _font(8.6, bold=True),
               INK, Qt.AlignLeft | Qt.AlignVCenter)
        y += rh
    sens = con.execute("SELECT antibiotic, result FROM culture_sensitivity WHERE culture_id=? "
                       "ORDER BY antibiotic", (cur["id"],)).fetchall()
    if sens:
        y += 3
        colour = {"S": GREEN, "I": AMBER, "R": RED}
        full = {"S": "Sensitive", "I": "Intermediate", "R": "Resistant"}
        d.fill_rect(x0, y, d.content_w, 7, TEAL)
        d.text(x0 + 2, y, d.content_w * 0.5, 7, "ANTIBIOTIC", _font(7, bold=True), "#ffffff",
               Qt.AlignLeft | Qt.AlignVCenter)
        d.text(x0 + d.content_w * 0.5, y, d.content_w * 0.5, 7, "SENSITIVITY", _font(7, bold=True),
               "#ffffff", Qt.AlignLeft | Qt.AlignVCenter)
        y += 7
        for s in sens:
            rh = 6.5
            res = (s["result"] or "").upper()
            d.rect(x0, y, d.content_w * 0.5, rh, BORDER, 1)
            d.text(x0 + 2, y, d.content_w * 0.5 - 4, rh, s["antibiotic"] or "", _font(8.6), INK,
                   Qt.AlignLeft | Qt.AlignVCenter)
            d.rect(x0 + d.content_w * 0.5, y, d.content_w * 0.5, rh, BORDER, 1)
            d.text(x0 + d.content_w * 0.5 + 2, y, d.content_w * 0.5 - 4, rh,
                   f"{res} — {full.get(res, '')}", _font(8.6, bold=True), colour.get(res, INK),
                   Qt.AlignLeft | Qt.AlignVCenter)
            y += rh
    return y


def build_test_page(printer_name: str = "", device=None):
    """A small printer-test page (native)."""
    from datetime import datetime
    d = Doc(margin_mm=(20, 20, 20, 20), device=device)
    x0 = d.ml
    y = d.mt
    d.rounded(x0, y, d.content_w, 60, 8, border=TEAL, border_px=2)
    d.text(x0 + 8, y + 6, d.content_w - 16, 10, "LabDesk — Printer Test",
           _font(20, bold=True), TEAL)
    d.text(x0 + 8, y + 20, d.content_w - 16, 8, "If you can read this, your printer is working.",
           _font(12), INK)
    target = printer_name or "Ask each time (print dialog)"
    when = datetime.now().strftime("%d %b %Y %H:%M")
    d.text(x0 + 8, y + 32, d.content_w - 16, 6, f"Printer: {target}", _font(10), MUTED)
    d.text(x0 + 8, y + 38, d.content_w - 16, 6, when, _font(10), MUTED)
    d.text(x0 + 8, y + 47, d.content_w - 16, 8, "✓ ↑ ↓ Rs. 1,234.50",
           _font(13, bold=True), TEAL)
    return d.tobytes()


def render_pages(con, receipt_id: int, kind: str):
    """Render a document to a list of QImage pages (on-screen preview; no QtPdf)."""
    if kind == "receipt":
        return build_receipt(con, receipt_id, images=True)
    return build_report(con, receipt_id, images=True)
