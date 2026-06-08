"""Shared constants & unit helpers for the native Qt renderer.

Coordinate model: paint at 300 dpi, position everything in millimetres. Helpers
mm() (mm→device units) and px() (CSS px@96 → mm) map the old CSS values exactly.
"""

from __future__ import annotations

from pathlib import Path

ASSETS = Path(__file__).parent.with_name("assets")
INTER_TTF = ASSETS / "fonts" / "Inter.ttf"

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

REPORT_HEADER_MM = 57.0  # reserved running-header band (matches CSS @page margin)
REPORT_FOOTER_MM = 27.0  # reserved running-footer band
