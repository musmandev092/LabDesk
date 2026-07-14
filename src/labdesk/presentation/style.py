"""Application-wide palette and stylesheet (light + dark themes)."""

from __future__ import annotations

from .._resources import package_root

# checkmark glyph for ticked checkboxes; injected into the QSS, falls back if missing
_CHECK = package_root() / "assets" / "checkmark.png"

# neutral product brand; the lab's own name is set per-install via the setup wizard
PRODUCT_NAME = "LabDesk"
PRODUCT_TAGLINE = "Laboratory Management System"

# developer credit — single source of truth for sidebar/login/About
DEVELOPER = "M Usman"
DEVELOPER_GITHUB = "github.com/mosman092"
DEVELOPER_EMAILS = ("musmaniqbalbaloch@gmail.com", "mosman092@hotmail.com")

# brand/accent colours stay fixed across themes; only surfaces change
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

# theme palettes — surface colours differ; the teal brand stays constant
_LIGHT = {
    "bg": "#eef1f4",
    "card": "#ffffff",
    "text": "#152028",
    "muted": "#64727d",
    "border": "#dde3e8",
    "heading": "#0a5f67",
    "ghost_text": "#0a5f67",
    "primary": "#0e7c86",
    "primary_dark": "#0a5f67",
    "primary_light": "#e6f4f5",
    "danger": "#c0392b",
    "input_bg": "#ffffff",
    "alt": "#f7fafb",
    "header_bg": "#eaf1f2",
    "grid": "#eef1f3",
    "scroll": "#c2cccf",
    "scroll_hover": "#aab6ba",
    "tab_bg": "#e3eaeb",
    "disabled_bg": "#aebfc1",
    "disabled_text": "#f0f4f4",
    "listsep": "#f0f3f4",
    "side": "#084a51",
    "side_text": "#cfeaec",
    "side_sub": "#c8e9eb",
}
_DARK = {
    "bg": "#0f1720",
    "card": "#18222c",
    "text": "#e6edf2",
    "muted": "#9aa7b2",
    "border": "#2a3742",
    "heading": "#5fd0db",
    "ghost_text": "#5fd0db",
    "primary": "#0e7c86",
    "primary_dark": "#0c6b73",
    "primary_light": "#15323a",
    "danger": "#d9544a",
    "input_bg": "#121b23",
    "alt": "#1d2832",
    "header_bg": "#1c2731",
    "grid": "#243039",
    "scroll": "#3a4a56",
    "scroll_hover": "#4a5b68",
    "tab_bg": "#1c2731",
    "disabled_bg": "#2a3742",
    "disabled_text": "#6b7782",
    "listsep": "#243039",
    "side": "#08191d",
    "side_text": "#cfeaec",
    "side_sub": "#9fc7cb",
}
THEMES = {"light": _LIGHT, "dark": _DARK}


def build_qss(theme: str = "light") -> str:
    p = THEMES.get(theme, _LIGHT)
    _check_line = f"image: url({_CHECK.as_posix()});" if _CHECK.exists() else ""
    return f"""
* {{
    font-family: "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 14px;
    color: {p["text"]};
}}
QMainWindow, QDialog, QWidget#page {{ background: {p["bg"]}; }}

QLabel#h1 {{ font-size: 22px; font-weight: 800; color: {p["heading"]}; }}
QLabel#h2 {{ font-size: 15px; font-weight: 700; color: {p["text"]}; }}
QLabel#muted {{ color: {p["muted"]}; font-size: 13px; }}
QLabel#fieldlbl {{ color: {p["muted"]}; font-size: 13px; }}

/* Header bar at the top of each page */
#PageHeader {{ background: transparent; border-bottom: 1px solid {p["border"]}; }}

/* Sidebar (always a dark teal in both themes) */
#Sidebar {{ background: {p["side"]}; }}
#Sidebar QPushButton {{
    text-align: left; padding: 12px 20px 12px 18px; border: none; color: {p["side_text"]};
    background: transparent; font-size: 14px; font-weight: 600; border-left: 4px solid transparent;
}}
#Sidebar QPushButton:hover {{ background: rgba(255,255,255,0.08); color: white; }}
#Sidebar QPushButton:checked {{
    background: rgba(255,255,255,0.14); color: white;
    border-left: 4px solid #7ff0e3;
}}
#SidebarLogo {{ background: white; border-radius: 14px; padding: 10px; margin: 0 10px; }}
#SidebarBrand {{ color: white; font-size: 17px; font-weight: 800; padding: 4px 14px 2px; }}
#SidebarSub {{ color: {p["side_sub"]}; font-size: 12px; padding: 0 14px 14px; qproperty-alignment: AlignCenter; }}
#SidebarUser {{ color: #dbf1f2; padding: 8px 18px; font-size: 13px; }}
#SidebarCredit {{ color: rgba(255,255,255,0.45); padding: 0 10px 12px; font-size: 11px; }}
QStatusBar {{ min-height: 24px; padding-left: 8px; }}

/* Cards */
QFrame#card {{ background: {p["card"]}; border: 1px solid {p["border"]}; border-radius: 12px; }}
QFrame#statcard {{ background: {p["card"]}; border: 1px solid {p["border"]}; border-radius: 12px; }}

/* Buttons — all carry a 1.5px border (transparent for filled ones) so filled
   and ghost buttons render at the exact same height and line up in a row. */
QPushButton {{
    background: {p["primary"]}; color: white; border: 1.5px solid transparent; border-radius: 8px;
    padding: 9px 18px; font-weight: 700; min-height: 18px;
}}
QPushButton:hover {{ background: {p["primary_dark"]}; }}
QPushButton:pressed {{ background: {p["primary_dark"]}; }}
QPushButton:disabled {{ background: {p["disabled_bg"]}; color: {p["disabled_text"]}; }}
QPushButton#ghost {{ background: transparent; color: {p["ghost_text"]}; border: 1.5px solid {p["primary"]}; }}
QPushButton#ghost:hover {{ background: {p["primary_light"]}; }}
QPushButton#ghost:disabled {{ background: transparent; color: {p["muted"]}; border: 1.5px solid {p["border"]}; }}
QPushButton#danger {{ background: {p["danger"]}; border: 1.5px solid transparent; }}
QPushButton#danger:hover {{ background: #99291c; }}
/* The #danger id-selector out-specifies QPushButton:disabled, so without this a
   disabled Delete keeps its red fill with low-contrast text. Match the normal
   disabled look so it reads the same as a disabled Edit. */
QPushButton#danger:disabled {{ background: {p["disabled_bg"]}; color: {p["disabled_text"]}; border: 1.5px solid transparent; }}
QPushButton#linkbtn {{ background: transparent; color: {p["ghost_text"]}; border: none; padding: 6px; font-weight: 700; }}
QPushButton#linkbtn:hover {{ color: {p["primary"]}; }}

/* Inputs */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {{
    background: {p["input_bg"]}; border: 1.5px solid {p["border"]}; border-radius: 8px; padding: 8px 10px;
    selection-background-color: {p["primary"]}; selection-color: white;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border: 1.5px solid {p["primary"]}; }}
QComboBox::drop-down, QDateEdit::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    border: none; width: 22px;
}}
QComboBox::down-arrow, QDateEdit::down-arrow {{
    image: none; width: 0; height: 0; margin-right: 8px;
    border-left: 5px solid transparent; border-right: 5px solid transparent;
    border-top: 6px solid {p["muted"]};
}}
QComboBox QAbstractItemView {{
    background: {p["input_bg"]}; border: 1px solid {p["border"]};
    selection-background-color: {p["primary_light"]}; selection-color: {p["text"]}; outline: none;
}}

/* Calendar popup (every QDateEdit) — themed to match the app instead of Qt's raw
   black-on-green default. Covers the nav bar, the month menu, the year editor (the
   bit that looked black-on-green), and the day grid. */
QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background: {p["primary"]}; min-height: 32px;
    border-top-left-radius: 8px; border-top-right-radius: 8px;
}}
QCalendarWidget QToolButton {{
    color: white; background: transparent; font-weight: 700; font-size: 14px;
    border: none; padding: 4px 12px; border-radius: 6px;
}}
QCalendarWidget QToolButton:hover {{ background: rgba(255,255,255,0.18); }}
QCalendarWidget QToolButton:pressed {{ background: rgba(255,255,255,0.28); }}
QCalendarWidget QToolButton::menu-indicator {{ image: none; width: 0; }}
QCalendarWidget QMenu {{
    background: {p["card"]}; border: 1px solid {p["border"]}; color: {p["text"]}; padding: 4px;
}}
QCalendarWidget QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}
QCalendarWidget QMenu::item:selected {{ background: {p["primary_light"]}; color: {p["text"]}; }}
QCalendarWidget QSpinBox {{
    background: white; color: {p["text"]}; border: 1px solid {p["border"]};
    border-radius: 6px; padding: 2px 6px; min-width: 64px; font-weight: 700;
    selection-background-color: {p["primary"]}; selection-color: white;
}}
QCalendarWidget QSpinBox::up-button {{ subcontrol-position: top right; width: 16px; }}
QCalendarWidget QSpinBox::down-button {{ subcontrol-position: bottom right; width: 16px; }}
QCalendarWidget QWidget {{ alternate-background-color: {p["card"]}; }}
QCalendarWidget QAbstractItemView {{
    background: {p["card"]}; color: {p["text"]}; outline: none; font-size: 13px;
    selection-background-color: {p["primary"]}; selection-color: white;
}}
QCalendarWidget QAbstractItemView:enabled {{ color: {p["text"]}; }}
QCalendarWidget QAbstractItemView:disabled {{ color: {p["muted"]}; }}
/* hide the broken/clipped spin steppers — values are typed */
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; height: 0; border: none; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 10px; }}

/* Checkboxes / radios — explicitly themed so they're clearly visible on dark
   (the default indicator washes out). Empty = outlined box; ticked = teal fill
   with a white check. */
QCheckBox, QRadioButton {{ spacing: 8px; color: {p["text"]}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 18px; height: 18px; border: 1.5px solid {p["muted"]};
    background: {p["input_bg"]};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {p["primary"]}; }}
QCheckBox::indicator:checked {{
    background: {p["primary"]}; border-color: {p["primary"]}; {_check_line}
}}
QRadioButton::indicator:checked {{
    background: {p["primary"]}; border-color: {p["primary"]};
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    border-color: {p["border"]}; background: {p["bg"]};
}}
QCheckBox:disabled, QRadioButton:disabled {{ color: {p["muted"]}; }}

/* Tables */
QTableView, QTableWidget, QTreeView, QListWidget {{
    background: {p["card"]}; border: 1px solid {p["border"]}; border-radius: 10px;
    gridline-color: {p["grid"]}; selection-background-color: {p["primary_light"]};
    selection-color: {p["text"]}; alternate-background-color: {p["alt"]};
}}
QTableView::item:selected, QTableWidget::item:selected,
QTreeView::item:selected {{ background: {p["primary_light"]}; color: {p["text"]}; }}
QHeaderView::section {{
    background: {p["header_bg"]}; color: {p["text"]}; padding: 9px 8px; border: none;
    border-right: 1px solid {p["border"]}; font-weight: 700;
}}
QTableView::item, QTableWidget::item {{ padding: 6px; }}
QListWidget::item {{ padding: 8px; border-bottom: 1px solid {p["listsep"]}; }}
QListWidget::item:selected {{ background: {p["primary_light"]}; color: {p["text"]}; }}

QTabWidget::pane {{ border: 1px solid {p["border"]}; border-radius: 10px; background: {p["card"]}; top: -1px; }}
QTabBar::tab {{
    padding: 9px 18px; background: {p["tab_bg"]}; margin-right: 3px; color: {p["muted"]};
    border-top-left-radius: 8px; border-top-right-radius: 8px; font-weight: 600;
}}
QTabBar::tab:selected {{ background: {p["card"]}; color: {p["heading"]}; font-weight: 700; }}

QScrollBar:vertical {{ width: 12px; background: transparent; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p["scroll"]}; border-radius: 6px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: {p["scroll_hover"]}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollArea {{ border: none; background: transparent; }}

/* Popup menus (right-click row menu, etc.) — themed so they don't fall back to
   a platform-white surface that washes out under the dark theme. Enabled items
   use full text colour; disabled (not-yet-available) items read as muted grey. */
QMenu {{
    background: {p["card"]}; color: {p["text"]};
    border: 1px solid {p["border"]}; border-radius: 8px; padding: 4px;
}}
QMenu::item {{ padding: 7px 22px 7px 16px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p["primary_light"]}; color: {p["text"]}; }}
QMenu::item:disabled {{ color: {p["muted"]}; background: transparent; }}
QMenu::separator {{ height: 1px; background: {p["border"]}; margin: 5px 10px; }}
QStatusBar {{ background: {p["card"]}; color: {p["muted"]}; border-top: 1px solid {p["border"]}; }}
QSplitter::handle {{ background: transparent; width: 14px; }}

/* Setup wizard / login surfaces */
#authCard {{ background: {p["card"]}; border: 1px solid {p["border"]}; border-radius: 16px; }}
#authTitle {{ font-size: 24px; font-weight: 800; color: {p["heading"]}; }}
#brandMark {{
    background: {p["primary"]}; color: white; font-size: 26px; font-weight: 800;
    border-radius: 16px;
}}
"""


def apply_theme(app, theme: str = "light") -> None:
    """Apply a theme fully: the stylesheet AND a matching QPalette (else unstyled
    container widgets keep painting with the default white palette)."""
    from PySide6.QtGui import QColor, QPalette

    p = THEMES.get(theme, _LIGHT)
    app.setStyleSheet(build_qss(theme))
    pal = QPalette()
    text = QColor(p["text"])
    pal.setColor(QPalette.Window, QColor(p["bg"]))
    pal.setColor(QPalette.WindowText, text)
    pal.setColor(QPalette.Base, QColor(p["input_bg"]))
    pal.setColor(QPalette.AlternateBase, QColor(p["alt"]))
    pal.setColor(QPalette.Text, text)
    pal.setColor(QPalette.Button, QColor(p["bg"]))
    pal.setColor(QPalette.ButtonText, text)
    pal.setColor(QPalette.ToolTipBase, QColor(p["card"]))
    pal.setColor(QPalette.ToolTipText, text)
    pal.setColor(QPalette.PlaceholderText, QColor(p["muted"]))
    pal.setColor(QPalette.Highlight, QColor(p["primary"]))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(p["muted"]))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(p["muted"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(p["muted"]))
    app.setPalette(pal)
    # Qt doesn't re-propagate a palette change to already-realised widgets, so
    # force every widget to adopt it and re-evaluate the stylesheet
    style = app.style()
    for w in app.allWidgets():
        w.setPalette(pal)
        style.unpolish(w)
        style.polish(w)
        w.update()


# Default (light) stylesheet — kept for any code that imports QSS directly.
QSS = build_qss("light")
