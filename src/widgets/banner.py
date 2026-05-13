"""CNBC-style banner widget. Used at the top of each chart and in each tile.

Layout for both modes:
    NAME                                      [CLOSED]
    PRICE   +CHANGE  [+PCT%]

Difference between modes:
- "chart": narrower height (sits above a chart).
- "tile": taller (standalone tile), text slightly larger but in the same
  typographic family as chart-banner text. Price font is auto-shrunk to
  fit alongside the change/pct text.

All font sizing is in pixels so it scales linearly with the widget — the
same code works on a 1080p test screen and a 4K wall display.

NaN/inf protection: if the Quote contains any non-finite numeric field, we
draw the placeholder (—) instead of attempting to format and paint it.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ..providers import Quote
from ..theme import Theme

log = logging.getLogger(__name__)


def _finite(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _quote_is_sane(q: Optional[Quote]) -> bool:
    if q is None:
        return False
    return all(_finite(v) for v in (q.price, q.prev_close, q.change, q.change_pct))


def fmt_price(value: float, decimals: int) -> str:
    return f"{value:,.{decimals}f}"


def fmt_change(value: float, decimals: int) -> str:
    sign = "+" if value >= 0 else "−"
    return f"{sign}{abs(value):,.{decimals}f}"


def fmt_pct(value: float) -> str:
    sign = "+" if value >= 0 else "−"
    return f"[{sign}{abs(value):.2f}%]"


def _font(px: int, bold: bool = True, letter_spacing: int = 100) -> QFont:
    f = QFont()
    f.setBold(bold)
    f.setPixelSize(max(8, int(px)))
    if letter_spacing != 100:
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, letter_spacing)
    return f


class BannerWidget(QWidget):
    def __init__(
        self,
        theme: Theme,
        name: str,
        decimals: int = 2,
        unit: str = "",
        mode: str = "chart",   # "chart" | "tile"
        parent=None,
    ):
        super().__init__(parent)
        self.theme = theme
        self.name = name
        self.decimals = decimals
        self.unit = unit
        self.mode = mode
        self.quote: Optional[Quote] = None
        self.is_closed = False
        self.setAutoFillBackground(False)
        self.setMinimumHeight(72 if mode == "chart" else 96)

    def set_quote(self, quote: Optional[Quote], is_closed: bool = False):
        if quote is not None and not _quote_is_sane(quote):
            log.warning(
                "Banner %r received non-finite Quote: price=%r prev=%r change=%r pct=%r",
                self.name, quote.price, quote.prev_close, quote.change, quote.change_pct,
            )
            quote = None
        self.quote = quote
        self.is_closed = is_closed
        self.update()

    # -------------------------------------------------------------------------
    def paintEvent(self, ev):
        try:
            self._paint(ev)
        except Exception:
            log.exception("Banner %r paint failed", self.name)

    def _paint(self, ev):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            rect = self.rect()
            h = rect.height()
            w = rect.width()
            if h <= 0 or w <= 0:
                return

            bg = self.theme.banner_bg if self.mode == "chart" else self.theme.tile_bg
            p.fillRect(rect, bg)
            if self.mode == "tile":
                p.setPen(QPen(self.theme.tile_border, 1))
                p.drawRect(rect.adjusted(0, 0, -1, -1))

            self._paint_inline(p, rect, w, h)
        finally:
            p.end()

    # -------------------------------------------------------------------------
    def _paint_inline(self, p: QPainter, rect: QRect, w: int, h: int):
        """Two-row layout: NAME on top, PRICE + CHANGE + PCT% inline below.
        Used by both chart and tile modes; tile uses slightly larger fonts."""
        # Slightly different vertical proportions per mode
        if self.mode == "tile":
            pad_x = max(12, int(h * 0.12))
            pad_y = max(8, int(h * 0.12))
            name_frac = 0.34
            price_size_frac = 0.62  # of price-row height
        else:
            pad_x = max(12, int(h * 0.12))
            pad_y = max(6, int(h * 0.10))
            name_frac = 0.35
            price_size_frac = 0.90

        name_h = int(h * name_frac)
        price_h = h - name_h - 2 * pad_y
        if price_h <= 0:
            return

        # --- Name row ---
        name_px = int(name_h * 0.78)
        p.setFont(_font(name_px, bold=True, letter_spacing=103))
        name_rect = QRect(pad_x, pad_y, w - 2 * pad_x, name_h)
        name_rect = self._reserve_closed_badge(p, name_rect, name_h, pad_x)
        p.setFont(_font(name_px, bold=True, letter_spacing=103))
        p.setPen(self.theme.banner_text)
        p.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.name.upper(),
        )

        # --- Price row ---
        price_y = pad_y + name_h
        price_rect = QRect(pad_x, price_y, w - 2 * pad_x, price_h)
        if self.quote is None:
            p.setFont(_font(int(price_h * 0.65)))
            p.setPen(self.theme.neutral)
            p.drawText(price_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "—")
            return

        self._draw_price_and_change_inline(p, price_rect, price_h, price_size_frac)

    # -------------------------------------------------------------------------
    def _reserve_closed_badge(
        self, p: QPainter, name_rect: QRect, name_h: int, pad_x: int
    ) -> QRect:
        if not self.is_closed:
            return name_rect
        badge_text = "CLOSED"
        badge_px = max(10, int(name_h * 0.55))
        p.setFont(_font(badge_px, bold=True))
        fm = p.fontMetrics()
        badge_w = fm.horizontalAdvance(badge_text) + int(pad_x * 1.2)
        badge_rect = QRect(
            name_rect.right() - badge_w, name_rect.top(), badge_w, name_rect.height()
        )
        p.fillRect(badge_rect, self.theme.closed_badge_bg)
        p.setPen(self.theme.closed_badge_text)
        p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)
        trimmed = QRect(name_rect)
        trimmed.setRight(badge_rect.left() - int(pad_x * 0.4))
        return trimmed

    def _draw_price_and_change_inline(
        self, p: QPainter, price_rect: QRect, price_h: int, price_size_frac: float
    ):
        price_str = fmt_price(self.quote.price, self.decimals) + (self.unit or "")
        change_str = fmt_change(self.quote.change, self.decimals)
        pct_str = fmt_pct(self.quote.change_pct)
        combined_change = f"{change_str}   {pct_str}"
        trend_color = self.theme.trend_color(self.quote.change)

        available_w = max(20, price_rect.width())
        gap_h = max(10, int(price_h * 0.20))

        price_px = max(12, int(price_h * price_size_frac))
        change_px = max(10, int(price_h * (price_size_frac * 0.46)))

        # Bounded auto-shrink loop
        for _ in range(64):
            p.setFont(_font(price_px, bold=True))
            price_w = p.fontMetrics().horizontalAdvance(price_str)
            p.setFont(_font(change_px, bold=True))
            change_w = p.fontMetrics().horizontalAdvance(combined_change)
            if price_w + gap_h + change_w <= available_w or price_px <= 12:
                break
            price_px -= 2
            if price_px % 4 == 0 and change_px > 10:
                change_px -= 1

        p.setFont(_font(price_px, bold=True))
        price_w = p.fontMetrics().horizontalAdvance(price_str)
        p.setPen(self.theme.banner_text)
        p.drawText(
            price_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            price_str,
        )
        change_rect = QRect(
            price_rect.left() + price_w + gap_h,
            price_rect.top(),
            available_w - price_w - gap_h,
            price_rect.height(),
        )
        p.setFont(_font(change_px, bold=True))
        p.setPen(trend_color)
        p.drawText(
            change_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            combined_change,
        )
