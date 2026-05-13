"""CNBC-style banner widget. Used at the top of each chart and in each tile.

Layout for "chart" mode (wide, short — sits atop a chart):
    NAME                                      [CLOSED]
    PRICE   +CHANGE  [+PCT%]

Layout for "tile" mode (smaller, more compact):
    NAME
    PRICE
    +CHANGE  [+PCT%]

All font sizing is in pixels so it scales linearly with the widget — the
same code works on a 1080p test screen and a 4K wall display.

NaN/inf protection: if the Quote contains any non-finite numeric field, we
draw the placeholder (—) instead of attempting to format and paint it.
Non-finite floats fed to fmt strings or QPainter cause native segfaults.
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
    """Verify every numeric field is finite. Otherwise the banner falls back
    to the placeholder display."""
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
        self.setMinimumHeight(72 if mode == "chart" else 110)

    def set_quote(self, quote: Optional[Quote], is_closed: bool = False):
        # Validate before storing. If the Quote contains any NaN/inf, store
        # None instead so we draw the placeholder rather than risk a segfault.
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

            # Background
            bg = self.theme.banner_bg if self.mode == "chart" else self.theme.tile_bg
            p.fillRect(rect, bg)
            if self.mode == "tile":
                p.setPen(QPen(self.theme.tile_border, 1))
                p.drawRect(rect.adjusted(0, 0, -1, -1))

            if self.mode == "tile":
                self._paint_tile(p, rect, w, h)
            else:
                self._paint_chart_banner(p, rect, w, h)
        finally:
            p.end()

    # -------------------------------------------------------------------------
    def _paint_chart_banner(self, p: QPainter, rect: QRect, w: int, h: int):
        """Horizontal layout: name on top row, price+change on bottom row."""
        pad_x = max(12, int(h * 0.12))
        pad_y = max(6, int(h * 0.10))

        name_h = int(h * 0.35)
        price_h = h - name_h - 2 * pad_y
        if price_h <= 0:
            return

        # Name
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

        # Price row
        price_y = pad_y + name_h
        price_rect = QRect(pad_x, price_y, w - 2 * pad_x, price_h)
        if self.quote is None:
            p.setFont(_font(int(price_h * 0.65)))
            p.setPen(self.theme.neutral)
            p.drawText(price_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "—")
            return

        self._draw_price_and_change_inline(p, price_rect, price_h)

    def _paint_tile(self, p: QPainter, rect: QRect, w: int, h: int):
        """Stacked layout: NAME | PRICE | CHANGE — each on its own line."""
        pad_x = max(10, int(h * 0.10))
        pad_y = max(6, int(h * 0.08))

        name_h = int(h * 0.22)
        price_h = int(h * 0.50)
        change_h = int(h * 0.22)

        if min(name_h, price_h, change_h) <= 0:
            return

        y = pad_y

        # Name
        name_px = int(name_h * 0.85)
        p.setFont(_font(name_px, bold=True, letter_spacing=103))
        name_rect = QRect(pad_x, y, w - 2 * pad_x, name_h)
        p.setPen(self.theme.banner_text)
        p.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.name.upper(),
        )
        y += name_h

        # Price
        if self.quote is None:
            p.setFont(_font(int(price_h * 0.70)))
            p.setPen(self.theme.neutral)
            p.drawText(
                QRect(pad_x, y, w - 2 * pad_x, price_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                "—",
            )
            return

        price_str = fmt_price(self.quote.price, self.decimals) + (self.unit or "")
        max_w = max(20, w - 2 * pad_x)
        price_px = self._fit_text_px(price_str, max_w, int(price_h * 0.85))
        p.setFont(_font(price_px, bold=True))
        p.setPen(self.theme.banner_text)
        p.drawText(
            QRect(pad_x, y, w - 2 * pad_x, price_h),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            price_str,
        )
        y += price_h

        # Change + pct
        change_str = fmt_change(self.quote.change, self.decimals)
        pct_str = fmt_pct(self.quote.change_pct)
        combined = f"{change_str}   {pct_str}"
        change_px = self._fit_text_px(combined, max_w, int(change_h * 0.78))
        p.setFont(_font(change_px, bold=True))
        p.setPen(self.theme.trend_color(self.quote.change))
        p.drawText(
            QRect(pad_x, y, w - 2 * pad_x, change_h),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            combined,
        )

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

    def _draw_price_and_change_inline(self, p: QPainter, price_rect: QRect, price_h: int):
        price_str = fmt_price(self.quote.price, self.decimals) + (self.unit or "")
        change_str = fmt_change(self.quote.change, self.decimals)
        pct_str = fmt_pct(self.quote.change_pct)
        combined_change = f"{change_str}   {pct_str}"
        trend_color = self.theme.trend_color(self.quote.change)

        available_w = max(20, price_rect.width())
        gap_h = max(10, int(price_h * 0.20))

        price_px = max(12, int(price_h * 0.90))
        change_px = max(10, int(price_h * 0.42))

        # Bounded iteration — never infinite loop
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

    def _fit_text_px(self, text: str, max_w: int, start_px: int) -> int:
        """Return the largest pixel font size that fits `text` within `max_w`.
        Bounded — never loops more than start_px iterations."""
        px = max(8, int(start_px))
        # Bounded so a degenerate max_w can't infinite loop
        for _ in range(px):
            if px <= 8:
                return 8
            fm = QFontMetrics(_font(px, bold=True))
            if fm.horizontalAdvance(text) <= max_w:
                return px
            px -= 1
        return max(8, px)
