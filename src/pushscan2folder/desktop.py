"""Show a finished scan on the desktop (option open_after_scan).

Best effort: a missing desktop or a failing helper program only produces a
warning, a scan never fails because of it."""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from .platform_support import is_macos, is_windows

log = logging.getLogger(__name__)

OPEN_MODES = ("off", "folder", "file")


def has_desktop(environ=None) -> bool:
    """Windows and macOS: assumed. Elsewhere a display server must be set."""
    if is_windows() or is_macos():
        return True
    env = os.environ if environ is None else environ
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


def open_saved(mode: str, paths, popen=subprocess.Popen) -> bool:
    """Open the folder ("folder", on Windows with the first file selected) or
    the first file ("file") of a finished job, once per job. True if a
    program was started."""
    if mode == "off" or not paths:
        return False
    first = Path(paths[0])
    try:
        if not has_desktop():
            log.warning("open_after_scan: no desktop session (DISPLAY or "
                        "WAYLAND_DISPLAY not set), not opening %s", first)
            return False
        if is_windows():
            if mode == "file":
                os.startfile(first)  # type: ignore[attr-defined]
            else:
                # Explorer wants /select,"path" as is; a list would quote the
                # whole argument when the path has spaces. Windows file names
                # cannot contain quotes, so this string is safe.
                popen(f'explorer.exe /select,"{first}"')
        else:
            opener = "open" if is_macos() else "xdg-open"
            target = first if mode == "file" else first.parent
            popen([opener, str(target)], stdin=subprocess.DEVNULL,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as exc:  # never fail the scan
        log.warning("open_after_scan: could not open %s: %s", first, exc)
        return False
