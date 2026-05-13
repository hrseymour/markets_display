"""EOD Historical Data (eodhd.com) provider.

The "All World" subscription is end-of-day. We use it for:
  - Reliable previous-day closes
  - Tile pricing fallback when yfinance is flaky
  - End-of-day points on charts when intraday isn't subscribed

The API key is read from env var EODHD_API_KEY. Do NOT put it in YAML.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import requests

from .base import DataProvider, IntradayBar, IntradaySeries, Quote

log = logging.getLogger(__name__)


class EODHDProvider(DataProvider):
    name = "eodhd"

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = self.config.get("base_url", "https://eodhistoricaldata.com/api")
        self.api_key = os.environ.get("EODHD_API_KEY", "")
        if not self.api_key:
            log.warning("EODHD_API_KEY not set; EODHD provider will return None.")

    # -------------------------------------------------------------------------
    def get_quote(self, symbol: str) -> Optional[Quote]:
        if not self.api_key:
            return None
        try:
            url = f"{self.base_url}/real-time/{symbol}"
            params = {"api_token": self.api_key, "fmt": "json"}
            r = requests.get(url, params=params, timeout=8)
            r.raise_for_status()
            data = r.json()
            price = float(data.get("close") or 0)
            prev = float(data.get("previousClose") or 0)
            if not price or not prev:
                return None
            change = price - prev
            change_pct = (change / prev * 100.0) if prev else 0.0
            return Quote(
                symbol=symbol,
                price=price,
                prev_close=prev,
                change=change,
                change_pct=change_pct,
                timestamp=datetime.now(),
                market_state="REGULAR",
            )
        except Exception as e:
            log.warning("EODHD get_quote(%s) failed: %s", symbol, e)
            return None

    # -------------------------------------------------------------------------
    def get_intraday(self, symbol: str, lookback_days: int = 2) -> Optional[IntradaySeries]:
        """
        EODHD intraday requires the Intraday Historical add-on. Most "All World"
        subs do NOT include it, so this will frequently return None — which is
        the correct fallthrough behavior for the dispatcher.
        """
        if not self.api_key:
            return None
        try:
            now = datetime.utcnow()
            start = now - timedelta(days=lookback_days + 2)
            url = f"{self.base_url}/intraday/{symbol}"
            params = {
                "api_token": self.api_key,
                "interval": "1m",
                "from": int(start.timestamp()),
                "to": int(now.timestamp()),
                "fmt": "json",
            }
            r = requests.get(url, params=params, timeout=12)
            if r.status_code == 402 or r.status_code == 403:
                log.info("EODHD intraday not available on this subscription (%s).", r.status_code)
                return None
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list) or not data:
                return None

            bars = []
            for row in data:
                ts = row.get("datetime") or row.get("timestamp")
                close = row.get("close")
                if ts is None or close is None:
                    continue
                if isinstance(ts, (int, float)):
                    dt = datetime.utcfromtimestamp(ts)
                else:
                    dt = datetime.fromisoformat(str(ts).replace("Z", ""))
                bars.append(IntradayBar(timestamp=dt, price=float(close)))

            if not bars:
                return None

            # Previous close from the daily EOD endpoint
            prev_close = self._daily_prev_close(symbol) or bars[0].price
            return IntradaySeries(symbol=symbol, bars=bars, prev_close=prev_close)
        except Exception as e:
            log.warning("EODHD get_intraday(%s) failed: %s", symbol, e)
            return None

    # -------------------------------------------------------------------------
    def _daily_prev_close(self, symbol: str) -> Optional[float]:
        try:
            url = f"{self.base_url}/eod/{symbol}"
            params = {"api_token": self.api_key, "fmt": "json", "period": "d", "order": "d"}
            r = requests.get(url, params=params, timeout=8)
            r.raise_for_status()
            rows = r.json()
            if not rows or len(rows) < 2:
                return None
            # Newest-first because of order=d; index 1 = previous session
            return float(rows[1].get("close"))
        except Exception:
            return None
