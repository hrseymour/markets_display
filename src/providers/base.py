"""
Base class for market-data providers.

To add a new provider:
  1. Create providers/<vendor>.py
  2. Subclass DataProvider and implement get_quote() and get_intraday()
  3. Register it in providers/__init__.py
  4. Add a `<vendor>:` block in config.yaml under `providers:`
  5. Add `<vendor>: "TICKER"` under each instrument's `symbols:` block

That's all. The dispatcher will pick it up.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional


@dataclass
class Quote:
    """Snapshot quote for a single instrument."""
    symbol: str
    price: float
    prev_close: float
    change: float            # price - prev_close
    change_pct: float        # (price - prev_close) / prev_close * 100
    timestamp: datetime
    market_state: str = "REGULAR"  # REGULAR | CLOSED | PRE | POST | UNKNOWN


@dataclass
class IntradayBar:
    """One point on the intraday line."""
    timestamp: datetime
    price: float


@dataclass
class IntradaySeries:
    """A run of intraday bars with per-session reference closes.

    `prev_close` is the close immediately before the most recent session
    in `bars` — used to compute change/change_pct in the banner.

    `prev_closes_by_date` maps each trading date present in `bars` to the
    reference close for THAT day (the close of the session immediately
    before that day). The chart uses this to draw one dashed line per
    session, anchored to that session's own reference.
    """
    symbol: str
    bars: List[IntradayBar]
    prev_close: float
    prev_closes_by_date: Dict[date, float] = field(default_factory=dict)
    market_state: str = "REGULAR"


class DataProvider(ABC):
    """Abstract base for any quote source."""

    name: str = "base"  # subclass overrides

    def __init__(self, config: dict):
        self.config = config or {}

    @abstractmethod
    def get_quote(self, symbol: str) -> Optional[Quote]:
        """Return a single snapshot quote, or None on failure."""
        raise NotImplementedError

    @abstractmethod
    def get_intraday(self, symbol: str, lookback_days: int = 2) -> Optional[IntradaySeries]:
        """
        Return intraday bars for the last `lookback_days` sessions, with a
        per-session prev_close map (see IntradaySeries).
        Return None on failure so the dispatcher can fall through to the next
        provider.
        """
        raise NotImplementedError
