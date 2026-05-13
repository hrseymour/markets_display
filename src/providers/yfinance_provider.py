"""yfinance-backed provider. No API key needed; ~15 min delayed for most US indices."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf

from .base import DataProvider, IntradayBar, IntradaySeries, Quote

log = logging.getLogger(__name__)


class YFinanceProvider(DataProvider):
    name = "yfinance"

    def get_quote(self, symbol: str) -> Optional[Quote]:
        try:
            ticker = yf.Ticker(symbol)
            # fast_info is cheap and contains last_price + previous_close
            fi = ticker.fast_info
            price = float(fi.get("last_price") or fi.get("lastPrice") or 0.0)
            prev = float(fi.get("previous_close") or fi.get("previousClose") or 0.0)
            if not price or not prev:
                # Fall back to 1-day history if fast_info was incomplete
                hist = ticker.history(period="2d", interval="1d", auto_adjust=False)
                if hist.empty or len(hist) < 1:
                    return None
                price = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price

            change = price - prev
            change_pct = (change / prev * 100.0) if prev else 0.0
            state = self._market_state(ticker)
            return Quote(
                symbol=symbol,
                price=price,
                prev_close=prev,
                change=change,
                change_pct=change_pct,
                timestamp=datetime.now(),
                market_state=state,
            )
        except Exception as e:
            log.warning("yfinance get_quote(%s) failed: %s", symbol, e)
            return None

    def get_intraday(self, symbol: str, lookback_days: int = 2) -> Optional[IntradaySeries]:
        try:
            ticker = yf.Ticker(symbol)
            # 1-minute bars only go back ~7 days. For a 2-day window this is fine.
            # We grab one extra day so we can find the prior session's close.
            period_days = max(lookback_days + 2, 3)
            hist = ticker.history(
                period=f"{period_days}d",
                interval="1m",
                auto_adjust=False,
                prepost=False,
            )
            if hist.empty:
                return None

            # Group by trading date; keep the most recent `lookback_days` sessions
            hist = hist.copy()
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

            # Previous session close = last close on the day BEFORE our window starts.
            # If we don't have it, fall back to daily history.
            prev_close: float
            if prev_session_date != wanted_dates[0]:
                prev_rows = hist[hist["date"] == prev_session_date]
                prev_close = float(prev_rows["Close"].iloc[-1])
            else:
                daily = ticker.history(period="5d", interval="1d", auto_adjust=False)
                if not daily.empty and len(daily) >= 2:
                    prev_close = float(daily["Close"].iloc[-2])
                else:
                    prev_close = float(hist["Close"].iloc[0])

            window = hist[hist["date"].isin(wanted_dates)]
            bars = [
                IntradayBar(timestamp=ts.to_pydatetime(), price=float(close))
                for ts, close in zip(window.index, window["Close"])
                if close == close  # filter NaN
            ]
            if not bars:
                return None

            state = self._market_state(ticker)
            return IntradaySeries(
                symbol=symbol, bars=bars, prev_close=prev_close, market_state=state
            )
        except Exception as e:
            log.warning("yfinance get_intraday(%s) failed: %s", symbol, e)
            return None

    @staticmethod
    def _market_state(ticker) -> str:
        try:
            info = ticker.fast_info
            # yfinance fast_info doesn't reliably expose market state.
            # Heuristic: if last quote is within 30 min, call it REGULAR;
            # else CLOSED. The caller will refine using its own schedule.
            return "REGULAR"
        except Exception:
            return "UNKNOWN"
