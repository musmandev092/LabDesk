"""On-screen preview & printer-test page (top of the render layering)."""

from __future__ import annotations

from PySide6.QtGui import QImage

from .constants import INK, MUTED, TEAL
from .fonts import _font
from .primitives import Doc
from .receipt import build_receipt
from .report_doc import build_report


def build_test_page(printer_name: str = "", device=None) -> bytes | list[QImage] | None:
    """A small printer-test page (native)."""
    from datetime import datetime

    d = Doc(margin_mm=(20, 20, 20, 20), device=device)
    x0 = d.ml
    y = d.mt
    d.rounded(x0, y, d.content_w, 60, 8, border=TEAL, border_px=2)
    d.text(
        x0 + 8,
        y + 6,
        d.content_w - 16,
        10,
        "LabDesk — Printer Test",
        _font(20, bold=True),
        TEAL,
    )
    d.text(
        x0 + 8,
        y + 20,
        d.content_w - 16,
        8,
        "If you can read this, your printer is working.",
        _font(12),
        INK,
    )
    target = printer_name or "Ask each time (print dialog)"
    when = datetime.now().strftime("%d %b %Y %H:%M")
    d.text(x0 + 8, y + 32, d.content_w - 16, 6, f"Printer: {target}", _font(10), MUTED)
    d.text(x0 + 8, y + 38, d.content_w - 16, 6, when, _font(10), MUTED)
    d.text(
        x0 + 8,
        y + 47,
        d.content_w - 16,
        8,
        "✓ ↑ ↓ Rs. 1,234.50",
        _font(13, bold=True),
        TEAL,
    )
    return d.tobytes()


def render_pages(
    con, receipt_id: int, kind: str, pack: bool = True
) -> bytes | list[QImage] | None:
    """Render a document to a list of QImage pages (on-screen preview; no QtPdf).
    Reports rasterise at half print resolution (``img_scale=0.5``) — 4x fewer pixels
    and memory for a snappier preview; the on-screen layout is identical, and print /
    PDF export still render at full 300 dpi."""
    if kind == "receipt":
        return build_receipt(con, receipt_id, images=True)
    return build_report(con, receipt_id, images=True, pack=pack, img_scale=0.5)
