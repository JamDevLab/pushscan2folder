"""Thread-safe runtime state for status displays (e.g. the web page).

The poll loop runs in the main thread; a web server reads this state from its
own threads. Everything shared goes through one lock, and readers only get
copies.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field

HISTORY = 50
LOG_LINES = 1000


@dataclass(frozen=True)
class ScanRecord:
    time: float
    target: str
    method: str            # "native" | "eSCL" | "" (failed before choosing)
    pages: int
    files: tuple[str, ...]
    result: str            # "ok" | "nothing saved" | "error"
    detail: str = ""


@dataclass(frozen=True)
class TargetState:
    name: str
    outdir: str
    registered: bool
    preset: dict = field(default_factory=dict)
    multipage: tuple[str, ...] | None = None
    type_dirs: tuple[tuple[str, str], ...] = ()   # (document type, folder) pairs


class ServiceStatus:
    def __init__(self):
        self._lock = threading.Lock()
        self._history: deque[ScanRecord] = deque(maxlen=HISTORY)
        self._targets: tuple[TargetState, ...] = ()
        self._last_ok: float | None = None
        self._last_error: tuple[float, str] | None = None
        self._busy: str | None = None
        self._pending = False

    def poll_ok(self) -> None:
        with self._lock:
            self._last_ok = time.time()
            self._last_error = None

    def poll_failed(self, message: str) -> None:
        with self._lock:
            self._last_error = (time.time(), message)

    def set_targets(self, targets) -> None:
        states = tuple(TargetState(t.name, str(t.outdir), t.session is not None, dict(t.preset),
                                   tuple(sorted(t.multipage)) if t.multipage is not None else None,
                                   tuple((kind, str(path)) for kind, path in t.type_dirs.items()))
                       for t in targets)
        with self._lock:
            self._targets = states

    def set_busy(self, target: str | None) -> None:
        with self._lock:
            self._busy = target

    def set_pending(self, pending: bool) -> None:
        with self._lock:
            self._pending = pending

    def record(self, record: ScanRecord) -> None:
        with self._lock:
            self._history.appendleft(record)

    def snapshot(self) -> dict:
        """Copy of the current state, newest scan first."""
        with self._lock:
            return {
                "targets": self._targets,
                "history": tuple(self._history),
                "last_ok": self._last_ok,
                "last_error": self._last_error,
                "busy": self._busy,
                "pending": self._pending,
            }


class LogBuffer(logging.Handler):
    """Keeps the last formatted log lines (INFO and above by default)."""

    def __init__(self, maxlen: int = LOG_LINES, level: int = logging.INFO):
        super().__init__(level)
        self._lines: deque[str] = deque(maxlen=maxlen)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:  # never let logging break the service
            return
        self.acquire()
        try:
            self._lines.append(line)
        finally:
            self.release()

    def lines(self) -> list[str]:
        self.acquire()
        try:
            return list(self._lines)
        finally:
            self.release()
