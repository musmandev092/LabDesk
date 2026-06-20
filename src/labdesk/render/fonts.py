"""Bundled-font loading and QFont construction for the native Qt renderer."""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase

from .constants import INTER_TTF

_FAMILY = None


def _ensure_app() -> None:
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


def preload() -> None:
    """Load the bundled font once on the main thread (call at app startup) so the
    PDF-building worker thread never touches QFontDatabase off-thread."""
    _family()


def _font(size_pt: float, *, bold: bool = False, spacing_px: float = 0.0) -> QFont:
    f = QFont(_family())
    f.setPointSizeF(size_pt)
    f.setBold(bold)
    f.setHintingPreference(QFont.PreferNoHinting)
    if spacing_px:
        # CSS letter-spacing px@96 → points (font logical units are points here)
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing_px / 96.0 * 72.0)
    return f
