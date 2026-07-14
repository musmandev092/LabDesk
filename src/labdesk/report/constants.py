"""Report & receipt palette + asset paths."""

from __future__ import annotations

from .._resources import package_root

TEAL = "#005f73"  # report --brand-primary
TEAL_DARK = "#004d5c"  # highlighted CURRENT column
ACCENT = "#0a9396"  # report departments line
SLATE = "#005f73"  # receipt --brand-primary
BLUE = "#0a9396"  # receipt --brand-accent
GREEN = "#059669"
AMBER = "#d97706"  # below range
RED = "#dc2626"  # above range
BODY = "#1e293b"

ARROW_UP = "↑"
ARROW_DOWN = "↓"

ASSETS = package_root() / "assets"
INTER_TTF = ASSETS / "fonts" / "Inter.ttf"
