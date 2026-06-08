"""Small reusable UI helpers."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .style import PRIMARY


class FlowLayout(QLayout):
    """Lay widgets left-to-right and WRAP to the next row when horizontal space
    runs out (Qt's classic flow layout). Its minimum width is just the widest
    single child, so a long button toolbar can shrink to one-button width and
    wrap instead of forcing the whole window wider than the screen.
    """

    def __init__(self, parent=None, *, margin=0, hspacing=8, vspacing=6):
        super().__init__(parent)
        self._items = []
        self._hspace = hspacing
        self._vspace = vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):  # noqa: N802 (Qt override)
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, *, test_only):
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = area.x(), area.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._hspace
            if next_x - self._hspace > area.right() and line_h > 0:
                x = area.x()
                y = y + line_h + self._vspace
                next_x = x + hint.width() + self._hspace
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


def fit_to_screen(widget, w: int, h: int, *, margin: float = 0.94) -> None:
    """Clamp a top-level *dialog's* opening size so it never exceeds the screen.

    Sizes are device-independent (logical) pixels — Qt 6 applies DPI scaling on top.
    A fixed resize(.., 1040) overflows a 1366x768 laptop (≈700 px usable height);
    this clamps to availableGeometry() (which excludes the taskbar/dock). Tall content
    should live in a QScrollArea so clamping the height scrolls rather than hides.

    Uses ONLY resize() — never move()/setGeometry() — so window placement is left to
    the layout/window-manager (per the native-layout rule).
    """
    screen = widget.screen() or QApplication.primaryScreen()
    if screen is None:  # headless / offscreen — nothing to clamp to
        widget.resize(w, h)
        return
    avail = screen.availableGeometry()
    widget.resize(min(w, int(avail.width() * margin)), min(h, int(avail.height() * margin)))


def max_width_center(inner, max_w: int):
    """Wrap `inner` so it never exceeds `max_w` logical px and stays horizontally
    centred (stretch | inner | stretch). Used for forms: on a 4K/ultrawide screen a
    single-line field would otherwise stretch across the whole width (sparse, ugly),
    and on a narrow screen an uncapped form can overflow — capping fixes both.
    """
    inner.setMaximumWidth(max_w)
    wrap = QWidget()
    lay = QHBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addStretch(1)
    lay.addWidget(inner)
    lay.addStretch(1)
    return wrap


# status → (display colour) for receipt/worklist tables (single source of truth)
STATUS_COLORS = {
    "pending": "#b9770e",
    "in_progress": "#0e7c86",
    "reported": "#1f9d55",
    "delivered": "#6b7280",
}


def _fixed_v(w: QWidget) -> QWidget:
    """Pin a widget's vertical size so layouts never inflate it (gap-bug guard)."""
    w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    return w


def h1(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("h1")
    return _fixed_v(lbl)


def h2(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("h2")
    return _fixed_v(lbl)


def muted(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("muted")
    return _fixed_v(lbl)


def field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("fieldlbl")
    return _fixed_v(lbl)


def page_header(title: str, subtitle: str = "", *actions: QWidget) -> tuple[QWidget, QLabel]:
    """A consistent page header: title (+subtitle) on the left, actions on the right.
    Returns (header_widget, subtitle_label) so callers can update the subtitle."""
    bar = QWidget()
    bar.setObjectName("PageHeader")
    bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    outer = QVBoxLayout(bar)
    outer.setContentsMargins(2, 0, 2, 10)
    outer.setSpacing(2)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    left = QVBoxLayout()
    left.setSpacing(1)
    left.addWidget(h1(title))
    sub = muted(subtitle)
    if not subtitle:
        sub.hide()
    left.addWidget(sub)
    row.addLayout(left)
    row.addStretch(1)
    for a in actions:
        a.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        row.addWidget(a, 0, Qt.AlignVCenter)
    outer.addLayout(row)
    return bar, sub


def card(*children: QWidget, title: str = "") -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(10)
    if title:
        lay.addWidget(h2(title))
    for c in children:
        lay.addWidget(c)
    return f


def stat_card(title: str, value: str, color: str = PRIMARY, on_click=None) -> QFrame:
    f = QFrame()
    f.setObjectName("statcard")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(20, 18, 20, 18)
    lay.setSpacing(4)
    t = QLabel(title)
    t.setObjectName("muted")
    v = QLabel(value)
    v.setStyleSheet(f"font-size: 30px; font-weight: 800; color: {color};")
    lay.addWidget(t)
    lay.addWidget(v)
    if on_click is not None:
        hint = QLabel("Open →")
        hint.setStyleSheet(f"color:{color};font-weight:700;font-size:12px;")
        lay.addWidget(hint)
        f.setCursor(Qt.PointingHandCursor)
        # highlight the border on hover only — a fixed light fill washes out in dark mode
        f.setStyleSheet("QFrame#statcard:hover { border-color: %s; }" % color)
        f.mousePressEvent = lambda e, cb=on_click: cb()
    else:
        lay.addStretch(1)
    f.value_label = v  # type: ignore[attr-defined]
    return f


def like_term(text: str) -> str:
    """Build a %wrapped% LIKE pattern with the wildcards % _ \\ escaped so user
    input matches literally. Pair with ESCAPE '\\' in the query."""
    t = (text or "").strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{t}%"


def money(value: float, currency: str = "Rs.") -> str:
    value = value or 0.0  # normalise -0.0 / None so we never print "-0"
    if value < 0:
        return f"- {currency} {abs(value):,.0f}"
    return f"{currency} {value:,.0f}"


def num_item(text: str, color: str | None = None) -> QTableWidgetItem:
    """A right-aligned, optionally-coloured table cell for money/number columns."""
    it = QTableWidgetItem(text)
    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if color:
        it.setForeground(QColor(color))
    return it


def selected_id(table, ids):
    """The id (from a parallel ``ids`` list) of the table's selected row, or None.

    Derived from the actual selection (NOT currentRow): a cleared selection
    leaves currentRow set, which would otherwise act on a stale row."""
    sel = table.selectionModel().selectedRows()
    if not sel:
        return None
    r = sel[0].row()
    return ids[r] if 0 <= r < len(ids) else None


def status_badge(status: str, voided: bool = False) -> QTableWidgetItem:
    """A bold, colour-coded status cell shared by the receipt/worklist tables."""
    text = "Voided" if voided else (status or "").replace("_", " ").title()
    it = QTableWidgetItem(text)
    col = "#c0392b" if voided else STATUS_COLORS.get(status or "")
    if col:
        it.setForeground(QColor(col))
        fnt = it.font()
        fnt.setBold(True)
        it.setFont(fnt)
    return it
