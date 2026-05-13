"""YAML config loader with .env support."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv


def load_config(path: str | os.PathLike) -> dict:
    """Load YAML config and merge .env into os.environ.

    .env is loaded from the project root (parent of `config/`).
    """
    path = Path(path).resolve()
    # Load .env from project root (one level above config/)
    project_root = path.parent.parent
    env_file = project_root / ".env"
    if env_file.exists():
        load_dotenv(env_file)

    with path.open("r") as fh:
        cfg = yaml.safe_load(fh)
    if not isinstance(cfg, dict):
        raise ValueError(f"Config at {path} is not a YAML mapping")
    return cfg
