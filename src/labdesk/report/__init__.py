"""Report & receipt generation.

Two documents — a branded lab report (letterhead, rounded patient card, teal
cumulative results table with a highlighted CURRENT column and inline ↑/↓ flags)
and a "CASH RECEIPT" (amount-in-words box + totals panel). They are drawn
natively with Qt (see render.py: QPainter → QPdfWriter), so the app needs no
WeasyPrint/Pango/Cairo/fontTools/Pillow. Inter is bundled (assets/fonts) and
embedded in the PDF. The HTML builders below are retained for content tests and
are not used for rendering. Printing paints straight onto the QPrinter (vector,
no QtPdf round-trip); preview renders to image pages (no QtPdf viewer).

This is a package split out of the former ``report.py`` module. The public API
is re-exported here unchanged: every ``from . import report``, ``report.X(...)``,
``from .report import X`` and the render package's lazy ``report._g(...)`` keeps
working exactly as before. Single-underscore helpers used by other modules
(_flag, _esc, _amount_in_words, _g, _user_display, _contacts, _regs,
_patient_pairs, _history_for_item, _patient_card, _flag_arrow, _resolve_ref,
_fmt_date, …) remain importable as ``report.<name>``.
"""

from __future__ import annotations

# ``db`` and ``render`` are bound here as ``report.db`` / ``report.render`` because
# the package preserves the import cycle: report imports render at module level;
# render lazily imports report back.
from .. import db, render
from .constants import (
    ACCENT,
    AMBER,
    ARROW_DOWN,
    ARROW_UP,
    ASSETS,
    BLUE,
    BODY,
    GREEN,
    INTER_TTF,
    RED,
    SLATE,
    TEAL,
    TEAL_DARK,
)
from .content import (
    _contacts,
    _culture_section,
    _g,
    _history_for_item,
    _patient_card,
    _patient_pairs,
    _prev_impression,
    _regs,
    _report_section,
    _signatures,
    _user_display,
    _value_cell,
)
from .export import (
    _make_printer,
    _pdf_target,
    build_receipt_bytes,
    build_report_bytes,
    build_test_page_bytes,
    export_receipt_pdf,
    export_report_pdf,
    print_doc,
    print_receipt,
    print_report,
    print_test_page,
    save_report_pdf,
)
from .formatting import (
    _ONES,
    _TENS,
    _amount_in_words,
    _esc,
    _file_url,
    _flag,
    _flag_arrow,
    _fmt_date,
    _img,
    _method_block,
    _remarks_block,
    _resolve_ref,
    _three,
    _two,
)
from .html import (
    _RECEIPT_CSS,
    _REPORT_CSS,
    _doc,
    _font_face,
    build_receipt_html,
    build_report_html,
)
from .verify import report_fingerprint, verification_code, verify

__all__ = [
    # constants
    "ACCENT",
    "AMBER",
    "ARROW_DOWN",
    "ARROW_UP",
    "ASSETS",
    "BLUE",
    "BODY",
    "GREEN",
    "INTER_TTF",
    "RED",
    "SLATE",
    "TEAL",
    "TEAL_DARK",
    # formatting
    "_ONES",
    "_RECEIPT_CSS",
    # html
    "_REPORT_CSS",
    "_TENS",
    "_amount_in_words",
    # content
    "_contacts",
    "_culture_section",
    "_doc",
    "_esc",
    "_file_url",
    "_flag",
    "_flag_arrow",
    "_fmt_date",
    "_font_face",
    "_g",
    "_history_for_item",
    "_prev_impression",
    "_img",
    # export
    "_make_printer",
    "_method_block",
    "_patient_card",
    "_patient_pairs",
    "_pdf_target",
    "_regs",
    "_remarks_block",
    "_report_section",
    "_resolve_ref",
    "_signatures",
    "_three",
    "_two",
    "_user_display",
    "_value_cell",
    "build_receipt_bytes",
    "build_receipt_html",
    "build_report_bytes",
    "build_report_html",
    "build_test_page_bytes",
    # sibling modules bound for the import-cycle contract (report.db / report.render)
    "db",
    "export_receipt_pdf",
    "export_report_pdf",
    "print_doc",
    "print_receipt",
    "print_report",
    "print_test_page",
    "render",
    # verification (keyed HMAC report code)
    "report_fingerprint",
    "save_report_pdf",
    "verification_code",
    "verify",
]
