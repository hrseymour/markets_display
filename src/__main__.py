"""Application entry point.

Usage:
    python -m markets_display              # uses config/config.yaml
    python -m markets_display --config path/to/other.yaml
    python -m markets_display --windowed   # disables fullscreen for dev
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from .config import load_config
from .main_window import MainWindow


#  Install a Python excepthook to force errors to print
import traceback

def _excepthook(exc_type, exc_value, exc_tb):
    print("=" * 60, file=sys.stderr)
    print("UNCAUGHT EXCEPTION:", file=sys.stderr)
    traceback.print_exception(exc_type, exc_value, exc_tb, file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _excepthook


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

    logging.basicConfig(level=level, format=fmt, handlers=handlers)


def main():
    parser = argparse.ArgumentParser(description="Market wall display")
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

    # Force Qt to surface exceptions from slot handlers
    def _qt_message_handler(mode, context, message):
        print(f"[Qt {mode}] {message}", file=sys.stderr)

    from PyQt6.QtCore import qInstallMessageHandler
    qInstallMessageHandler(_qt_message_handler)

    win = MainWindow(cfg)
    rc = app.exec()
    log.info("Exiting (rc=%s)", rc)
    sys.exit(rc)


if __name__ == "__main__":
    main()
