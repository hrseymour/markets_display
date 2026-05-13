"""Main window. Charts row on top, tiles grid on bottom.

When the active region changes (e.g. North America → Asia), the window
swaps both the chart instruments and the tile instruments based on YAML.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QCursor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from .data_service import DataService
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
        self.dispatcher = ProviderDispatcher(config.get("providers", {}))
        self.data = DataService(self.dispatcher)
        self.data.quote_ready.connect(self._on_quote)
        self.data.series_ready.connect(self._on_series)

        # Track currently-displayed instruments keyed by widget slot
        self.chart_panels: List[ChartPanel] = []
        self.tile_widgets: List[BannerWidget] = []
        self.chart_instruments: List[dict] = []
        self.tile_instruments: List[dict] = []
        self.active_region: Optional[str] = None

        self._build_ui()
        self._install_shortcuts()
        self._apply_window_settings()

        # Refresh timers
        refresh = config.get("refresh", {})
        self.chart_timer = QTimer(self)
        self.chart_timer.setInterval(int(refresh.get("chart_seconds", 60)) * 1000)
        self.chart_timer.timeout.connect(self._refresh_charts)
        self.chart_timer.start()

        self.tile_timer = QTimer(self)
        self.tile_timer.setInterval(int(refresh.get("tile_seconds", 60)) * 1000)
        self.tile_timer.timeout.connect(self._refresh_tiles)
        self.tile_timer.start()

        # Region check (cheap) every 30s
        self.region_timer = QTimer(self)
        self.region_timer.setInterval(30_000)
        self.region_timer.timeout.connect(self._check_region)
        self.region_timer.start()

        # Initial population
        self._check_region(force=True)

    # =========================================================================
    # UI construction
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

        # --- Charts row ---
        self.charts_row = QWidget()
        charts_layout = QHBoxLayout(self.charts_row)
        charts_layout.setContentsMargins(0, 0, 0, 0)
        charts_layout.setSpacing(self._scaled(layout_cfg.get("chart_gap", 16)))
        self.charts_layout = charts_layout

        # --- Tiles grid ---
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
        # Resolution
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
        self.setWindowTitle("Market Display")

    def _install_shortcuts(self):
        # Esc to exit fullscreen / quit (handy on the Pi)
        QShortcut(QKeySequence("Esc"), self, activated=self.close)
        QShortcut(QKeySequence("F11"), self, activated=self._toggle_fullscreen)
        QShortcut(QKeySequence("R"), self, activated=lambda: self._refresh_all())

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _scaled(self, px_at_1080p: int) -> int:
        """Scale a 1080p-baseline pixel size to the actual screen height."""
        screen = self.screen() if hasattr(self, "screen") else None
        h = screen.size().height() if screen else 1080
        factor = h / 1080.0
        return max(1, int(round(px_at_1080p * factor)))

    # =========================================================================
    # Region switching
    # =========================================================================
    def _check_region(self, force: bool = False):
        active = self.scheduler.active()
        if not force and active.name == self.active_region:
            return
        log.info("Switching to region: %s", active.name)
        self.active_region = active.name
        self._load_chart_set(active.chart_set)
        self._load_tile_set(active.tile_set)
        self._refresh_all()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _load_chart_set(self, set_name: str):
        instruments = self.config.get("charts", {}).get(set_name, [])
        self._clear_layout(self.charts_layout)
        self.chart_panels = []
        self.chart_instruments = []
        banner_h = self._scaled(96)
        for inst in instruments:
            panel = ChartPanel(self.theme, inst)
            panel.banner.setMinimumHeight(banner_h)
            panel.banner.setMaximumHeight(banner_h)
            self.charts_layout.addWidget(panel, stretch=1)
            self.chart_panels.append(panel)
            self.chart_instruments.append(inst)

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

    # =========================================================================
    # Data refresh
    # =========================================================================
    def _refresh_all(self):
        self._refresh_charts()
        self._refresh_tiles()

    def _refresh_charts(self):
        for idx, inst in enumerate(self.chart_instruments):
            key = f"chart:{idx}"
            self.data.request_quote(key, inst)
            self.data.request_intraday(key, inst, 2)

    def _refresh_tiles(self):
        for idx, inst in enumerate(self.tile_instruments):
            key = f"tile:{idx}"
            self.data.request_quote(key, inst)

    # =========================================================================
    # Slots from DataService
    # =========================================================================
    def _on_quote(self, key: str, quote):
        kind, idx_str = key.split(":")
        idx = int(idx_str)
        is_closed = self._is_market_closed_for_active_region()
        if kind == "chart" and idx < len(self.chart_panels):
            self.chart_panels[idx].update_quote(quote, is_closed=is_closed)
        elif kind == "tile" and idx < len(self.tile_widgets):
            self.tile_widgets[idx].set_quote(quote, is_closed=False)

    def _on_series(self, key: str, series):
        kind, idx_str = key.split(":")
        idx = int(idx_str)
        if kind == "chart" and idx < len(self.chart_panels):
            self.chart_panels[idx].update_series(series)

    def _is_market_closed_for_active_region(self) -> bool:
        """Weekend = closed for North America. (Asia/Europe weekend rules vary;
        we keep this simple.) Returns True only on weekends for North America."""
        if self.active_region != "north_america":
            return False
        return datetime.now().weekday() >= 5  # 5=Sat, 6=Sun

    # =========================================================================
    def closeEvent(self, ev):
        self.data.stop()
        super().closeEvent(ev)
