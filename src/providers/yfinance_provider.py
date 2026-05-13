"""yfinance-backed provider. No API key needed; ~15 min delayed for most US indices.

Guarantees that no NaN/inf prices ever escape this module. yfinance returns
NaN for off-hours minutes and partial bars, which would crash QPainter
downstream.

Also populates `prev_closes_by_date` so the chart can draw one dashed
reference line per session (each session's line at its OWN prior close).
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from typing import Dict, Optional

import yfinance as yf

from .base import DataProvider, IntradayBar, IntradaySeries, Quote

log = logging.getLogger(__name__)


def _finite(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _safe_float(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


class YFinanceProvider(DataProvider):
    name = "yfinance"

    def _build_quote(self, symbol: str, price: float, prev: float) -> Optional[Quote]:
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
            # Grab enough days that we have at least one extra session ahead
            # of `lookback_days` to anchor the first day's reference line.
            period_days = max(lookback_days + 3, 5)
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
            window = hist[hist["date"].isin(wanted_dates)]

            bars = []
            for ts, close in zip(window.index, window["Close"]):
                price = _safe_float(close, default=float("nan"))
                if not _finite(price):
                    continue
                bars.append(IntradayBar(timestamp=ts.to_pydatetime(), price=price))

            if not bars:
                return None

            # ---------------------------------------------------------------
            # Per-session previous closes. For each session in wanted_dates,
            # find the close of the session immediately before it. Prefer
            # the prior session's intraday last-close; fall back to daily.
            # ---------------------------------------------------------------
            prev_closes_by_date: Dict[date, float] = {}

            daily_closes: Dict[date, float] = {}
            try:
                daily = ticker.history(
                    period=f"{period_days + 5}d",
                    interval="1d",
                    auto_adjust=False,
                )
                if daily is not None and not daily.empty:
                    daily = daily[daily["Close"].notna()]
                    for ts, close in zip(daily.index, daily["Close"]):
                        c = _safe_float(close, default=float("nan"))
                        if _finite(c):
                            d = ts.date() if hasattr(ts, "date") else ts
                            daily_closes[d] = c
            except Exception as e:
                log.debug("yfinance %s: daily history fallback failed: %s", symbol, e)

            for target_date in wanted_dates:
                prior_intraday = [d for d in unique_dates if d < target_date]
                anchor: Optional[float] = None
                if prior_intraday:
                    prior_date = prior_intraday[-1]
                    prior_rows = hist[hist["date"] == prior_date]
                    if not prior_rows.empty:
                        candidate = _safe_float(
                            prior_rows["Close"].iloc[-1], default=float("nan")
                        )
                        if _finite(candidate):
                            anchor = candidate

                if anchor is None:
                    daily_priors = sorted(
                        d for d in daily_closes.keys() if d < target_date
                    )
                    if daily_priors:
                        anchor = daily_closes[daily_priors[-1]]

                if anchor is not None and _finite(anchor):
                    prev_closes_by_date[target_date] = anchor

            latest_date = wanted_dates[-1]
            prev_close = prev_closes_by_date.get(latest_date)
            if prev_close is None or not _finite(prev_close):
                prev_close = bars[0].price

            log.debug(
                "yfinance %s: returning %d bars, prev_close=%.2f, sessions=%s",
                symbol, len(bars), prev_close, len(prev_closes_by_date),
            )
            return IntradaySeries(
                symbol=symbol,
                bars=bars,
                prev_close=prev_close,
                prev_closes_by_date=prev_closes_by_date,
            )
        except Exception as e:
            log.warning("yfinance get_intraday(%s) failed: %s", symbol, e, exc_info=True)
            return None
