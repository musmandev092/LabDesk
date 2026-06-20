"""Shared constants & unit helpers for the native Qt renderer.

Coordinate model: paint at 300 dpi, position everything in millimetres. Helpers
mm() (mm→device units) and px() (CSS px@96 → mm) map the old CSS values exactly.
"""

from __future__ import annotations

from .._resources import package_root

ASSETS = package_root() / "assets"
INTER_TTF = ASSETS / "fonts" / "Inter.ttf"

DPI = 300
A4_W_MM, A4_H_MM = 210.0, 297.0


def mm(v: float) -> float:
    return v / 25.4 * DPI


def px(v: float) -> float:
    """CSS px (at 96 dpi reference) → mm."""
    return v / 96.0 * 25.4


# palette — CarePoint Health Clinic brand scheme.
# TEAL is the primary brand colour (title bars, lab name, header/footer bands);
# ACCENT is the teal highlight (subtitle, conclusion accent bar). Semantic flag
# colours (GREEN/AMBER/RED) are kept for out-of-range / polarity cues.
TEAL = "#1b2a6b"  # primary navy
TEAL_DARK = "#142052"  # darker navy — title gridlines, current-column fill
ACCENT = "#00b4b4"  # teal accent
GREEN = "#059669"
AMBER = "#d97706"
RED = "#dc2626"
INK = "#1b2a6b"  # text-primary (navy)
MUTED = "#5a6a8a"  # text-secondary
FAINT = "#9aa7be"  # faint labels (lighter secondary)
LIGHT = "#f0f8f8"  # surface — teal-tinted row striping / card fill
BORDER = "#c3d0e0"
BORDER2 = "#e2eaf2"
SUBHEAD_BG = "#dceff0"  # teal-tinted subhead / impression band (distinct from LIGHT)

REPORT_HEADER_MM = 57.0  # reserved running-header band (matches CSS @page margin)
REPORT_FOOTER_MM = 27.0  # reserved running-footer band
