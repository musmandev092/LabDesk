"""Native Qt rendering of the lab report & cash receipt (QPainter → QPdfWriter).

A pixel-faithful reproduction of the former WeasyPrint HTML/CSS design, using only
Qt (which the app already bundles) — no WeasyPrint / Pango / Cairo / fontTools /
Pillow. All data/business logic still lives in report.py; this module only draws.

Coordinate model: paint at 300 dpi, position everything in millimetres. Helpers
mm() (mm→device units) and px() (CSS px@96 → mm) map the old CSS values exactly.

This package was split out of a single render.py module; ``__init__`` re-exports the
complete former public API so ``from . import render`` / ``render.X`` / ``from
.render import X`` keep working unchanged.
"""

from __future__ import annotations

import contextlib

# Re-export the PySide names the former flat module exposed at module level, so
# ``dir(render)`` (and any incidental ``render.QRectF`` style access) stays stable.
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QMarginsF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPainterPath,
    QPdfWriter,
    QPen,
    qAlpha,
    qBlue,
    qGreen,
    qRed,
)

# Bind the sibling ``report`` module as ``render.report`` so the lazy
# ``from . import report as R`` inside the submodules resolves to labdesk.report
# (it is a sibling module, not labdesk.render.report).
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

# ``_FAMILY`` is module-level mutable state in fonts.py; expose it for parity with
# the former flat module (some tools/tests introspect it).
from .fonts import _FAMILY, _ensure_app, _family, _font, preload
from .image import autocrop_image
from .preview import build_test_page, render_pages
from .primitives import Doc
from .receipt import build_receipt

# build_report lives in report_doc but is part of the public surface.
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

# ``__all__`` lists the entire former public surface of the flat render.py module
# (public API + the underscore helpers other modules reach for + the incidental
# PySide / stdlib names that ``dir(render)`` used to expose). Listing every
# re-exported name here keeps ``dir(render)`` byte-stable AND tells ruff these
# imports are deliberately re-exported (so they are not flagged as F401).
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
    "Doc",
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
    "autocrop_image",
    "build_receipt",
    "build_report",
    "build_test_page",
    "mm",
    "preload",
    "px",
    "render_pages",
    # underscore helpers other modules / tools reference via ``render._x``
    "_FAMILY",
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
    # incidental names the former flat module exposed at module level
    "Path",
    "QBuffer",
    "QByteArray",
    "QColor",
    "QFont",
    "QFontDatabase",
    "QFontMetricsF",
    "QImage",
    "QMarginsF",
    "QPageLayout",
    "QPageSize",
    "QPainter",
    "QPainterPath",
    "QPdfWriter",
    "QPen",
    "QRectF",
    "Qt",
    "contextlib",
    "qAlpha",
    "qBlue",
    "qGreen",
    "qRed",
]
