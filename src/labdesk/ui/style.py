"""Application-wide palette and stylesheet."""
from __future__ import annotations

# Product (white-label) identity. The *lab's* own name is configured per-install
# via the first-run wizard; this is only the neutral product brand.
PRODUCT_NAME = "LabDesk"
PRODUCT_TAGLINE = "Laboratory Management System"

# Brand palette — clinical teal, calm and legible.
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

# Sidebar gradient endpoints
SIDE_TOP = "#0c6b73"
SIDE_BOT = "#084a51"

QSS = f"""
* {{
    font-family: "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 14px;
    color: {TEXT};
}}
QMainWindow, QDialog, QWidget#page {{ background: {BG}; }}

QLabel#h1 {{ font-size: 22px; font-weight: 800; color: {PRIMARY_DARK}; }}
QLabel#h2 {{ font-size: 15px; font-weight: 700; color: {TEXT}; }}
QLabel#muted {{ color: {MUTED}; font-size: 13px; }}
QLabel#fieldlbl {{ color: {MUTED}; font-size: 13px; }}

/* Header bar at the top of each page */
#PageHeader {{ background: transparent; border-bottom: 1px solid {BORDER}; }}

/* Sidebar */
#Sidebar {{ background: {SIDE_BOT}; }}
#Sidebar QPushButton {{
    text-align: left; padding: 12px 20px 12px 18px; border: none; color: #cfeaec;
    background: transparent; font-size: 14px; font-weight: 600; border-left: 4px solid transparent;
}}
#Sidebar QPushButton:hover {{ background: rgba(255,255,255,0.08); color: white; }}
#Sidebar QPushButton:checked {{
    background: rgba(255,255,255,0.14); color: white;
    border-left: 4px solid #7ff0e3;
}}
#SidebarLogo {{ background: white; border-radius: 14px; padding: 10px; margin: 0 10px; }}
#SidebarBrand {{ color: white; font-size: 17px; font-weight: 800; padding: 4px 14px 2px; }}
#SidebarSub {{ color: #c8e9eb; font-size: 12px; padding: 0 14px 14px; qproperty-alignment: AlignCenter; }}
#SidebarUser {{ color: #dbf1f2; padding: 8px 18px; font-size: 13px; }}
QStatusBar {{ min-height: 24px; padding-left: 8px; }}

/* Cards */
QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#statcard {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}

/* Buttons */
/* All buttons carry a 1.5px border (transparent for filled ones) so a filled
   button and a ghost/outlined button render at the EXACT same height and line
   up in a row. min-height keeps every button a uniform size. */
QPushButton {{
    background: {PRIMARY}; color: white; border: 1.5px solid transparent; border-radius: 8px;
    padding: 9px 18px; font-weight: 700; min-height: 18px;
}}
QPushButton:hover {{ background: {PRIMARY_DARK}; }}
QPushButton:pressed {{ background: {PRIMARY_DARK}; }}
QPushButton:disabled {{ background: #aebfc1; color: #f0f4f4; }}
QPushButton#ghost {{ background: transparent; color: {PRIMARY_DARK}; border: 1.5px solid {PRIMARY}; }}
QPushButton#ghost:hover {{ background: {PRIMARY_LIGHT}; }}
QPushButton#danger {{ background: {DANGER}; }}
QPushButton#danger:hover {{ background: #99291c; }}
QPushButton#linkbtn {{ background: transparent; color: {PRIMARY_DARK}; border: none; padding: 6px; font-weight: 700; }}
QPushButton#linkbtn:hover {{ color: {PRIMARY}; }}

/* Inputs */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {{
    background: white; border: 1.5px solid {BORDER}; border-radius: 8px; padding: 8px 10px;
    selection-background-color: {PRIMARY}; selection-color: white;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border: 1.5px solid {PRIMARY}; }}
QComboBox::drop-down, QDateEdit::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    border: none; width: 22px;
}}
QComboBox::down-arrow, QDateEdit::down-arrow {{
    image: none; width: 0; height: 0; margin-right: 8px;
    border-left: 5px solid transparent; border-right: 5px solid transparent;
    border-top: 6px solid {MUTED};
}}
QComboBox QAbstractItemView {{
    background: white; border: 1px solid {BORDER}; selection-background-color: {PRIMARY_LIGHT};
    selection-color: {TEXT}; outline: none;
}}
/* hide the broken/clipped spin steppers — values are typed */
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; height: 0; border: none; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 10px; }}

/* Tables */
QTableView, QTableWidget, QTreeView, QListWidget {{
    background: white; border: 1px solid {BORDER}; border-radius: 10px;
    gridline-color: #eef1f3; selection-background-color: {PRIMARY_LIGHT};
    selection-color: {TEXT}; alternate-background-color: #f7fafb;
}}
/* keep selected rows readable: dark text on the light teal highlight
   (without this Qt paints selected text white -> invisible on PRIMARY_LIGHT) */
QTableView::item:selected, QTableWidget::item:selected,
QTreeView::item:selected {{ background: {PRIMARY_LIGHT}; color: {TEXT}; }}
QHeaderView::section {{
    background: #eaf1f2; color: {TEXT}; padding: 9px 8px; border: none;
    border-right: 1px solid {BORDER}; font-weight: 700;
}}
QTableView::item, QTableWidget::item {{ padding: 6px; }}
QListWidget::item {{ padding: 8px; border-bottom: 1px solid #f0f3f4; }}
QListWidget::item:selected {{ background: {PRIMARY_LIGHT}; color: {TEXT}; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 10px; background: white; top: -1px; }}
QTabBar::tab {{
    padding: 9px 18px; background: #e3eaeb; margin-right: 3px; color: {MUTED};
    border-top-left-radius: 8px; border-top-right-radius: 8px; font-weight: 600;
}}
QTabBar::tab:selected {{ background: white; color: {PRIMARY_DARK}; font-weight: 700; }}

QScrollBar:vertical {{ width: 12px; background: transparent; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #c2cccf; border-radius: 6px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: #aab6ba; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollArea {{ border: none; background: transparent; }}
QStatusBar {{ background: {CARD}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QSplitter::handle {{ background: transparent; width: 14px; }}

/* Setup wizard / login surfaces */
#authCard {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 16px; }}
#authTitle {{ font-size: 24px; font-weight: 800; color: {PRIMARY_DARK}; }}
#brandMark {{
    background: {PRIMARY}; color: white; font-size: 26px; font-weight: 800;
    border-radius: 16px;
}}
"""
