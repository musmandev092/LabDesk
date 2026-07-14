"""Native Qt rendering of the lab report & cash receipt (QPainter → QPdfWriter); re-exports the former flat render.py API."""

from __future__ import annotations

# Bind as render.report so submodules' ``from . import report as R`` resolves to labdesk.report (a sibling, not labdesk.render.report).
from .. import report as report
from ._shared import _patient_card, _wrap_value
from .constants import (
    A4_H_MM,
    A4_W_MM,
    ACCENT,
    AMBER,
    ASSETS,
    BORDER,
    BORDER2,
    DPI,
    FAINT,
    GREEN,
    INK,
    INTER_TTF,
    LIGHT,
    MUTED,
    RED,
    REPORT_FOOTER_MM,
    REPORT_HEADER_MM,
    SUBHEAD_BG,
    TEAL,
    TEAL_DARK,
    mm,
    px,
)

from .fonts import _FAMILY, _ensure_app, _family, _font, preload
from .image import autocrop_image
from .preview import build_test_page, render_pages
from .primitives import Doc
from .receipt import build_receipt
from .report_doc import (
    _draw_blocks_after_table,
    _draw_culture,
    _draw_test_table,
    _draw_value,
    _fmt_one,
    _fmt_two,
    _measure_test,
    _rcontacts,
    _ref_lines,
    _report_footer,
    _report_header,
    _report_letterhead,
    _rregs,
    build_report,
)

__all__ = [
    # public API
    "A4_H_MM",
    "A4_W_MM",
    "ACCENT",
    "AMBER",
    "ASSETS",
    "BORDER",
    "BORDER2",
    "DPI",
    "FAINT",
    "GREEN",
    "INK",
    "INTER_TTF",
    "LIGHT",
    "MUTED",
    "RED",
    "REPORT_FOOTER_MM",
    "REPORT_HEADER_MM",
    "SUBHEAD_BG",
    "TEAL",
    "TEAL_DARK",
    # underscore helpers other modules / tools reference via ``render._x``
    "_FAMILY",
    "Doc",
    "_draw_blocks_after_table",
    "_draw_culture",
    "_draw_test_table",
    "_draw_value",
    "_ensure_app",
    "_family",
    "_fmt_one",
    "_fmt_two",
    "_font",
    "_measure_test",
    "_patient_card",
    "_rcontacts",
    "_ref_lines",
    "_report_footer",
    "_report_header",
    "_report_letterhead",
    "_rregs",
    "_wrap_value",
    "autocrop_image",
    "build_receipt",
    "build_report",
    "build_test_page",
    "mm",
    "preload",
    "px",
    "render_pages",
]
