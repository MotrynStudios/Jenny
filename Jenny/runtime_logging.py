"""Mirror Python stdout and stderr to a bounded runtime log file."""
from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO


class _TeeStream:
    """Forward terminal output unchanged while writing complete lines to a logger."""

    def __init__(self, console: TextIO, logger: logging.Logger, level: int) -> None:
        self.console = console
        self.logger = logger
        self.level = level
        self.pending = ""
        self.lock = threading.RLock()
        self.encoding = getattr(console, "encoding", "utf-8")

    def write(self, value: str) -> int:
        text = str(value)
        with self.lock:
            written = self.console.write(text)
            self.pending += text
            while "\n" in self.pending:
                line, self.pending = self.pending.split("\n", 1)
                self.logger.log(self.level, line.rstrip("\r"))
            return len(text) if written is None else written

    def flush(self) -> None:
        with self.lock:
            self.console.flush()
            if self.pending:
                self.logger.log(self.level, self.pending.rstrip("\r"))
                self.pending = ""

    def isatty(self) -> bool:
        return bool(getattr(self.console, "isatty", lambda: False)())

    def fileno(self) -> int:
        return self.console.fileno()

    def __getattr__(self, name: str):
        return getattr(self.console, name)


def configure_runtime_logging() -> None:
    """Capture Python stdout/stderr in logs/python-runtime.log with rotation."""
    if getattr(sys, "_jenny_runtime_logging_enabled", False):
        return
    project_root = Path(__file__).resolve().parents[1]
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("jenny.runtime")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = RotatingFileHandler(
        log_dir / "python-runtime.log", maxBytes=8_000_000, backupCount=4, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    sys.stdout = _TeeStream(sys.__stdout__, logger, logging.INFO)  # type: ignore[assignment]
    sys.stderr = _TeeStream(sys.__stderr__, logger, logging.ERROR)  # type: ignore[assignment]
    sys._jenny_runtime_logging_enabled = True

