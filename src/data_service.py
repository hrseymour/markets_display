"""Background fetcher. Runs in a QThread so network IO never freezes the UI.

Emits signals when fresh data is ready. The main window reconnects which
instruments it wants whenever the region changes.

Every worker method is wrapped so any exception is logged with a full
traceback and routed back to the main thread as a `None` payload — Qt
threads must NEVER let exceptions escape into the event loop.
"""
from __future__ import annotations

import logging
import traceback
from typing import Dict, List, Optional

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal, pyqtSlot

from .providers import IntradaySeries, ProviderDispatcher, Quote

log = logging.getLogger(__name__)


class FetchWorker(QObject):
    """Lives on a worker QThread. Fetches on demand."""

    quote_ready = pyqtSignal(str, object)        # (instrument_key, Quote|None)
    series_ready = pyqtSignal(str, object)       # (instrument_key, IntradaySeries|None)

    def __init__(self, dispatcher: ProviderDispatcher):
        super().__init__()
        self.dispatcher = dispatcher

    @pyqtSlot(str, object)
    def fetch_quote(self, key: str, instrument: dict):
        try:
            q = self.dispatcher.get_quote(instrument)
            self.quote_ready.emit(key, q)
        except Exception:
            log.error(
                "fetch_quote(%s) crashed:\n%s", key, traceback.format_exc()
            )
            try:
                self.quote_ready.emit(key, None)
            except Exception:
                log.exception("Even the failure emit crashed for %s", key)

    @pyqtSlot(str, object, int)
    def fetch_intraday(self, key: str, instrument: dict, lookback_days: int):
        try:
            s = self.dispatcher.get_intraday(instrument, lookback_days)
            self.series_ready.emit(key, s)
        except Exception:
            log.error(
                "fetch_intraday(%s) crashed:\n%s", key, traceback.format_exc()
            )
            try:
                self.series_ready.emit(key, None)
            except Exception:
                log.exception("Even the failure emit crashed for %s", key)


class DataService(QObject):
    """Owns the worker thread and exposes a thin facade for the UI."""

    quote_ready = pyqtSignal(str, object)
    series_ready = pyqtSignal(str, object)

    _request_quote = pyqtSignal(str, object)
    _request_intraday = pyqtSignal(str, object, int)

    def __init__(self, dispatcher: ProviderDispatcher):
        super().__init__()
        self.thread = QThread()
        self.thread.setObjectName("FetchWorkerThread")
        self.worker = FetchWorker(dispatcher)
        self.worker.moveToThread(self.thread)

        # Cross-thread signal wiring. We explicitly use QueuedConnection so
        # the slot runs on the destination thread's event loop. AutoConnection
        # *should* pick this, but being explicit avoids surprises.
        self._request_quote.connect(
            self.worker.fetch_quote, Qt.ConnectionType.QueuedConnection
        )
        self._request_intraday.connect(
            self.worker.fetch_intraday, Qt.ConnectionType.QueuedConnection
        )
        self.worker.quote_ready.connect(
            self.quote_ready, Qt.ConnectionType.QueuedConnection
        )
        self.worker.series_ready.connect(
            self.series_ready, Qt.ConnectionType.QueuedConnection
        )

        self.thread.start()
        log.info("DataService thread started.")

    def request_quote(self, key: str, instrument: dict):
        self._request_quote.emit(key, instrument)

    def request_intraday(self, key: str, instrument: dict, lookback_days: int = 2):
        self._request_intraday.emit(key, instrument, lookback_days)

    def stop(self):
        log.info("DataService stopping...")
        self.thread.quit()
        self.thread.wait(2000)
