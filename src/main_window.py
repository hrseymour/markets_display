"""Main window. Charts row on top, tiles grid on bottom.

When the active region changes, the window swaps both the chart
instruments and the tile instruments based on YAML. Each chart instrument
may declare a `market:` key referencing the top-level `markets:` block;
the chart then knows what timezone and session apply, and positions bars
along an x-axis that represents that market's trading day.

Data fetching is asynchronous via DataService (thread-pool based).
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QCursor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from .data_service import DataService
from .markets import Market, load_markets
from .providers import IntradaySeries, ProviderDispatcher, Quote
from .scheduler import Scheduler
from .theme import Theme
from .widgets import BannerWidget, ChartPanel

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.theme = Theme.from_config(config)
        self.scheduler = Scheduler(config["schedule"])
        self.markets: Dict[str, Market] = load_markets(config.get("markets", {}))
        log.info("Loaded %d markets: %s", len(self.markets), list(self.markets.keys()))
        self.dispatcher = ProviderDispatcher(config.get("providers", {}))
        self.data = DataService(self.dispatcher)
        self.data.quote_ready.connect(self._on_quote)
        self.data.series_ready.connect(self._on_series)

        self.chart_panels: List[ChartPanel] = []
        self.tile_widgets: List[BannerWidget] = []
        self.chart_instruments: List[dict] = []
        self.tile_instruments: List[dict] = []
        self.active_region: Optional[str] = None

        self._build_ui()
        self._install_shortcuts()
        self._apply_window_settings()

        refresh = config.get("refresh", {})
        self.chart_timer = QTimer(self)
        self.chart_timer.setInterval(int(refresh.get("chart_seconds", 60)) * 1000)
        self.chart_timer.timeout.connect(self._refresh_charts)
        self.chart_timer.start()

        self.tile_timer = QTimer(self)
        self.tile_timer.setInterval(int(refresh.get("tile_seconds", 60)) * 1000)
        self.tile_timer.timeout.connect(self._refresh_tiles)
        self.tile_timer.start()

        self.region_timer = QTimer(self)
        self.region_timer.setInterval(30_000)
        self.region_timer.timeout.connect(self._check_region)
        self.region_timer.start()

        # Re-paint chart banners every minute so the CLOSED badge appears
        # promptly when a market crosses its open/close boundary, even if
        # no new data has arrived.
        self.market_state_timer = QTimer(self)
        self.market_state_timer.setInterval(30_000)
        self.market_state_timer.timeout.connect(self._refresh_chart_states)
        self.market_state_timer.start()

        QTimer.singleShot(0, lambda: self._check_region(force=True))

    # =========================================================================
    def _build_ui(self):
        central = QWidget()
        central.setStyleSheet(
            f"background-color: {self.theme.background.name()};"
        )
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        layout_cfg = self.config.get("layout", {})
        outer_pad = self._scaled(layout_cfg.get("outer_padding", 24))
        outer.setContentsMargins(outer_pad, outer_pad, outer_pad, outer_pad)
        outer.setSpacing(self._scaled(layout_cfg.get("chart_gap", 16)))

        self.charts_row = QWidget()
        charts_layout = QHBoxLayout(self.charts_row)
        charts_layout.setContentsMargins(0, 0, 0, 0)
        charts_layout.setSpacing(self._scaled(layout_cfg.get("chart_gap", 16)))
        self.charts_layout = charts_layout

        self.tiles_grid = QWidget()
        tiles_layout = QGridLayout(self.tiles_grid)
        tiles_layout.setContentsMargins(0, 0, 0, 0)
        tile_gap = self._scaled(layout_cfg.get("tile_gap", 10))
        tiles_layout.setHorizontalSpacing(tile_gap)
        tiles_layout.setVerticalSpacing(tile_gap)
        self.tiles_layout = tiles_layout

        charts_frac = float(layout_cfg.get("charts_height_fraction", 0.62))
        outer.addWidget(self.charts_row, stretch=int(charts_frac * 100))
        outer.addWidget(self.tiles_grid, stretch=int((1 - charts_frac) * 100))

    def _apply_window_settings(self):
        d = self.config.get("display", {})
        res = d.get("resolution", "auto")
        if res != "auto":
            try:
                w, h = res.lower().split("x")
                self.resize(int(w), int(h))
            except Exception:
                log.warning("Bad resolution %r in config; using auto.", res)
        if d.get("fullscreen", True):
            self.showFullScreen()
        else:
            self.show()
        if d.get("hide_cursor", True):
            self.setCursor(QCursor(Qt.CursorShape.BlankCursor))
        self.setWindowTitle("Markets Display")

    def _install_shortcuts(self):
        QShortcut(QKeySequence("Esc"), self, activated=self.close)
        QShortcut(QKeySequence("F11"), self, activated=self._toggle_fullscreen)
        QShortcut(QKeySequence("R"), self, activated=lambda: self._refresh_all())

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _scaled(self, px_at_1080p: int) -> int:
        h = 1080
        try:
            screen = self.screen()
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen is not None:
                size = screen.size()
                if size is not None and size.height() > 0:
                    h = size.height()
        except Exception as e:
            log.debug("_scaled: falling back to 1080p baseline (%s)", e)
        factor = h / 1080.0
        return max(1, int(round(px_at_1080p * factor)))

    # =========================================================================
    def _check_region(self, force: bool = False):
        try:
            active = self.scheduler.active()
            if not force and active.name == self.active_region:
                return
            log.info("Switching to region: %s", active.name)
            self.active_region = active.name
            self._load_chart_set(active.chart_set)
            self._load_tile_set(active.tile_set)
            self._refresh_all()
        except Exception:
            log.error("_check_region crashed:\n%s", traceback.format_exc())

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _resolve_market(self, instrument: dict) -> Optional[Market]:
        name = instrument.get("market")
        if not name:
            return None
        m = self.markets.get(name)
        if m is None:
            log.warning(
                "Instrument %r references unknown market %r",
                instrument.get("name"), name,
            )
        return m

    def _load_chart_set(self, set_name: str):
        instruments = self.config.get("charts", {}).get(set_name, [])
        self._clear_layout(self.charts_layout)
        self.chart_panels = []
        self.chart_instruments = []
        banner_h = self._scaled(96)
        for inst in instruments:
            market = self._resolve_market(inst)
            panel = ChartPanel(self.theme, inst, market=market)
            panel.banner.setMinimumHeight(banner_h)
            panel.banner.setMaximumHeight(banner_h)
            self.charts_layout.addWidget(panel, stretch=1)
            self.chart_panels.append(panel)
            self.chart_instruments.append(inst)
        log.debug("Loaded %d chart panels for set=%s", len(instruments), set_name)

    def _load_tile_set(self, set_name: str):
        instruments = self.config.get("tiles", {}).get(set_name, [])
        self._clear_layout(self.tiles_layout)
        self.tile_widgets = []
        self.tile_instruments = []
        cols = int(self.config.get("layout", {}).get("tile_columns", 4))
        for idx, inst in enumerate(instruments):
            decimals = int(inst.get("decimals", 2))
            unit = inst.get("unit", "")
            w = BannerWidget(
                self.theme,
                name=inst["name"],
                decimals=decimals,
                unit=unit,
                mode="tile",
            )
            row = idx // cols
            col = idx % cols
            self.tiles_layout.addWidget(w, row, col)
            self.tile_widgets.append(w)
            self.tile_instruments.append(inst)
        log.debug("Loaded %d tiles for set=%s", len(instruments), set_name)

    # =========================================================================
    def _refresh_all(self):
        self._refresh_charts()
        self._refresh_tiles()

    def _refresh_charts(self):
        log.debug("Refreshing %d charts", len(self.chart_instruments))
        for idx, inst in enumerate(self.chart_instruments):
            key = f"chart:{idx}"
            self.data.request_quote(key, inst)
            self.data.request_intraday(key, inst, 2)

    def _refresh_tiles(self):
        log.debug("Refreshing %d tiles", len(self.tile_instruments))
        for idx, inst in enumerate(self.tile_instruments):
            key = f"tile:{idx}"
            self.data.request_quote(key, inst)

    def _refresh_chart_states(self):
        """Repaint chart banners so the CLOSED badge updates near boundaries."""
        for panel in self.chart_panels:
            # Re-applying the existing quote re-evaluates is_closed via market
            panel.update_quote(panel.banner.quote, is_closed=None)
            panel.chart.update()

    # =========================================================================
    def _on_quote(self, key: str, quote):
        try:
            kind, idx_str = key.split(":")
            idx = int(idx_str)
            if kind == "chart" and idx < len(self.chart_panels):
                # Pass None so the panel derives is_closed from the Market
                self.chart_panels[idx].update_quote(quote, is_closed=None)
            elif kind == "tile" and idx < len(self.tile_widgets):
                self.tile_widgets[idx].set_quote(quote, is_closed=False)
        except Exception:
            log.error("_on_quote(%s) crashed:\n%s", key, traceback.format_exc())

    def _on_series(self, key: str, series):
        try:
            kind, idx_str = key.split(":")
            idx = int(idx_str)
            if kind == "chart" and idx < len(self.chart_panels):
                self.chart_panels[idx].update_series(series)
        except Exception:
            log.error("_on_series(%s) crashed:\n%s", key, traceback.format_exc())

    def closeEvent(self, ev):
        log.info("Window closeEvent — shutting down DataService.")
        self.data.stop()
        super().closeEvent(ev)
