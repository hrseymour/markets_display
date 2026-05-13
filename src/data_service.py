"""Background fetcher using a ThreadPoolExecutor.

Why not QThread/pyqtSignal? yfinance uses curl_cffi under the hood, which
has known segfault issues when its HTTP connections are torn down across
Qt's cross-thread signal machinery on Linux glibc. Plain Python threads
that return futures avoid that path entirely.

Approach: when the UI wants data, we submit a callable to a thread pool
and store the resulting Future. A QTimer on the main thread polls all
in-flight Futures every 100ms. When one is done, we call the result
handler on the main thread.

This keeps the UI responsive and bypasses Qt's cross-thread signal
marshaling for the data payload.
"""
from __future__ import annotations

import logging
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Dict, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .providers import IntradaySeries, ProviderDispatcher, Quote

log = logging.getLogger(__name__)


class DataService(QObject):
    """Owns a thread pool and a poller. Exposes Qt signals to the UI.

    Signals are emitted on the MAIN thread (the QTimer runs there), so they
    can safely update UI widgets directly.
    """

    quote_ready = pyqtSignal(str, object)
    series_ready = pyqtSignal(str, object)

    def __init__(self, dispatcher: ProviderDispatcher, max_workers: int = 4):
        super().__init__()
        self.dispatcher = dispatcher
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="DataFetch"
        )
        # Pending futures keyed by full_key; value = (future, kind)
        # where kind is "quote" or "series"
        self._pending: Dict[str, tuple] = {}
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()
        log.info("DataService (thread-pool) started with %d workers.", max_workers)

    # -------------------------------------------------------------------------
    def request_quote(self, key: str, instrument: dict):
        full_key = f"{key}#quote"
        if full_key in self._pending:
            return  # older request still in flight; skip
        fut = self.executor.submit(self._do_get_quote, key, instrument)
        self._pending[full_key] = (fut, "quote")

    def request_intraday(self, key: str, instrument: dict, lookback_days: int = 2):
        full_key = f"{key}#series"
        if full_key in self._pending:
            return
        fut = self.executor.submit(
            self._do_get_intraday, key, instrument, lookback_days
        )
        self._pending[full_key] = (fut, "series")

    # -------------------------------------------------------------------------
    # Worker functions — run in the thread pool
    # -------------------------------------------------------------------------
    def _do_get_quote(self, key: str, instrument: dict) -> Optional[Quote]:
        try:
            return self.dispatcher.get_quote(instrument)
        except Exception:
            log.error("Quote fetch for %s crashed:\n%s", key, traceback.format_exc())
            return None

    def _do_get_intraday(
        self, key: str, instrument: dict, lookback_days: int
    ) -> Optional[IntradaySeries]:
        try:
            return self.dispatcher.get_intraday(instrument, lookback_days)
        except Exception:
            log.error(
                "Intraday fetch for %s crashed:\n%s", key, traceback.format_exc()
            )
            return None

    # -------------------------------------------------------------------------
    # Poller — runs on the main thread via QTimer
    # -------------------------------------------------------------------------
    def _poll(self):
        if not self._pending:
            return
        done_keys = []
        for full_key, (fut, kind) in self._pending.items():
            if not fut.done():
                continue
            done_keys.append(full_key)
            try:
                result = fut.result(timeout=0)
            except Exception:
                log.error(
                    "Future %s raised in result():\n%s",
                    full_key, traceback.format_exc(),
                )
                result = None

            ui_key = full_key.split("#")[0]
            try:
                if kind == "quote":
                    self.quote_ready.emit(ui_key, result)
                else:
                    self.series_ready.emit(ui_key, result)
            except Exception:
                log.error(
                    "Emit for %s failed:\n%s", full_key, traceback.format_exc()
                )

        for k in done_keys:
            self._pending.pop(k, None)

    # -------------------------------------------------------------------------
    def stop(self):
        log.info("DataService stopping...")
        self._poll_timer.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
