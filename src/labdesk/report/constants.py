"""Report & receipt palette + asset paths.

Bottom layer of the report package: pure constants, no intra-package imports.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# palette — matches the supplied design mockups
# ---------------------------------------------------------------------------
TEAL = "#005f73"  # report --brand-primary
TEAL_DARK = "#004d5c"  # highlighted CURRENT column
ACCENT = "#0a9396"  # report departments line
SLATE = "#005f73"  # receipt --brand-primary
BLUE = "#0a9396"  # receipt --brand-accent
GREEN = "#059669"
AMBER = "#d97706"  # below range ↓
RED = "#dc2626"  # above range ↑
BODY = "#1e293b"

ARROW_UP = "↑"  # above reference range (High)
ARROW_DOWN = "↓"  # below reference range (Low)

ASSETS = Path(__file__).parent.parent / "assets"
INTER_TTF = ASSETS / "fonts" / "Inter.ttf"
