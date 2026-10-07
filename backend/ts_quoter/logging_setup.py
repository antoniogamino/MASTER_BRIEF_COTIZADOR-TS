"""Logs separados: app / ai / calc / error (sec. 80). Nunca registrar API keys."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import settings

CHANNELS = {"app": logging.INFO, "ai": logging.INFO, "calc": logging.INFO, "error": logging.ERROR}


def setup_logging() -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    for name, level in CHANNELS.items():
        lg = logging.getLogger(f"tsq.{name}")
        if lg.handlers:
            continue
        h = RotatingFileHandler(settings.log_dir / f"{name}.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        h.setFormatter(fmt)
        lg.addHandler(h)
        lg.setLevel(level)
