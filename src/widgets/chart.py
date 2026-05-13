"""Simple line chart with a dashed previous-close reference line.

Deliberately minimal: no candlesticks, no volume, no axes clutter.
- Single thin colored line (green up / red down based on day-over-day)
- Subtle area fill below
- Dashed horizontal line at previous-day close, labeled at right edge
- Y-axis labels on the left (auto-scaled, 4 ticks)
- X-axis: subtle vertical separator between sessions if lookback_days >= 2
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QPointF, Qt, QRectF
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from ..providers import IntradaySeries
from ..theme import Theme


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
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Chart paint failed: %s", e)

    def _paint(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        rect = self.rect()
        p.fillRect(rect, self.theme.background)

        if not self.series or not self.series.bars:
            self._draw_empty(p, rect)
            p.end()
            return

        bars = self.series.bars
        prev_close = self.series.prev_close

        # Compute price range
        prices = [b.price for b in bars]
        lo = min(min(prices), prev_close)
        hi = max(max(prices), prev_close)
        if hi == lo:
            hi = lo + 1.0
        # Pad range a bit so the line doesn't kiss the edges
        span = hi - lo
        lo -= span * 0.08
        hi += span * 0.08

        # Left margin reserved for Y-axis labels
        left_margin = max(56, int(rect.width() * 0.06))
        right_margin = max(72, int(rect.width() * 0.08))  # space for prev-close label
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
        y_prev = self._y(prev_close, lo, hi, plot_rect)
        pen = QPen(self.theme.prev_close_line, 1.4)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([6, 4])
        p.setPen(pen)
        p.drawLine(QPointF(plot_rect.left(), y_prev), QPointF(plot_rect.right(), y_prev))
        # Label on right side
        label_font = QFont()
        label_font.setPointSizeF(9)
        p.setFont(label_font)
        p.setPen(self.theme.prev_close_line)
        label = f"{prev_close:,.2f}"
        p.drawText(
            QRectF(plot_rect.right() + 4, y_prev - 8, right_margin - 8, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            label,
        )

        # Determine trend color from last vs prev_close
        last_price = bars[-1].price
        change = last_price - prev_close
        line_color = self.theme.trend_color(change)
        fill_color = self.theme.trend_fill(change)

        # Build the path
        n = len(bars)
        if n < 2:
            p.end()
            return

        def x_for(i):
            return plot_rect.left() + (i / (n - 1)) * plot_rect.width()

        path = QPainterPath()
        path.moveTo(x_for(0), self._y(bars[0].price, lo, hi, plot_rect))
        for i in range(1, n):
            path.lineTo(x_for(i), self._y(bars[i].price, lo, hi, plot_rect))

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
        p.setBrush(QBrush(line_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(end_x, end_y), 3.5, 3.5)

        p.end()

    # -------------------------------------------------------------------------
    @staticmethod
    def _y(value: float, lo: float, hi: float, plot_rect: QRectF) -> float:
        frac = (value - lo) / (hi - lo) if hi != lo else 0.5
        # Higher value = higher on screen (smaller y)
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
            # Subtle grid line
            pen = QPen(self.theme.grid, 1)
            pen.setStyle(Qt.PenStyle.SolidLine)
            p.setPen(pen)
            p.drawLine(QPointF(plot_rect.left(), y), QPointF(plot_rect.right(), y))
            # Label
            p.setPen(self.theme.axis)
            label = f"{value:,.0f}"
            p.drawText(
                QRectF(0, y - 8, plot_rect.left() - 4, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )

    def _draw_session_separators(self, p: QPainter, plot_rect: QRectF, bars):
        # Find indices where the date changes
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
                p.drawLine(QPointF(x, plot_rect.top()), QPointF(x, plot_rect.bottom()))
                # Date label
                font = QFont()
                font.setPointSizeF(8)
                p.setFont(font)
                p.setPen(self.theme.axis)
                date_str = d.strftime("%-m/%-d")
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

    def _draw_empty(self, p: QPainter, rect):
        p.setPen(self.theme.neutral)
        font = QFont()
        font.setPointSizeF(11)
        p.setFont(font)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Loading…")
