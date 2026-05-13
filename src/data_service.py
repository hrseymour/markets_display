"""Background fetcher. Runs in a QThread so network IO never freezes the UI.

Emits signals when fresh data is ready. The main window reconnects which
instruments it wants whenever the region changes.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal, pyqtSlot

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
        q = self.dispatcher.get_quote(instrument)
        self.quote_ready.emit(key, q)

    @pyqtSlot(str, object, int)
    def fetch_intraday(self, key: str, instrument: dict, lookback_days: int):
        s = self.dispatcher.get_intraday(instrument, lookback_days)
        self.series_ready.emit(key, s)


class DataService(QObject):
    """Owns the worker thread and exposes a thin facade for the UI."""

    quote_ready = pyqtSignal(str, object)
    series_ready = pyqtSignal(str, object)

    _request_quote = pyqtSignal(str, object)
    _request_intraday = pyqtSignal(str, object, int)

    def __init__(self, dispatcher: ProviderDispatcher):
        super().__init__()
        self.thread = QThread()
        self.worker = FetchWorker(dispatcher)
        self.worker.moveToThread(self.thread)

        # Wire signals
        self._request_quote.connect(self.worker.fetch_quote)
        self._request_intraday.connect(self.worker.fetch_intraday)
        self.worker.quote_ready.connect(self.quote_ready)
        self.worker.series_ready.connect(self.series_ready)

        self.thread.start()

    def request_quote(self, key: str, instrument: dict):
        self._request_quote.emit(key, instrument)

    def request_intraday(self, key: str, instrument: dict, lookback_days: int = 2):
        self._request_intraday.emit(key, instrument, lookback_days)

    def stop(self):
        self.thread.quit()
        self.thread.wait(2000)
