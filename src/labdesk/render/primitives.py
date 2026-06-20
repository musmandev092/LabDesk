"""The Doc class — a QPdfWriter + QPainter wrapper that draws in millimetres."""

from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QMarginsF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPainterPath,
    QPdfWriter,
    QPen,
)

from .constants import A4_H_MM, A4_W_MM, DPI, mm, px
from .fonts import _ensure_app
from .image import autocrop_image


class Doc:
    """A QPdfWriter + QPainter wrapper that draws in millimetres at 300 dpi."""

    def __init__(
        self,
        margin_mm: tuple[float, float, float, float] = (8, 8, 8, 8),
        device=None,
        images: bool = False,
    ) -> None:
        _ensure_app()
        self._images_mode = images
        self._images: list[QImage] = []
        self._owns = device is None and not images
        self.w: QPdfWriter = None  # type: ignore[assignment]  # may be QPrinter/None
        self._dev: QBuffer = None  # type: ignore[assignment]
        self._buf: QByteArray = None  # type: ignore[assignment]
        if images:
            # paint each page onto an A4 QImage at 300 dpi (for on-screen preview,
            # so we need no QtPdf viewer). new_page() finalises one and starts next.
            self._buf = self._dev = self.w = None
        elif self._owns:
            self._buf = QByteArray()
            self._dev = QBuffer(self._buf)
            self._dev.open(QBuffer.WriteOnly)
            self.w = QPdfWriter(self._dev)
        else:
            # an external QPagedPaintDevice (e.g. a QPrinter) — paint straight onto
            # it so printing needs no QtPdf round-trip and emits vector output
            self._buf = self._dev = None
            self.w = device
        self.ml, self.mt, self.mr, self.mb = margin_mm
        self.content_w = A4_W_MM - self.ml - self.mr
        if images:
            self._start_image()
        else:
            self.w.setResolution(DPI)
            self.w.setPageSize(QPageSize(QPageSize.A4))
            with contextlib.suppress(Exception):
                self.w.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)
            with contextlib.suppress(Exception):
                self.w.setFullPage(True)  # QPrinter: paint the whole sheet ourselves
            self.p = QPainter(self.w)
            self._hints()

    def _hints(self) -> None:
        self.p.setRenderHint(QPainter.Antialiasing, True)
        self.p.setRenderHint(QPainter.TextAntialiasing, True)
        self.p.setRenderHint(QPainter.SmoothPixmapTransform, True)

    def _start_image(self) -> None:
        img = QImage(int(mm(A4_W_MM)), int(mm(A4_H_MM)), QImage.Format_RGB888)
        img.fill(QColor("#ffffff"))
        img.setDotsPerMeterX(int(DPI / 25.4 * 1000))
        img.setDotsPerMeterY(int(DPI / 25.4 * 1000))
        self._cur_img = img
        self.p = QPainter(img)
        self._hints()

    # -- finish: PDF bytes (owned QPdfWriter), list[QImage] (images), or None --
    def finish(self) -> list[QImage] | bytes | None:
        self.p.end()
        if self._images_mode:
            self._images.append(self._cur_img)
            return self._images
        if self._owns:
            self._dev.close()
            return bytes(self._buf)
        return None

    def tobytes(self) -> bytes | list[QImage] | None:
        return self.finish()

    def new_page(self) -> None:
        if self._images_mode:
            self.p.end()
            self._images.append(self._cur_img)
            self._start_image()
        else:
            self.w.newPage()

    # -- primitives (all args in mm) --
    def fm(self, font: QFont) -> QFontMetricsF:
        return QFontMetricsF(font, self.p.device())

    def fill_rect(self, x: float, y: float, w: float, h: float, color: str) -> None:
        self.p.fillRect(QRectF(mm(x), mm(y), mm(w), mm(h)), QColor(color))

    def rect(
        self, x: float, y: float, w: float, h: float, color: str, width_px: float = 1.0
    ) -> None:
        self.p.setBrush(Qt.NoBrush)
        self.p.setPen(QPen(QColor(color), mm(px(width_px))))
        self.p.drawRect(QRectF(mm(x), mm(y), mm(w), mm(h)))

    def rounded(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        radius_px: float,
        fill: str | None = None,
        border: str | None = None,
        border_px: float = 1.0,
    ) -> None:
        r = mm(px(radius_px))
        path = QPainterPath()
        path.addRoundedRect(QRectF(mm(x), mm(y), mm(w), mm(h)), r, r)
        if fill:
            self.p.fillPath(path, QColor(fill))
        if border:
            self.p.setPen(QPen(QColor(border), mm(px(border_px))))
            self.p.setBrush(Qt.NoBrush)
            self.p.drawPath(path)

    def top_rounded(
        self, x: float, y: float, w: float, h: float, radius_px: float, fill: str
    ) -> None:
        """Rectangle with only the top two corners rounded (title bar)."""
        r = mm(px(radius_px))
        path = QPainterPath()
        path.moveTo(mm(x), mm(y + h))
        path.lineTo(mm(x), mm(y) + r)
        path.quadTo(mm(x), mm(y), mm(x) + r, mm(y))
        path.lineTo(mm(x + w) - r, mm(y))
        path.quadTo(mm(x + w), mm(y), mm(x + w), mm(y) + r)
        path.lineTo(mm(x + w), mm(y + h))
        path.closeSubpath()
        self.p.fillPath(path, QColor(fill))

    def hline(
        self, x: float, y: float, w: float, color: str, width_px: float = 1.0
    ) -> None:
        self.p.setPen(QPen(QColor(color), mm(px(width_px))))
        self.p.drawLine(
            QRectF(mm(x), mm(y), mm(w), 0).topLeft(),
            QRectF(mm(x), mm(y), mm(w), 0).topRight(),
        )

    def text(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        s: str | None,
        font: QFont,
        color: str,
        align=Qt.AlignLeft | Qt.AlignVCenter,
        wrap: bool = False,
    ) -> None:
        self.p.setFont(font)
        self.p.setPen(QColor(color))
        flags = int(align)
        if wrap:
            flags |= int(Qt.TextWordWrap)
        self.p.drawText(QRectF(mm(x), mm(y), mm(w), mm(h)), flags, s or "")

    def text_runs(
        self,
        x: float,
        y: float,
        h: float,
        runs: list[tuple[str, QFont, str]],
        align_left: bool = True,
    ) -> float:
        """Draw a sequence of (text, font, color) runs on one baseline-centred row,
        left to right. Returns total width in mm. Used for value + colored arrow."""
        cx = x
        for s, font, color in runs:
            fmpx = self.fm(font)
            adv = fmpx.horizontalAdvance(s) / DPI * 25.4
            self.p.setFont(font)
            self.p.setPen(QColor(color))
            self.p.drawText(
                QRectF(mm(cx), mm(y), mm(adv + 1), mm(h)),
                int(Qt.AlignLeft | Qt.AlignVCenter),
                s,
            )
            cx += adv
        return cx - x

    def image(
        self,
        x: float,
        y: float,
        path: str | Path,
        h_px: float,
        center_w: float | None = None,
    ) -> float:
        img = QImage(str(path))
        if img.isNull():
            return 0.0
        img = autocrop_image(img)  # trim baked-in white/transparent margins
        target_h = mm(px(h_px))
        scaled = img.scaledToHeight(int(target_h), Qt.SmoothTransformation)
        w_mm = scaled.width() / DPI * 25.4
        if center_w is not None:  # horizontally centre within [x, x+center_w]
            x = x + (center_w - w_mm) / 2
        self.p.drawImage(
            QRectF(mm(x), mm(y), scaled.width(), scaled.height()).topLeft(), scaled
        )
        return w_mm  # drawn width in mm

    def text_height(
        self, s: str | None, font: QFont, w: float, wrap: bool = True
    ) -> float:
        """Measured height in mm for text in a width-w (mm) box."""
        fmpx = self.fm(font)
        flags = int(Qt.AlignLeft | Qt.AlignTop)
        if wrap:
            flags |= int(Qt.TextWordWrap)
        br = fmpx.boundingRect(QRectF(0, 0, mm(w), mm(10000)), flags, s or "")
        return br.height() / DPI * 25.4
