"""Show a finished scan on the desktop (option open_after_scan).

Best effort: a missing desktop or a failing helper program only produces a
warning, a scan never fails because of it."""
from __future__ import annotations

import base64
import logging
import os
import subprocess
from pathlib import Path

from .platform_support import is_macos, is_windows

log = logging.getLogger(__name__)

# Words accepted for open_after_scan in the environment and on the command
# line. "folder" and "file" are the old values (both mean "yes" now).
OPEN_TRUE = ("true", "yes", "1", "on", "folder", "file")
OPEN_FALSE = ("false", "no", "0", "off")


def parse_open(value) -> bool | None:
    """open_after_scan from a bool or a word (any case); None if not valid."""
    if isinstance(value, bool):
        return value
    word = str(value).strip().lower()
    if word in OPEN_TRUE:
        return True
    if word in OPEN_FALSE:
        return False
    return None

# Windows: if an Explorer window already shows the folder,
# select the new file there instead of opening one more window. Explorer's
# own "/select" always opens a new window, so this goes through the Shell
# COM object (PowerShell, no extra dependency). The path comes in through
# the environment, so it needs no quoting. Any failure falls back to
# "explorer /select" (a new window), as before.
SELECT_SCRIPT = r"""
$file = $env:PUSHSCAN_SELECT
try {
  $dir = Split-Path -LiteralPath $file
  $name = Split-Path -LiteralPath $file -Leaf
  $win = $null
  foreach ($w in (New-Object -ComObject Shell.Application).Windows()) {
    try { if ($w.Document.Folder.Self.Path -eq $dir) { $win = $w; break } } catch {}
  }
  if ($win -ne $null) {
    for ($i = 0; $i -lt 15; $i++) {
      $item = $win.Document.Folder.ParseName($name)
      if ($item -ne $null) { $win.Document.SelectItem($item, 29); exit 0 }
      Start-Sleep -Milliseconds 200
    }
    exit 0
  }
} catch {}
Start-Process explorer.exe -ArgumentList "/select,`"$file`""
"""
CREATE_NO_WINDOW = 0x08000000


def explorer_select(path: Path, popen=subprocess.Popen) -> None:
    """Show `path` selected in Explorer, reusing a window of its folder."""
    encoded = base64.b64encode(SELECT_SCRIPT.encode("utf-16-le")).decode("ascii")
    try:
        popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
               "-EncodedCommand", encoded],
              env=dict(os.environ, PUSHSCAN_SELECT=str(path)),
              creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:   # no PowerShell: a new window, as before
        # Explorer wants /select,"path" as is; a list would quote the
        # whole argument when the path has spaces. Windows file names
        # cannot contain quotes, so this string is safe.
        popen(f'explorer.exe /select,"{path}"')


DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def windows_has_program(suffix: str) -> bool:
    """True when Windows has a program for files ending in `suffix`."""
    import ctypes
    from ctypes import wintypes
    size = wintypes.DWORD(0)
    # ASSOCF_INIT_IGNOREUNKNOWN (0x400), ASSOCSTR_EXECUTABLE (2); with no
    # buffer the call only reports the length: S_FALSE (1) when found.
    result = ctypes.windll.shlwapi.AssocQueryStringW(
        0x400, 2, suffix, None, None, ctypes.byref(size))
    return result >= 0


def _start_detached(command: list[str], popen) -> None:
    """Start a program that keeps running when this console closes."""
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, close_fds=True)
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:   # also leave the job of the terminal, if it allows that
        popen(command, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, **kwargs)
    except OSError:
        popen(command, creationflags=flags, **kwargs)


def open_path(path: Path, popen=subprocess.Popen, has_program=None) -> None:
    """Open a file with the program the system has for it, independent of
    this console. Windows: through Explorer (the program then belongs to
    Explorer, not to this terminal), else Notepad; macOS "open"; elsewhere
    "xdg-open". Raises OSError."""
    if is_windows():
        try:
            found = (has_program or windows_has_program)(path.suffix)
        except (OSError, AttributeError):
            found = False
        _start_detached(["explorer.exe" if found else "notepad.exe", str(path)], popen)
        return
    popen(["open" if is_macos() else "xdg-open", str(path)], start_new_session=True,
          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def has_desktop(environ=None) -> bool:
    """Windows and macOS: assumed. Elsewhere a display server must be set."""
    if is_windows() or is_macos():
        return True
    env = os.environ if environ is None else environ
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


_told_no_desktop = False


def open_saved(open: bool, paths, popen=subprocess.Popen) -> bool:
    """Open the folder of a finished job (on Windows with the first file
    selected), once per job. True if a program was started."""
    if not open or not paths:
        return False
    first = Path(paths[0])
    try:
        if not has_desktop():
            global _told_no_desktop
            if not _told_no_desktop:   # once, not after every scan
                _told_no_desktop = True
                log.warning("open_after_scan: no desktop session (DISPLAY or "
                            "WAYLAND_DISPLAY not set, for example in Docker), "
                            "so no folder is opened after a scan")
            return False
        if is_windows():
            explorer_select(first, popen)
        else:
            opener = "open" if is_macos() else "xdg-open"
            popen([opener, str(first.parent)], stdin=subprocess.DEVNULL,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as exc:  # never fail the scan
        log.warning("open_after_scan: could not open %s: %s", first, exc)
        return False
