"""yfinance-backed provider. No API key needed; ~15 min delayed for most US indices.

Guarantees that no NaN/inf prices ever escape this module. yfinance returns
NaN for off-hours minutes and partial bars, which would crash QPainter
downstream.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf

from .base import DataProvider, IntradayBar, IntradaySeries, Quote

log = logging.getLogger(__name__)


def _finite(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _safe_float(x, default: float = 0.0) -> float:
    """Coerce to a finite float, or return default."""
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


class YFinanceProvider(DataProvider):
    name = "yfinance"

    def _build_quote(self, symbol: str, price: float, prev: float) -> Optional[Quote]:
        """Construct a Quote, validating every numeric field. Returns None if
        the inputs can't produce a sane Quote."""
        if not (_finite(price) and _finite(prev)) or price <= 0 or prev <= 0:
            return None
        change = price - prev
        change_pct = (change / prev * 100.0)
        if not (_finite(change) and _finite(change_pct)):
            return None
        return Quote(
            symbol=symbol,
            price=price,
            prev_close=prev,
            change=change,
            change_pct=change_pct,
            timestamp=datetime.now(),
            market_state="REGULAR",
        )

    def get_quote(self, symbol: str) -> Optional[Quote]:
        try:
            ticker = yf.Ticker(symbol)
            fi = ticker.fast_info
            price = _safe_float(fi.get("last_price") or fi.get("lastPrice"))
            prev = _safe_float(fi.get("previous_close") or fi.get("previousClose"))

            q = self._build_quote(symbol, price, prev)
            if q is not None:
                return q

            # Fall back to history
            hist = ticker.history(period="2d", interval="1d", auto_adjust=False)
            if hist is None or hist.empty:
                return None
            hist = hist[hist["Close"].notna()]
            if hist.empty:
                return None
            price = _safe_float(hist["Close"].iloc[-1])
            prev = _safe_float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price
            return self._build_quote(symbol, price, prev)

        except Exception as e:
            log.warning("yfinance get_quote(%s) failed: %s", symbol, e)
            return None

    def get_intraday(self, symbol: str, lookback_days: int = 2) -> Optional[IntradaySeries]:
        try:
            ticker = yf.Ticker(symbol)
            period_days = max(lookback_days + 2, 3)
            hist = ticker.history(
                period=f"{period_days}d",
                interval="1m",
                auto_adjust=False,
                prepost=False,
            )
            if hist is None or hist.empty:
                return None

            hist = hist[hist["Close"].notna()].copy()
            if hist.empty:
                return None

            hist["date"] = hist.index.date
            unique_dates = sorted(hist["date"].unique())
            if len(unique_dates) < 1:
                return None

            wanted_dates = unique_dates[-lookback_days:]
            prev_session_date = (
                unique_dates[-(lookback_days + 1)]
                if len(unique_dates) > lookback_days
                else unique_dates[0]
            )

            prev_close: Optional[float] = None
            if prev_session_date != wanted_dates[0]:
                prev_rows = hist[hist["date"] == prev_session_date]
                if not prev_rows.empty:
                    candidate = _safe_float(prev_rows["Close"].iloc[-1], default=float("nan"))
                    if _finite(candidate):
                        prev_close = candidate

            if prev_close is None:
                daily = ticker.history(period="5d", interval="1d", auto_adjust=False)
                if not daily.empty:
                    daily = daily[daily["Close"].notna()]
                if not daily.empty and len(daily) >= 2:
                    candidate = _safe_float(daily["Close"].iloc[-2], default=float("nan"))
                    if _finite(candidate):
                        prev_close = candidate

            if prev_close is None:
                first_price = _safe_float(hist["Close"].iloc[0], default=float("nan"))
                if not _finite(first_price):
                    return None
                prev_close = first_price

            window = hist[hist["date"].isin(wanted_dates)]

            bars = []
            for ts, close in zip(window.index, window["Close"]):
                price = _safe_float(close, default=float("nan"))
                if not _finite(price):
                    continue
                bars.append(IntradayBar(timestamp=ts.to_pydatetime(), price=price))

            if not bars:
                return None

            log.debug(
                "yfinance %s: returning %d bars, prev_close=%.2f",
                symbol, len(bars), prev_close,
            )
            return IntradaySeries(symbol=symbol, bars=bars, prev_close=prev_close)
        except Exception as e:
            log.warning("yfinance get_intraday(%s) failed: %s", symbol, e, exc_info=True)
            return None
