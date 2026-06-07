"""Application-wide palette and stylesheet (light + dark themes)."""
from __future__ import annotations

from pathlib import Path

# checkmark glyph for ticked checkboxes (white check, reads on the teal fill in
# both themes). Path is injected into the QSS; falls back gracefully if missing.
_CHECK = Path(__file__).resolve().parent.parent / "assets" / "checkmark.png"

# Product (white-label) identity. The *lab's* own name is configured per-install
# via the first-run wizard; this is only the neutral product brand.
PRODUCT_NAME = "LabDesk"
PRODUCT_TAGLINE = "Laboratory Management System"

# Brand / accent colours — used directly by some widgets (dashboard stat cards,
# report colours). They read well on both light and dark surfaces, so they stay
# fixed; only the *surfaces* (backgrounds/text/borders) change between themes.
PRIMARY = "#0e7c86"
PRIMARY_DARK = "#0a5f67"
PRIMARY_LIGHT = "#e6f4f5"
ACCENT = "#1f9d55"
AMBER = "#b9770e"
DANGER = "#c0392b"
BG = "#eef1f4"
CARD = "#ffffff"
TEXT = "#152028"
MUTED = "#64727d"
BORDER = "#dde3e8"
SIDE_TOP = "#0c6b73"
SIDE_BOT = "#084a51"

# ---------------------------------------------------------------------------
# Theme palettes. Surface colours differ; the teal brand stays constant.
# ---------------------------------------------------------------------------
_LIGHT = {
    "bg": "#eef1f4", "card": "#ffffff", "text": "#152028", "muted": "#64727d",
    "border": "#dde3e8", "heading": "#0a5f67", "ghost_text": "#0a5f67",
    "primary": "#0e7c86", "primary_dark": "#0a5f67", "primary_light": "#e6f4f5",
    "danger": "#c0392b", "input_bg": "#ffffff", "alt": "#f7fafb",
    "header_bg": "#eaf1f2", "grid": "#eef1f3", "scroll": "#c2cccf",
    "scroll_hover": "#aab6ba", "tab_bg": "#e3eaeb", "disabled_bg": "#aebfc1",
    "disabled_text": "#f0f4f4", "listsep": "#f0f3f4", "side": "#084a51",
    "side_text": "#cfeaec", "side_sub": "#c8e9eb",
}
_DARK = {
    "bg": "#0f1720", "card": "#18222c", "text": "#e6edf2", "muted": "#9aa7b2",
    "border": "#2a3742", "heading": "#5fd0db", "ghost_text": "#5fd0db",
    "primary": "#0e7c86", "primary_dark": "#0c6b73", "primary_light": "#15323a",
    "danger": "#d9544a", "input_bg": "#121b23", "alt": "#1d2832",
    "header_bg": "#1c2731", "grid": "#243039", "scroll": "#3a4a56",
    "scroll_hover": "#4a5b68", "tab_bg": "#1c2731", "disabled_bg": "#2a3742",
    "disabled_text": "#6b7782", "listsep": "#243039", "side": "#08191d",
    "side_text": "#cfeaec", "side_sub": "#9fc7cb",
}
THEMES = {"light": _LIGHT, "dark": _DARK}


def build_qss(theme: str = "light") -> str:
    p = THEMES.get(theme, _LIGHT)
    _check_line = (f"image: url({_CHECK.as_posix()});" if _CHECK.exists() else "")
    return f"""
* {{
    font-family: "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 14px;
    color: {p['text']};
}}
QMainWindow, QDialog, QWidget#page {{ background: {p['bg']}; }}

QLabel#h1 {{ font-size: 22px; font-weight: 800; color: {p['heading']}; }}
QLabel#h2 {{ font-size: 15px; font-weight: 700; color: {p['text']}; }}
QLabel#muted {{ color: {p['muted']}; font-size: 13px; }}
QLabel#fieldlbl {{ color: {p['muted']}; font-size: 13px; }}

/* Header bar at the top of each page */
#PageHeader {{ background: transparent; border-bottom: 1px solid {p['border']}; }}

/* Sidebar (always a dark teal in both themes) */
#Sidebar {{ background: {p['side']}; }}
#Sidebar QPushButton {{
    text-align: left; padding: 12px 20px 12px 18px; border: none; color: {p['side_text']};
    background: transparent; font-size: 14px; font-weight: 600; border-left: 4px solid transparent;
}}
#Sidebar QPushButton:hover {{ background: rgba(255,255,255,0.08); color: white; }}
#Sidebar QPushButton:checked {{
    background: rgba(255,255,255,0.14); color: white;
    border-left: 4px solid #7ff0e3;
}}
#SidebarLogo {{ background: white; border-radius: 14px; padding: 10px; margin: 0 10px; }}
#SidebarBrand {{ color: white; font-size: 17px; font-weight: 800; padding: 4px 14px 2px; }}
#SidebarSub {{ color: {p['side_sub']}; font-size: 12px; padding: 0 14px 14px; qproperty-alignment: AlignCenter; }}
#SidebarUser {{ color: #dbf1f2; padding: 8px 18px; font-size: 13px; }}
QStatusBar {{ min-height: 24px; padding-left: 8px; }}

/* Cards */
QFrame#card {{ background: {p['card']}; border: 1px solid {p['border']}; border-radius: 12px; }}
QFrame#statcard {{ background: {p['card']}; border: 1px solid {p['border']}; border-radius: 12px; }}

/* Buttons — all carry a 1.5px border (transparent for filled ones) so filled
   and ghost buttons render at the exact same height and line up in a row. */
QPushButton {{
    background: {p['primary']}; color: white; border: 1.5px solid transparent; border-radius: 8px;
    padding: 9px 18px; font-weight: 700; min-height: 18px;
}}
QPushButton:hover {{ background: {p['primary_dark']}; }}
QPushButton:pressed {{ background: {p['primary_dark']}; }}
QPushButton:disabled {{ background: {p['disabled_bg']}; color: {p['disabled_text']}; }}
QPushButton#ghost {{ background: transparent; color: {p['ghost_text']}; border: 1.5px solid {p['primary']}; }}
QPushButton#ghost:hover {{ background: {p['primary_light']}; }}
QPushButton#danger {{ background: {p['danger']}; border: 1.5px solid transparent; }}
QPushButton#danger:hover {{ background: #99291c; }}
QPushButton#linkbtn {{ background: transparent; color: {p['ghost_text']}; border: none; padding: 6px; font-weight: 700; }}
QPushButton#linkbtn:hover {{ color: {p['primary']}; }}

/* Inputs */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {{
    background: {p['input_bg']}; border: 1.5px solid {p['border']}; border-radius: 8px; padding: 8px 10px;
    selection-background-color: {p['primary']}; selection-color: white;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border: 1.5px solid {p['primary']}; }}
QComboBox::drop-down, QDateEdit::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    border: none; width: 22px;
}}
QComboBox::down-arrow, QDateEdit::down-arrow {{
    image: none; width: 0; height: 0; margin-right: 8px;
    border-left: 5px solid transparent; border-right: 5px solid transparent;
    border-top: 6px solid {p['muted']};
}}
QComboBox QAbstractItemView {{
    background: {p['input_bg']}; border: 1px solid {p['border']};
    selection-background-color: {p['primary_light']}; selection-color: {p['text']}; outline: none;
}}
/* hide the broken/clipped spin steppers — values are typed */
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; height: 0; border: none; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 10px; }}

/* Checkboxes / radios — explicitly themed so they're clearly visible on dark
   (the default indicator washes out). Empty = outlined box; ticked = teal fill
   with a white check. */
QCheckBox, QRadioButton {{ spacing: 8px; color: {p['text']}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 18px; height: 18px; border: 1.5px solid {p['muted']};
    background: {p['input_bg']};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {p['primary']}; }}
QCheckBox::indicator:checked {{
    background: {p['primary']}; border-color: {p['primary']}; {_check_line}
}}
QRadioButton::indicator:checked {{
    background: {p['primary']}; border-color: {p['primary']};
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    border-color: {p['border']}; background: {p['bg']};
}}
QCheckBox:disabled, QRadioButton:disabled {{ color: {p['muted']}; }}

/* Tables */
QTableView, QTableWidget, QTreeView, QListWidget {{
    background: {p['card']}; border: 1px solid {p['border']}; border-radius: 10px;
    gridline-color: {p['grid']}; selection-background-color: {p['primary_light']};
    selection-color: {p['text']}; alternate-background-color: {p['alt']};
}}
QTableView::item:selected, QTableWidget::item:selected,
QTreeView::item:selected {{ background: {p['primary_light']}; color: {p['text']}; }}
QHeaderView::section {{
    background: {p['header_bg']}; color: {p['text']}; padding: 9px 8px; border: none;
    border-right: 1px solid {p['border']}; font-weight: 700;
}}
QTableView::item, QTableWidget::item {{ padding: 6px; }}
QListWidget::item {{ padding: 8px; border-bottom: 1px solid {p['listsep']}; }}
QListWidget::item:selected {{ background: {p['primary_light']}; color: {p['text']}; }}

QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 10px; background: {p['card']}; top: -1px; }}
QTabBar::tab {{
    padding: 9px 18px; background: {p['tab_bg']}; margin-right: 3px; color: {p['muted']};
    border-top-left-radius: 8px; border-top-right-radius: 8px; font-weight: 600;
}}
QTabBar::tab:selected {{ background: {p['card']}; color: {p['heading']}; font-weight: 700; }}

QScrollBar:vertical {{ width: 12px; background: transparent; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['scroll']}; border-radius: 6px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: {p['scroll_hover']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollArea {{ border: none; background: transparent; }}

/* Popup menus (right-click row menu, etc.) — themed so they don't fall back to
   a platform-white surface that washes out under the dark theme. Enabled items
   use full text colour; disabled (not-yet-available) items read as muted grey. */
QMenu {{
    background: {p['card']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: 8px; padding: 4px;
}}
QMenu::item {{ padding: 7px 22px 7px 16px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p['primary_light']}; color: {p['text']}; }}
QMenu::item:disabled {{ color: {p['muted']}; background: transparent; }}
QMenu::separator {{ height: 1px; background: {p['border']}; margin: 5px 10px; }}
QStatusBar {{ background: {p['card']}; color: {p['muted']}; border-top: 1px solid {p['border']}; }}
QSplitter::handle {{ background: transparent; width: 14px; }}

/* Setup wizard / login surfaces */
#authCard {{ background: {p['card']}; border: 1px solid {p['border']}; border-radius: 16px; }}
#authTitle {{ font-size: 24px; font-weight: 800; color: {p['heading']}; }}
#brandMark {{
    background: {p['primary']}; color: white; font-size: 26px; font-weight: 800;
    border-radius: 16px;
}}
"""


# Default (light) stylesheet — kept for any code that imports QSS directly.
QSS = build_qss("light")
