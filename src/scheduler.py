"""Time-of-day region scheduler.

Given the YAML `schedule` block, returns which chart_set and tile_set are
active right now. Handles wrap-around past midnight.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo


@dataclass
class ActiveWindow:
    name: str
    chart_set: str
    tile_set: str


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _in_window(now_t: time, start: time, end: time) -> bool:
    """True if now_t falls inside [start, end), with wrap-around at midnight.

    If end is 00:00 it's treated as end-of-day (24:00) for the comparison.
    """
    if end == time(0, 0):
        return now_t >= start  # runs from start through midnight
    if start <= end:
        return start <= now_t < end
    # wraps midnight
    return now_t >= start or now_t < end


class Scheduler:
    def __init__(self, schedule_config: dict):
        self.tz = ZoneInfo(schedule_config.get("timezone", "America/Los_Angeles"))
        self.windows = []
        for w in schedule_config.get("windows", []):
            self.windows.append({
                "name": w["name"],
                "start": _parse_hhmm(w["start"]),
                "end": _parse_hhmm(w["end"]),
                "chart_set": w["chart_set"],
                "tile_set": w["tile_set"],
            })
        if not self.windows:
            raise ValueError("schedule.windows is empty")

    def active(self, now: Optional[datetime] = None) -> ActiveWindow:
        now = (now or datetime.now(self.tz)).astimezone(self.tz)
        now_t = now.time().replace(microsecond=0)
        for w in self.windows:
            if _in_window(now_t, w["start"], w["end"]):
                return ActiveWindow(
                    name=w["name"], chart_set=w["chart_set"], tile_set=w["tile_set"]
                )
        # Fallback to first window if nothing matched (shouldn't happen with
        # well-formed config covering 24h)
        w = self.windows[0]
        return ActiveWindow(name=w["name"], chart_set=w["chart_set"], tile_set=w["tile_set"])
