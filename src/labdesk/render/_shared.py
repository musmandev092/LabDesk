"""Shared drawing helpers: letterhead value-wrapping + the patient card."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetricsF

from .constants import BORDER2, INK, LIGHT, MUTED, mm
from .fonts import _font
from .primitives import Doc


# ---------------------------------------------------------------------------
# Shared: letterhead + patient card
# ---------------------------------------------------------------------------
def _wrap_value(fm: QFontMetricsF, text: str, max_px: float, max_lines: int = 2) -> list[str]:
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
    lines = [
        ln if fm.horizontalAdvance(ln) <= max_px else fm.elidedText(ln, Qt.ElideRight, max_px)
        for ln in lines
    ]
    if len(lines) > max_lines:
        keep = lines[:max_lines]
        keep[-1] = fm.elidedText(" ".join(lines[max_lines - 1 :]), Qt.ElideRight, max_px)
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
        n = max(
            (len(wrapped[r * cols + c][1]) for c in range(cols) if r * cols + c < len(wrapped)),
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
            d.text(cx, cy, col_w, l_h, lbl.upper(), l_font, MUTED, Qt.AlignLeft | Qt.AlignVCenter)
            vy = cy + l_h + 0.6
            for ln in lines:
                d.text(cx, vy, vw, v_h, ln, v_font, INK, Qt.AlignLeft | Qt.AlignVCenter)
                vy += v_h + line_gap
        cy += row_h[r] + gv
    return card_h
