"""ChartPanel = banner on top + line chart below. Used in the 3 top slots.

Owns the Market context for both the banner (CLOSED badge) and the chart
(x-axis positioning).
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from ..markets import Market
from ..providers import IntradaySeries, Quote
from ..theme import Theme
from .banner import BannerWidget
from .chart import LineChart


class ChartPanel(QWidget):
    def __init__(
        self,
        theme: Theme,
        instrument: dict,
        market: Optional[Market] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.theme = theme
        self.instrument = instrument
        self.market = market

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        decimals = int(instrument.get("decimals", 2))
        unit = instrument.get("unit", "")
        self.banner = BannerWidget(
            theme, name=instrument["name"], decimals=decimals, unit=unit, mode="chart"
        )
        self.banner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.banner.setMinimumHeight(80)
        self.banner.setMaximumHeight(140)

        self.chart = LineChart(theme, market=market)
        self.chart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout.addWidget(self.banner, stretch=0)
        layout.addWidget(self.chart, stretch=1)

    def set_market(self, market: Optional[Market]):
        self.market = market
        self.chart.set_market(market)

    def update_quote(self, quote: Optional[Quote], is_closed: Optional[bool] = None):
        """If is_closed is None, derive it from the Market (when one is set)."""
        if is_closed is None:
            if self.market is not None:
                try:
                    is_closed = not self.market.is_open()
                except Exception:
                    is_closed = False
            else:
                is_closed = False
        self.banner.set_quote(quote, is_closed=is_closed)

    def update_series(self, series: Optional[IntradaySeries]):
        self.chart.set_series(series)
