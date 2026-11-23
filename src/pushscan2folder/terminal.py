"""Clickable paths in the terminal (OSC 8 hyperlinks).

A hyperlink is the visible text wrapped in two escape sequences:
ESC ] 8 ; ; URI ESC \\  text  ESC ] 8 ; ; ESC \\. Terminals that know them
(Windows Terminal, most Linux terminals) show the plain text and open the
URI on Ctrl+click or click. The classic Windows console window does not
know them and would print the escape codes, so on Windows links are only
used inside Windows Terminal (it sets WT_SESSION). Never used when the
output is not a terminal, so log files and tests get the plain text."""
from __future__ import annotations

import os
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .platform_support import is_windows


def supports_links(stream=None, environ=None) -> bool:
    stream = sys.stdout if stream is None else stream
    env = os.environ if environ is None else environ
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError, OSError):
        return False
    if is_windows():
        return bool(env.get("WT_SESSION"))
    return env.get("TERM", "") not in ("", "dumb")


def file_uri(path, environ=None) -> str | None:
    """file:// URI of `path`. Inside WSL a Linux path is reached by Windows
    programs (Windows Terminal opens the link) as \\\\wsl.localhost\\<distro>."""
    env = os.environ if environ is None else environ
    try:
        absolute = Path(path).absolute()
        distro = env.get("WSL_DISTRO_NAME")
        if distro and not is_windows():
            parts = PurePosixPath(absolute.as_posix())
            return PurePosixPath("/", *parts.parts[1:]).as_uri().replace(
                "file:///", f"file://wsl.localhost/{quote(distro)}/", 1)
        return absolute.as_uri()
    except ValueError:
        return None


def link(path, stream=None, environ=None) -> str:
    """`path` as text, clickable where the terminal supports it."""
    text = str(path)
    if not supports_links(stream, environ):
        return text
    uri = file_uri(path, environ)
    if uri is None:
        return text
    return f"\033]8;;{uri}\033\\{text}\033]8;;\033\\"
