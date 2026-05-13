"""ChartPanel = banner on top + line chart below. Used in the 3 top slots."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import QVBoxLayout, QWidget, QSizePolicy

from ..providers import IntradaySeries, Quote
from ..theme import Theme
from .banner import BannerWidget
from .chart import LineChart


class ChartPanel(QWidget):
    def __init__(self, theme: Theme, instrument: dict, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.instrument = instrument

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        decimals = int(instrument.get("decimals", 2))
        unit = instrument.get("unit", "")
        self.banner = BannerWidget(
            theme, name=instrument["name"], decimals=decimals, unit=unit, mode="chart"
        )
        # Banner gets a fixed-ish vertical footprint so the chart fills the rest
        self.banner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.banner.setMinimumHeight(80)
        self.banner.setMaximumHeight(140)

        self.chart = LineChart(theme)
        self.chart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout.addWidget(self.banner, stretch=0)
        layout.addWidget(self.chart, stretch=1)

    def update_quote(self, quote: Optional[Quote], is_closed: bool = False):
        self.banner.set_quote(quote, is_closed=is_closed)

    def update_series(self, series: Optional[IntradaySeries]):
        self.chart.set_series(series)
