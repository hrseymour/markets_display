"""Theme helpers — pulls colors and sizing from the loaded config."""
from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QColor


@dataclass
class Theme:
    up: QColor
    up_fill: QColor
    down: QColor
    down_fill: QColor
    neutral: QColor
    banner_bg: QColor
    banner_text: QColor
    axis: QColor
    grid: QColor
    prev_close_line: QColor
    tile_bg: QColor
    tile_border: QColor
    closed_badge_bg: QColor
    closed_badge_text: QColor
    background: QColor

    @classmethod
    def from_config(cls, cfg: dict) -> "Theme":
        c = cfg.get("colors", {})
        bg = cfg.get("display", {}).get("background", "#0A0E1A")
        return cls(
            up=QColor(c.get("up", "#00D964")),
            up_fill=QColor(c.get("up_fill", "#00D96433")),
            down=QColor(c.get("down", "#FF3B3B")),
            down_fill=QColor(c.get("down_fill", "#FF3B3B33")),
            neutral=QColor(c.get("neutral", "#888888")),
            banner_bg=QColor(c.get("banner_bg", "#1A1F2E")),
            banner_text=QColor(c.get("banner_text", "#FFFFFF")),
            axis=QColor(c.get("axis", "#3A4255")),
            grid=QColor(c.get("grid", "#1F2533")),
            prev_close_line=QColor(c.get("prev_close_line", "#FFB800")),
            tile_bg=QColor(c.get("tile_bg", "#141A26")),
            tile_border=QColor(c.get("tile_border", "#252C3E")),
            closed_badge_bg=QColor(c.get("closed_badge_bg", "#FF8A00")),
            closed_badge_text=QColor(c.get("closed_badge_text", "#0A0E1A")),
            background=QColor(bg),
        )

    def trend_color(self, change: float) -> QColor:
        if change > 0:
            return self.up
        if change < 0:
            return self.down
        return self.neutral

    def trend_fill(self, change: float) -> QColor:
        if change >= 0:
            return self.up_fill
        return self.down_fill
