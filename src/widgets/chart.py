"""Simple line chart with a dashed previous-close reference line.

Deliberately minimal: no candlesticks, no volume, no axes clutter.
- Single thin colored line (green up / red down based on day-over-day)
- Subtle area fill below
- Dashed horizontal line at previous-day close, labeled at right edge
- Y-axis labels on the left (auto-scaled, 4 ticks)
- X-axis: subtle vertical separator between sessions if lookback_days >= 2

NaN/inf protection: yfinance returns NaN prices for off-hours minutes and
sometimes for the most recent partial bar. Feeding NaN coordinates to
QPainter's native C++ side causes an immediate segfault with no Python
traceback. This module filters all values through `math.isfinite()` before
any painter call.
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional, Tuple

from PyQt6.QtCore import QPointF, Qt, QRectF
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from ..providers import IntradaySeries
from ..providers.base import IntradayBar
from ..theme import Theme

log = logging.getLogger(__name__)


def _finite(x) -> bool:
    """True only if x is a real, finite number."""
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


class LineChart(QWidget):
    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.series: Optional[IntradaySeries] = None
        self.setMinimumHeight(120)

    def set_series(self, series: Optional[IntradaySeries]):
        self.series = series
        self.update()

    # -------------------------------------------------------------------------
    def paintEvent(self, ev):
        try:
            self._paint(ev)
        except Exception:
            log.exception("Chart paint failed")

    def _paint(self, ev):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

            rect = self.rect()
            p.fillRect(rect, self.theme.background)

            if not self.series:
                self._draw_empty(p, rect, "Loading…")
                return

            # Filter out NaN/inf bars BEFORE anything else touches them.
            clean_bars = self._clean_bars(self.series.bars)
            prev_close = self.series.prev_close if _finite(self.series.prev_close) else None

            if not clean_bars:
                self._draw_empty(p, rect, "No data")
                return

            self._draw_chart(p, rect, clean_bars, prev_close)
        finally:
            p.end()

    @staticmethod
    def _clean_bars(bars: List[IntradayBar]) -> List[IntradayBar]:
        """Drop any bars whose price isn't a real finite number."""
        if not bars:
            return []
        return [b for b in bars if _finite(b.price)]

    # -------------------------------------------------------------------------
    def _draw_chart(
        self,
        p: QPainter,
        rect,
        bars: List[IntradayBar],
        prev_close: Optional[float],
    ):
        prices = [b.price for b in bars]
        # All bars are guaranteed finite by _clean_bars; still defensive:
        lo = min(prices)
        hi = max(prices)
        if prev_close is not None:
            lo = min(lo, prev_close)
            hi = max(hi, prev_close)

        # Final sanity check — if anything went sideways, bail to empty rather
        # than feeding bad values to QPainter.
        if not (_finite(lo) and _finite(hi)):
            self._draw_empty(p, rect, "Bad data")
            return

        if hi == lo:
            hi = lo + 1.0
        span = hi - lo
        lo -= span * 0.08
        hi += span * 0.08

        # Left margin reserved for Y-axis labels
        left_margin = max(56, int(rect.width() * 0.06))
        right_margin = max(72, int(rect.width() * 0.08))
        top_margin = 8
        bottom_margin = 18

        plot_rect = QRectF(
            rect.left() + left_margin,
            rect.top() + top_margin,
            rect.width() - left_margin - right_margin,
            rect.height() - top_margin - bottom_margin,
        )

        # Grid + Y-axis labels
        self._draw_y_axis(p, plot_rect, lo, hi)

        # Session separators (vertical lines between trading days)
        self._draw_session_separators(p, plot_rect, bars)

        # Previous close dashed line
        if prev_close is not None:
            y_prev = self._y(prev_close, lo, hi, plot_rect)
            if _finite(y_prev):
                pen = QPen(self.theme.prev_close_line, 1.4)
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setDashPattern([6, 4])
                p.setPen(pen)
                p.drawLine(
                    QPointF(plot_rect.left(), y_prev),
                    QPointF(plot_rect.right(), y_prev),
                )
                label_font = QFont()
                label_font.setPointSizeF(9)
                p.setFont(label_font)
                p.setPen(self.theme.prev_close_line)
                p.drawText(
                    QRectF(plot_rect.right() + 4, y_prev - 8, right_margin - 8, 16),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    f"{prev_close:,.2f}",
                )

        # Trend color from last vs prev_close
        last_price = bars[-1].price
        reference = prev_close if prev_close is not None else bars[0].price
        change = last_price - reference
        line_color = self.theme.trend_color(change)
        fill_color = self.theme.trend_fill(change)

        # Build the path — every point validated before adding
        n = len(bars)
        if n < 2:
            return

        def x_for(i):
            return plot_rect.left() + (i / (n - 1)) * plot_rect.width()

        path = QPainterPath()
        started = False
        for i, b in enumerate(bars):
            y = self._y(b.price, lo, hi, plot_rect)
            x = x_for(i)
            if not (_finite(x) and _finite(y)):
                continue
            if not started:
                path.moveTo(x, y)
                started = True
            else:
                path.lineTo(x, y)

        if not started:
            return

        # Area fill under the line
        fill_path = QPainterPath(path)
        fill_path.lineTo(x_for(n - 1), plot_rect.bottom())
        fill_path.lineTo(x_for(0), plot_rect.bottom())
        fill_path.closeSubpath()
        p.fillPath(fill_path, QBrush(fill_color))

        # The line itself
        pen = QPen(line_color, 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPath(path)

        # End-point dot
        end_x = x_for(n - 1)
        end_y = self._y(bars[-1].price, lo, hi, plot_rect)
        if _finite(end_x) and _finite(end_y):
            p.setBrush(QBrush(line_color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(end_x, end_y), 3.5, 3.5)

    # -------------------------------------------------------------------------
    @staticmethod
    def _y(value: float, lo: float, hi: float, plot_rect: QRectF) -> float:
        if not (_finite(value) and _finite(lo) and _finite(hi)):
            return float("nan")
        if hi == lo:
            frac = 0.5
        else:
            frac = (value - lo) / (hi - lo)
        return plot_rect.bottom() - frac * plot_rect.height()

    def _draw_y_axis(self, p: QPainter, plot_rect: QRectF, lo: float, hi: float):
        ticks = 4
        font = QFont()
        font.setPointSizeF(9)
        p.setFont(font)
        for i in range(ticks + 1):
            frac = i / ticks
            value = lo + frac * (hi - lo)
            y = plot_rect.bottom() - frac * plot_rect.height()
            if not (_finite(value) and _finite(y)):
                continue
            pen = QPen(self.theme.grid, 1)
            pen.setStyle(Qt.PenStyle.SolidLine)
            p.setPen(pen)
            p.drawLine(QPointF(plot_rect.left(), y), QPointF(plot_rect.right(), y))
            p.setPen(self.theme.axis)
            p.drawText(
                QRectF(0, y - 8, plot_rect.left() - 4, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{value:,.0f}",
            )

    def _draw_session_separators(self, p: QPainter, plot_rect: QRectF, bars):
        n = len(bars)
        if n < 2:
            return
        pen = QPen(self.theme.axis, 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([2, 4])
        p.setPen(pen)
        last_date = bars[0].timestamp.date()
        for i in range(1, n):
            d = bars[i].timestamp.date()
            if d != last_date:
                x = plot_rect.left() + (i / (n - 1)) * plot_rect.width()
                if not _finite(x):
                    continue
                p.drawLine(QPointF(x, plot_rect.top()), QPointF(x, plot_rect.bottom()))
                font = QFont()
                font.setPointSizeF(8)
                p.setFont(font)
                p.setPen(self.theme.axis)
                # Cross-platform date format (%-m fails on Windows)
                date_str = f"{d.month}/{d.day}"
                p.drawText(
                    QRectF(x - 30, plot_rect.bottom() + 2, 60, 14),
                    Qt.AlignmentFlag.AlignCenter,
                    date_str,
                )
                pen = QPen(self.theme.axis, 1)
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setDashPattern([2, 4])
                p.setPen(pen)
                last_date = d

    def _draw_empty(self, p: QPainter, rect, message: str = "Loading…"):
        p.setPen(self.theme.neutral)
        font = QFont()
        font.setPointSizeF(11)
        p.setFont(font)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, message)
