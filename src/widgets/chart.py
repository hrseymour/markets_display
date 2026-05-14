"""Single-day line chart with a dashed previous-close reference line.

Market-aware x-axis:
- When the market is OPEN, the chart x-axis represents today's full
  trading session. Bars are positioned at their real time fraction, so
  at 10:00 ET (30 min into the US session) the line covers ~7.7% of the
  chart width — empty space to the right.
- When the market is CLOSED (weekend, holiday, after-hours, pre-market),
  the chart shows the most recent session that has data, filling the
  whole chart. A "MARKET CLOSED" badge sits in the chart's banner.
- If no Market is associated with the chart, falls back to the legacy
  behavior: bars fill the chart left-to-right by index.

Visuals:
- Dark background. White Y-axis tick labels on the left.
- No fill below the line.
- Segment coloring with INTERPOLATED crossings at the reference line.
- One dashed amber reference line at yesterday's close.
- "Nice" rounded y-axis tick values.
- Visible grid lines.
"""
from __future__ import annotations

import logging
import math
from datetime import date as date_t, datetime
from typing import List, Optional, Tuple

from PyQt6.QtCore import QPointF, Qt, QRectF
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from ..markets import Market
from ..providers import IntradaySeries
from ..providers.base import IntradayBar
from ..theme import Theme

log = logging.getLogger(__name__)


GRID_LINE = QColor("#2E3548")
AXIS_TEXT = QColor("#FFFFFF")
UP_LINE = QColor("#00D964")
DOWN_LINE = QColor("#FF3B3B")


def _finite(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _with_alpha(c: QColor, alpha_byte: int) -> QColor:
    nc = QColor(c)
    nc.setAlpha(max(0, min(255, alpha_byte)))
    return nc


def _nice_ticks(lo: float, hi: float, target_count: int = 5) -> List[float]:
    if not (_finite(lo) and _finite(hi)) or hi <= lo:
        return []
    raw_step = (hi - lo) / max(1, target_count)
    magnitude = 10 ** math.floor(math.log10(raw_step))
    residual = raw_step / magnitude
    if residual < 1.5:
        nice = 1
    elif residual < 3:
        nice = 2
    elif residual < 7:
        nice = 5
    else:
        nice = 10
    step = nice * magnitude
    first = math.floor(lo / step) * step
    ticks = []
    v = first
    for _ in range(200):
        if v > hi + step / 2:
            break
        if v >= lo - step / 2:
            ticks.append(v)
        v += step
    return ticks


class LineChart(QWidget):
    def __init__(self, theme: Theme, market: Optional[Market] = None, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.market = market
        self.series: Optional[IntradaySeries] = None
        self.setMinimumHeight(120)

    def set_series(self, series: Optional[IntradaySeries]):
        self.series = series
        self.update()

    def set_market(self, market: Optional[Market]):
        self.market = market
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

            clean_bars = self._clean_bars(self.series.bars)
            if not clean_bars:
                self._draw_empty(p, rect, "No data")
                return

            target_date = self._choose_session_date(clean_bars)
            session_bars = [b for b in clean_bars if b.timestamp.date() == target_date]
            if not session_bars:
                self._draw_empty(p, rect, "No data")
                return

            anchor = self.series.prev_closes_by_date.get(target_date)
            if anchor is None or not _finite(anchor):
                anchor = self.series.prev_close if _finite(self.series.prev_close) else None

            use_market_layout = (
                self.market is not None
                and self._is_today_in_market(target_date)
                and self.market.is_open()
            )

            self._draw_chart(p, rect, session_bars, anchor, use_market_layout)
        finally:
            p.end()

    @staticmethod
    def _clean_bars(bars: List[IntradayBar]) -> List[IntradayBar]:
        if not bars:
            return []
        return [b for b in bars if _finite(b.price)]

    def _is_today_in_market(self, d: date_t) -> bool:
        if self.market is None:
            return False
        try:
            return d == self.market.local_date_today()
        except Exception:
            return False

    def _choose_session_date(self, bars: List[IntradayBar]) -> date_t:
        present_dates = []
        seen = set()
        for b in bars:
            d = b.timestamp.date()
            if d not in seen:
                seen.add(d)
                present_dates.append(d)
        present_dates.sort()
        if not present_dates:
            return bars[-1].timestamp.date()

        if self.market is not None:
            try:
                today_local = self.market.local_date_today()
                if today_local in seen and self.market.is_open():
                    return today_local
            except Exception:
                pass

        return present_dates[-1]

    # -------------------------------------------------------------------------
    def _draw_chart(
        self,
        p: QPainter,
        rect,
        bars: List[IntradayBar],
        anchor: Optional[float],
        use_market_layout: bool,
    ):
        prices = [b.price for b in bars]
        lo = min(prices)
        hi = max(prices)
        if anchor is not None and _finite(anchor):
            lo = min(lo, anchor)
            hi = max(hi, anchor)

        if not (_finite(lo) and _finite(hi)):
            self._draw_empty(p, rect, "Bad data")
            return

        if hi == lo:
            hi = lo + 1.0
        span = hi - lo
        lo -= span * 0.08
        hi += span * 0.08

        ch = rect.height()
        axis_px = max(10, int(ch * 0.032))

        left_margin = max(72, int(rect.width() * 0.07))
        right_margin = 12
        top_margin = 10
        bottom_margin = 10

        plot_rect = QRectF(
            rect.left() + left_margin,
            rect.top() + top_margin,
            rect.width() - left_margin - right_margin,
            rect.height() - top_margin - bottom_margin,
        )

        n = len(bars)
        if n < 2:
            return

        if use_market_layout and self.market is not None:
            def x_for(i: int) -> float:
                frac = self.market.fraction_for(bars[i].timestamp)
                return plot_rect.left() + frac * plot_rect.width()
        else:
            def x_for(i: int) -> float:
                return plot_rect.left() + (i / (n - 1)) * plot_rect.width()

        self._draw_y_axis(p, plot_rect, lo, hi, axis_px)

        ref = anchor if (anchor is not None and _finite(anchor)) else None
        y_anchor = self._y(ref, lo, hi, plot_rect) if ref is not None else None

        if ref is not None and y_anchor is not None and _finite(y_anchor):
            pen = QPen(self.theme.prev_close_line, 1.4)
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setDashPattern([6, 4])
            p.setPen(pen)
            p.drawLine(
                QPointF(plot_rect.left(), y_anchor),
                QPointF(plot_rect.right(), y_anchor),
            )

        coords: List[Tuple[float, float]] = []
        for i, b in enumerate(bars):
            x = x_for(i)
            y = self._y(b.price, lo, hi, plot_rect)
            if not (_finite(x) and _finite(y)):
                coords.append((float("nan"), float("nan")))
            else:
                coords.append((x, y))

        pen_up = QPen(UP_LINE, 1.8)
        pen_up.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen_up.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen_down = QPen(DOWN_LINE, 1.8)
        pen_down.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen_down.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        for i in range(n - 1):
            x0, y0 = coords[i]
            x1, y1 = coords[i + 1]
            if not (_finite(x0) and _finite(y0) and _finite(x1) and _finite(y1)):
                continue

            if ref is None or y_anchor is None or not _finite(y_anchor):
                p.setPen(pen_up)
                p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
                continue

            p0_up = bars[i].price >= ref
            p1_up = bars[i + 1].price >= ref

            if p0_up == p1_up:
                p.setPen(pen_up if p0_up else pen_down)
                p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
            else:
                dy = y1 - y0
                if abs(dy) < 1e-9:
                    p.setPen(pen_up if p0_up else pen_down)
                    p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
                    continue
                t = (y_anchor - y0) / dy
                t = max(0.0, min(1.0, t))
                xc = x0 + t * (x1 - x0)
                yc = y_anchor
                p.setPen(pen_up if p0_up else pen_down)
                p.drawLine(QPointF(x0, y0), QPointF(xc, yc))
                p.setPen(pen_up if p1_up else pen_down)
                p.drawLine(QPointF(xc, yc), QPointF(x1, y1))

        end_x, end_y = coords[-1]
        if _finite(end_x) and _finite(end_y):
            if ref is not None and _finite(ref):
                end_color = UP_LINE if bars[-1].price >= ref else DOWN_LINE
            else:
                end_color = UP_LINE
            p.setBrush(QBrush(end_color))
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

    def _draw_y_axis(self, p: QPainter, plot_rect: QRectF, lo: float, hi: float, px: int):
        font = QFont()
        font.setPixelSize(px)
        font.setBold(False)
        p.setFont(font)

        ticks = _nice_ticks(lo, hi, target_count=5)
        for value in ticks:
            y = self._y(value, lo, hi, plot_rect)
            if not _finite(y):
                continue
            if y < plot_rect.top() - 1 or y > plot_rect.bottom() + 1:
                continue
            grid_pen = QPen(GRID_LINE, 1)
            grid_pen.setStyle(Qt.PenStyle.SolidLine)
            p.setPen(grid_pen)
            p.drawLine(QPointF(plot_rect.left(), y), QPointF(plot_rect.right(), y))
            p.setPen(AXIS_TEXT)
            label_h = px + 4
            p.drawText(
                QRectF(0, y - label_h / 2, plot_rect.left() - 6, label_h),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{value:,.0f}",
            )

    def _draw_empty(self, p: QPainter, rect, message: str = "Loading…"):
        p.setPen(_with_alpha(QColor("#FFFFFF"), 180))
        font = QFont()
        font.setPixelSize(max(14, int(rect.height() * 0.06)))
        p.setFont(font)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, message)
