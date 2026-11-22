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

OPEN_MODES = ("off", "folder", "file")

# Windows, mode "folder": if an Explorer window already shows the folder,
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


def open_path(path: Path, popen=subprocess.Popen, startfile=None) -> None:
    """Open a file with the program the system has for it. Windows: the file
    association, else Notepad; macOS "open"; elsewhere "xdg-open". Raises OSError."""
    if is_windows():
        startfile = startfile or getattr(os, "startfile", None)
        try:
            if startfile is None:
                raise OSError("no os.startfile")
            startfile(str(path))
        except OSError:   # no program for this file type
            popen(["notepad.exe", str(path)])
        return
    popen(["open" if is_macos() else "xdg-open", str(path)],
          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
                explorer_select(first, popen)
        else:
            opener = "open" if is_macos() else "xdg-open"
            target = first if mode == "file" else first.parent
            popen([opener, str(target)], stdin=subprocess.DEVNULL,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as exc:  # never fail the scan
        log.warning("open_after_scan: could not open %s: %s", first, exc)
        return False
