"""Shared drawing helpers: letterhead value-wrapping + the patient card."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetricsF, QImage

from .constants import BORDER2, DPI, INK, LIGHT, MUTED, mm, px
from .fonts import _font
from .image import autocrop_image
from .primitives import Doc


def centered_logo_left(
    d: Doc, logo_path: str, x0: float, h_px: float = 48
) -> float | None:
    """X (mm) where a logo of height `h_px`, centred across the content width, begins — or None if no usable logo."""
    p = (logo_path or "").strip()
    if not p or not Path(p).exists():
        return None
    img = QImage(str(p))
    if img.isNull():
        return None
    img = autocrop_image(img)
    scaled = img.scaledToHeight(int(mm(px(h_px))), Qt.SmoothTransformation)
    w_mm = scaled.width() / DPI * 25.4
    return x0 + (d.content_w - w_mm) / 2


def fit_lab_name_font(
    d: Doc, text: str, base_pt: float, avail_mm: float, *, min_pt: float = 10.0
):
    """Bold title font shrunk just enough that `text` fits within `avail_mm` on one line (down to `min_pt`)."""
    avail_dev = mm(max(0.0, avail_mm))
    pt = base_pt
    f = _font(pt, bold=True, spacing_px=-0.5)
    while pt > min_pt and d.fm(f).horizontalAdvance(text or "") > avail_dev:
        pt -= 0.5
        f = _font(pt, bold=True, spacing_px=-0.5)
    return f


def _wrap_value(
    fm: QFontMetricsF, text: str, max_px: float, max_lines: int = 2
) -> list[str]:
    """Greedy word-wrap `text` to `max_px` across up to `max_lines`; elides the last line with '…' on overflow."""
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
    lines = [
        ln
        if fm.horizontalAdvance(ln) <= max_px
        else fm.elidedText(ln, Qt.ElideRight, max_px)
        for ln in lines
    ]
    if len(lines) > max_lines:
        keep = lines[:max_lines]
        keep[-1] = fm.elidedText(
            " ".join(lines[max_lines - 1 :]), Qt.ElideRight, max_px
        )
        lines = keep
    return lines


def _patient_card(
    d: Doc,
    x: float,
    y: float,
    pairs: list[tuple[str, object]],
    *,
    card_pad: tuple[float, float] = (5, 6),
    gap: tuple[float, float] = (4, 6),
    l_pt: float = 7.5,
    v_pt: float = 9.5,
    radius: float = 6,
    border: str = BORDER2,
    max_value_lines: int = 2,
) -> float:
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
    # long values spill into the column gap (not last column) so names don't clip
    wrapped = []
    for i, (lbl, val) in enumerate(pairs):
        c = i % cols
        vw = col_w + (gh - 1) if c < cols - 1 else col_w
        lines = _wrap_value(vfm, str(val) if val else "", mm(vw), max_value_lines)
        wrapped.append((lbl, lines, vw))
    # row height adapts to the tallest (most-wrapped) value in that row
    row_h = []
    for r in range(rows):
        n = max(
            (
                len(wrapped[r * cols + c][1])
                for c in range(cols)
                if r * cols + c < len(wrapped)
            ),
            default=1,
        )
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
            d.text(
                cx,
                cy,
                col_w,
                l_h,
                lbl.upper(),
                l_font,
                MUTED,
                Qt.AlignLeft | Qt.AlignVCenter,
            )
            vy = cy + l_h + 0.6
            for ln in lines:
                d.text(cx, vy, vw, v_h, ln, v_font, INK, Qt.AlignLeft | Qt.AlignVCenter)
                vy += v_h + line_gap
        cy += row_h[r] + gv
    return card_h
