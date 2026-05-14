"""Market session model.

A Market is a named exchange context with a timezone and one or more
trading sessions per day. For chart placement we treat each session as
spanning from `open` to `close` in the market's local time.

For markets with a lunch break (Japan, Hong Kong, China), we use a SINGLE
session spanning the gross day — open of morning session to close of
afternoon session. The line will appear flat during the lunch break,
which is honest enough (trading is paused).

Public API:
    Market.from_dict(name, dict)           -> Market
    market.now_local()                     -> datetime in market tz
    market.is_open(now=None)               -> bool
    market.fraction_for(ts)                -> float in [0, 1] (session position)
    market.local_date_today(now=None)      -> date in market tz (the "today"
                                              for chart filtering)
    market.most_recent_session_date(bars)  -> date of last session that has bars
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


@dataclass(frozen=True)
class Session:
    open: time
    close: time

    def contains(self, t: time) -> bool:
        return self.open <= t <= self.close

    def total_minutes(self) -> int:
        return (self.close.hour - self.open.hour) * 60 + (self.close.minute - self.open.minute)


@dataclass
class Market:
    name: str
    tz: ZoneInfo
    # We use a SINGLE effective session spanning open-of-first to close-of-last.
    # Lunch breaks render as flat segments, which is fine.
    session: Session

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "Market":
        tz = ZoneInfo(d["timezone"])
        sessions_raw = d.get("sessions") or []
        if not sessions_raw:
            raise ValueError(f"Market {name!r}: no sessions defined")
        opens = [_parse_hhmm(s["open"]) for s in sessions_raw]
        closes = [_parse_hhmm(s["close"]) for s in sessions_raw]
        effective = Session(open=min(opens), close=max(closes))
        return cls(name=name, tz=tz, session=effective)

    # ------------------------------------------------------------------
    def now_local(self, now: Optional[datetime] = None) -> datetime:
        if now is None:
            now = datetime.now(tz=self.tz)
        elif now.tzinfo is None:
            # Naive datetime — assume it's UTC, then convert
            now = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(self.tz)
        else:
            now = now.astimezone(self.tz)
        return now

    def local_date_today(self, now: Optional[datetime] = None) -> date:
        """Return 'today' in the market's timezone."""
        return self.now_local(now).date()

    def is_open(self, now: Optional[datetime] = None) -> bool:
        """True if the market is currently in its trading session.

        Note: we do NOT check holidays here. Holidays are detected naturally
        by 'is there any bar for today in the data' — see the chart code.
        Weekends are checked explicitly.
        """
        local = self.now_local(now)
        # Saturday=5, Sunday=6
        if local.weekday() >= 5:
            return False
        t = local.time().replace(microsecond=0)
        return self.session.open <= t <= self.session.close

    def fraction_for(self, ts: datetime) -> float:
        """Return where `ts` falls within the session as a fraction [0, 1].

        Values outside the session are clamped. `ts` is converted to the
        market's local timezone first.
        """
        local = self.now_local(ts)
        t = local.time()
        # Minutes since midnight
        ts_minutes = t.hour * 60 + t.minute + t.second / 60.0
        open_minutes = self.session.open.hour * 60 + self.session.open.minute
        close_minutes = self.session.close.hour * 60 + self.session.close.minute
        if close_minutes <= open_minutes:
            return 0.0
        frac = (ts_minutes - open_minutes) / (close_minutes - open_minutes)
        return max(0.0, min(1.0, frac))

    def progress_now(self, now: Optional[datetime] = None) -> float:
        """How far we are into today's session, as a fraction [0, 1].

        Returns 0.0 before open, 1.0 after close (or on weekends).
        """
        local = self.now_local(now)
        if local.weekday() >= 5:
            return 1.0  # weekend — show last session fully
        t = local.time()
        open_t = self.session.open
        close_t = self.session.close
        if t < open_t:
            return 0.0
        if t > close_t:
            return 1.0
        ts_minutes = t.hour * 60 + t.minute + t.second / 60.0
        open_minutes = open_t.hour * 60 + open_t.minute
        close_minutes = close_t.hour * 60 + close_t.minute
        if close_minutes <= open_minutes:
            return 1.0
        return (ts_minutes - open_minutes) / (close_minutes - open_minutes)


def load_markets(markets_cfg: dict) -> dict:
    """Build {name: Market} from the YAML `markets:` block."""
    out = {}
    for name, d in (markets_cfg or {}).items():
        try:
            out[name] = Market.from_dict(name, d)
        except Exception as e:
            # Don't crash the whole app on one bad market entry
            import logging
            logging.getLogger(__name__).warning(
                "Failed to parse market %r: %s", name, e
            )
    return out
