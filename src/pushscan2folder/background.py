"""Run in the background: start, stop and status of a detached instance.

One background instance per user. It holds an exclusive lock on a file in the
state dir (the lock is what proves it is alive: the operating system drops it
when the process ends, however it ends, so a stale file never blocks a start
and a recycled PID is never mistaken for the program). Next to it the
instance writes a small info file (PID, log file). A detached Windows process
gets no Ctrl+C, so `stop` creates a stop-request file that the poll loop
checks; only if the instance does not react in time is it terminated."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import autostart
from .platform_support import default_state_dir, is_windows

LOCK_NAME = "pushscan2folder.lock"
INFO_NAME = "pushscan2folder.pid"
STOP_NAME = "pushscan2folder.stop"

# Windows process creation flags (spelled out: the subprocess constants exist on Windows only).
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
WINDOWS_FLAGS = CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

STOP_TIMEOUT = 30.0   # seconds to wait for a clean stop (a running scan finishes first)
START_TIMEOUT = 10.0  # seconds to wait until the new instance holds its lock

ALREADY_RUNNING = "already running"
NOT_RUNNING, STOPPED, TERMINATED, FAILED = "not running", "stopped", "terminated", "failed"


def _try_lock(fd: int) -> bool:
    """Take the exclusive lock on byte 0 without waiting."""
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fd: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


@dataclass
class Info:
    pid: int | None = None
    log: str | None = None


class Instance:
    """The background instance of this user (state in `directory`)."""

    def __init__(self, directory: Path | None = None):
        self.dir = Path(directory) if directory is not None else default_state_dir()
        self.lock_path = self.dir / LOCK_NAME
        self.info_path = self.dir / INFO_NAME
        self.stop_path = self.dir / STOP_NAME
        self._fd: int | None = None

    def is_running(self) -> bool:
        if self._fd is not None:
            return True
        if not self.lock_path.exists():
            return False
        try:
            fd = os.open(self.lock_path, os.O_RDWR)
        except OSError:
            return False
        try:
            if _try_lock(fd):
                _unlock(fd)
                return False
            return True
        finally:
            os.close(fd)

    def claim(self, log_file: str | None = None) -> bool:
        """Become the instance. False if another one holds the lock. Clears an
        old stop request. Raises OSError if the state dir is not writable."""
        self.dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        if not _try_lock(fd):
            os.close(fd)
            return False
        self._fd = fd
        self._remove(self.stop_path)
        self.info_path.write_text(json.dumps({"pid": os.getpid(), "log": log_file}),
                                  encoding="utf-8")
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        self._remove(self.info_path)
        self._remove(self.stop_path)
        _unlock(self._fd)
        os.close(self._fd)
        self._fd = None

    def stop_requested(self) -> bool:
        return self.stop_path.exists()

    def request_stop(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.stop_path.write_text("stop\n", encoding="utf-8")

    def read_info(self) -> Info:
        try:
            data = json.loads(self.info_path.read_text(encoding="utf-8"))
            pid = data.get("pid")
            log = data.get("log")
            return Info(pid if isinstance(pid, int) else None, log if isinstance(log, str) else None)
        except (OSError, ValueError, AttributeError):
            return Info()

    def clean_stale(self) -> None:
        """Remove the files of an instance that is gone."""
        for path in (self.info_path, self.stop_path):
            self._remove(path)

    @staticmethod
    def _remove(path: Path) -> None:
        try:
            path.unlink()
        except OSError:
            pass


def terminate(pid: int) -> None:
    """Last resort: end the process without a clean shutdown."""
    if is_windows():
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, check=False)
    else:
        os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))   # no SIGKILL on Windows


def stop_instance(inst: Instance, timeout: float = STOP_TIMEOUT, poll: float = 0.5,
                  sleep: Callable[[float], None] = time.sleep,
                  clock: Callable[[], float] = time.monotonic,
                  kill: Callable[[int], None] = terminate) -> str:
    """Stop the background instance cleanly (it releases its panel entries),
    terminate it if it does not react within `timeout` seconds. Returns
    NOT_RUNNING, STOPPED, TERMINATED or FAILED."""
    if not inst.is_running():
        inst.clean_stale()
        return NOT_RUNNING
    inst.request_stop()
    deadline = clock() + timeout
    while inst.is_running() and clock() < deadline:
        sleep(poll)
    if not inst.is_running():
        inst.clean_stale()
        return STOPPED
    pid = inst.read_info().pid
    if pid is not None:
        try:
            kill(pid)
        except OSError:
            pass
        for _ in range(10):
            if not inst.is_running():
                break
            sleep(poll)
    if inst.is_running():
        return FAILED
    inst.clean_stale()
    return TERMINATED


def launch(command: list[str], popen=subprocess.Popen):
    """Start `command` detached from this console and session, no output
    streams, no window. Returns the Popen object."""
    kwargs: dict = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, close_fds=True)
    if is_windows():
        kwargs["creationflags"] = WINDOWS_FLAGS
    else:
        kwargs["start_new_session"] = True
    if getattr(sys, "frozen", False):
        # A one-file exe starting itself: the child must not share (and lose)
        # the extraction folder of this short-lived parent.
        kwargs["env"] = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    return popen(command, **kwargs)


def start_instance(argv: list[str], inst: Instance, popen=subprocess.Popen,
                   sleep: Callable[[float], None] = time.sleep,
                   clock: Callable[[], float] = time.monotonic,
                   timeout: float = START_TIMEOUT) -> tuple[bool, str]:
    """Launch `argv` (the options and subcommand `run`, with --background)
    and wait until the new instance holds its lock. Returns (ok, message)."""
    if inst.is_running():
        pid = inst.read_info().pid
        return False, ALREADY_RUNNING + (f" (PID {pid})" if pid else "")
    try:
        proc = launch(autostart.program_command() + argv, popen)
    except OSError as exc:
        return False, f"cannot start: {exc.strerror or exc}"
    deadline = clock() + timeout
    while clock() < deadline:
        if inst.is_running():
            pid = inst.read_info().pid
            return True, "started" + (f" (PID {pid})" if pid else "")
        code = proc.poll()
        if code is not None:
            return False, f"the background process ended right away (exit code {code})"
        sleep(0.25)
    return False, "the background process did not report in time"


def log_tail(path: Path | str | None, lines: int = 10) -> list[str]:
    """Last lines of a text file ([] if it cannot be read)."""
    if not path:
        return []
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 32768))
            data = fh.read()
    except OSError:
        return []
    text = data.decode("utf-8", errors="replace").splitlines()
    return list(deque(text, maxlen=lines))
