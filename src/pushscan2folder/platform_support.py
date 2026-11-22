"""Small platform helpers: default paths, safe file replacement, Windows names.

Everything here is plain stdlib. The name rules (valid_component and friends)
are the Windows rules and are applied on every platform, so a config written
on Linux also works when it is copied to Windows."""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path


def is_windows() -> bool:
    return sys.platform == "win32"


def is_macos() -> bool:
    return sys.platform == "darwin"


def default_config_path() -> Path:
    """Windows: %APPDATA%\\pushscan2folder\\config.toml. Everywhere else
    (Linux, macOS): $XDG_CONFIG_HOME or ~/.config, then pushscan2folder/config.toml."""
    if is_windows():
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "pushscan2folder" / "config.toml"


def default_output() -> Path:
    """Where scans go without any setting. ./scans on Linux (a container maps
    /scans through its config); Documents/Scans of the user on Windows and macOS."""
    if is_windows() or is_macos():
        return Path.home() / "Documents" / "Scans"
    return Path("./scans")


def replace_file(src, dst, attempts: int = 5, delay: float = 0.1) -> None:
    """os.replace that retries briefly on Windows. There the rename fails with
    PermissionError while another program (virus scanner, editor, indexer) has
    the target open for a moment. Elsewhere it is a plain os.replace."""
    for attempt in range(1, attempts + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if not is_windows() or attempt == attempts:
                raise
            time.sleep(delay)


# --- file and folder names -------------------------------------------------------

_RESERVED_STEMS = frozenset(
    ["con", "prn", "aux", "nul", "conin$", "conout$"]
    + [f"com{i}" for i in range(10)] + [f"lpt{i}" for i in range(10)])

# Characters Windows does not allow in a name (the path separators are handled
# by the callers, which split paths into components first).
_BAD_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


def is_reserved_name(component: str) -> bool:
    """True for a Windows device name (CON, PRN, AUX, NUL, COM0-9, LPT0-9),
    case-insensitive, with or without an extension: "con", "NUL.txt",
    "com1.tar.gz" and "aux ." all are. The extension and trailing spaces
    before it do not matter to Windows."""
    stem = component.split(".", 1)[0].rstrip(" ")
    return stem.lower() in _RESERVED_STEMS


def component_problem(component: str) -> str | None:
    """Why `component` is not a valid file or folder name on Windows (and so
    not accepted anywhere), or None if it is fine."""
    if _BAD_NAME_CHARS.search(component):
        return 'a name must not contain any of < > : " / \\ | ? * or control characters'
    if component.endswith((".", " ")):
        return "a name must not end with a dot or a space"
    if is_reserved_name(component):
        return f"{component!r} is a reserved Windows device name"
    return None
