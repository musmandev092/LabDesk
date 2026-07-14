"""Shared constants & unit helpers for the native Qt renderer (300 dpi, mm-based)."""

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


# CarePoint Health Clinic brand palette
TEAL = "#1b2a6b"
TEAL_DARK = "#142052"
ACCENT = "#00b4b4"
GREEN = "#059669"
AMBER = "#d97706"
RED = "#dc2626"
INK = "#1b2a6b"
MUTED = "#5a6a8a"
FAINT = "#9aa7be"
LIGHT = "#f0f8f8"
BORDER = "#c3d0e0"
BORDER2 = "#e2eaf2"
SUBHEAD_BG = "#dceff0"

REPORT_HEADER_MM = 57.0  # matches CSS @page margin
REPORT_FOOTER_MM = 27.0
