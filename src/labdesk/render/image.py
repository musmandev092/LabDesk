"""Logo autocrop — shared by the sidebar brand mark AND the printed letterhead."""

from __future__ import annotations

from PySide6.QtGui import QImage, qAlpha, qBlue, qGreen, qRed


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

    def near_bg(px: int) -> bool:
        a = qAlpha(px)
        if a < 16 and ba < 16:
            return True
        if abs(a - ba) > 40:
            return False
        return (
            abs(qRed(px) - br) <= TOL
            and abs(qGreen(px) - bgc) <= TOL
            and abs(qBlue(px) - bb) <= TOL
        )

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
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(w - 1, right + pad)
    bot = min(h - 1, bot + pad)
    return img.copy(left, top, right - left + 1, bot - top + 1)
