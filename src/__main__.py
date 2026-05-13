"""Application entry point.

Usage:
    python -m src                  # uses config/config.yaml
    python -m src --config path/to/other.yaml
    python -m src --windowed       # disables fullscreen for dev
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import threading
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# Install exception hooks BEFORE importing Qt, so anything that blows up
# during Qt initialization is also visible.
# ---------------------------------------------------------------------------
def _sys_excepthook(exc_type, exc_value, exc_tb):
    print("=" * 70, file=sys.stderr)
    print("UNCAUGHT EXCEPTION (main thread):", file=sys.stderr)
    traceback.print_exception(exc_type, exc_value, exc_tb, file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    sys.stderr.flush()


def _thread_excepthook(args):
    print("=" * 70, file=sys.stderr)
    print(f"UNCAUGHT EXCEPTION (thread: {args.thread.name}):", file=sys.stderr)
    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    sys.stderr.flush()


sys.excepthook = _sys_excepthook
threading.excepthook = _thread_excepthook

from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
from PyQt6.QtWidgets import QApplication

from .config import load_config
from .main_window import MainWindow


def _qt_message_handler(mode, context, message):
    mode_name = {
        QtMsgType.QtDebugMsg: "DEBUG",
        QtMsgType.QtInfoMsg: "INFO",
        QtMsgType.QtWarningMsg: "WARNING",
        QtMsgType.QtCriticalMsg: "CRITICAL",
        QtMsgType.QtFatalMsg: "FATAL",
    }.get(mode, "?")
    where = ""
    if context is not None and context.file:
        where = f" ({context.file}:{context.line})"
    print(f"[Qt {mode_name}]{where} {message}", file=sys.stderr)
    sys.stderr.flush()


def setup_logging(cfg: dict):
    log_cfg = cfg.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    fmt = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

    handlers = [logging.StreamHandler(sys.stdout)]
    log_file = log_cfg.get("file")
    if log_file:
        log_path = Path(log_file)
        if not log_path.is_absolute():
            log_path = Path(__file__).resolve().parent.parent / log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_path,
                maxBytes=int(log_cfg.get("max_bytes", 5_000_000)),
                backupCount=int(log_cfg.get("backup_count", 3)),
            )
        )

    logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)

    # Quiet down noisy third-party libraries
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("peewee").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main():
    parser = argparse.ArgumentParser(description="Markets wall display")
    default_cfg = Path(__file__).resolve().parent.parent / "config" / "config.yaml"
    parser.add_argument("--config", default=str(default_cfg), help="Path to YAML config")
    parser.add_argument(
        "--windowed", action="store_true", help="Force windowed mode (dev)"
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.windowed:
        cfg.setdefault("display", {})["fullscreen"] = False
        cfg["display"]["hide_cursor"] = False

    setup_logging(cfg)
    log = logging.getLogger("markets_display")
    log.info("Starting Market Display. Config: %s", args.config)

    app = QApplication(sys.argv)
    qInstallMessageHandler(_qt_message_handler)

    win = MainWindow(cfg)
    rc = app.exec()
    log.info("Exiting (rc=%s)", rc)
    sys.exit(rc)


if __name__ == "__main__":
    main()
