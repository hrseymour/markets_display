"""Provider registry and dispatcher.

The dispatcher tries providers in the order configured in YAML, falling through
on None or exception. Each instrument's `symbols:` block tells the dispatcher
which ticker to ask each provider for.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .base import DataProvider, IntradaySeries, Quote
from .eodhd_provider import EODHDProvider
from .yfinance_provider import YFinanceProvider

log = logging.getLogger(__name__)

# Register provider classes here. The key must match what the YAML uses
# (under `providers:` and inside each instrument's `symbols:` block).
PROVIDER_CLASSES = {
    "yfinance": YFinanceProvider,
    "eodhd": EODHDProvider,
}


class ProviderDispatcher:
    """Picks the right provider for each instrument and falls through on failure."""

    def __init__(self, providers_config: dict):
        self.order: List[str] = providers_config.get("order", ["yfinance"])
        self.instances: Dict[str, DataProvider] = {}
        for name in self.order:
            cfg = providers_config.get(name, {})
            if not cfg.get("enabled", True):
                continue
            klass = PROVIDER_CLASSES.get(name)
            if not klass:
                log.warning("Unknown provider in config: %s", name)
                continue
            try:
                self.instances[name] = klass(cfg)
                log.info("Initialized provider: %s", name)
            except Exception as e:
                log.error("Failed to init provider %s: %s", name, e)

    # -------------------------------------------------------------------------
    def get_quote(self, instrument: dict) -> Optional[Quote]:
        """`instrument` is a dict with at least a `symbols` sub-dict."""
        forced = instrument.get("provider")
        order = [forced] if forced else self.order
        symbols = instrument.get("symbols", {})
        for name in order:
            if name not in self.instances or name not in symbols:
                continue
            q = self.instances[name].get_quote(symbols[name])
            if q is not None:
                return q
        return None

    def get_intraday(self, instrument: dict, lookback_days: int = 2) -> Optional[IntradaySeries]:
        forced = instrument.get("provider")
        order = [forced] if forced else self.order
        symbols = instrument.get("symbols", {})
        for name in order:
            if name not in self.instances or name not in symbols:
                continue
            s = self.instances[name].get_intraday(symbols[name], lookback_days)
            if s is not None:
                return s
        return None


__all__ = ["DataProvider", "ProviderDispatcher", "Quote", "IntradaySeries", "PROVIDER_CLASSES"]
