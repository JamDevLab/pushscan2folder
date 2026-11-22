"""Start pushscan2folder when the user logs in to Windows.

This uses the per-user Run key (HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run),
written with reg.exe. It needs no administrator rights. A Task Scheduler
logon trigger would need them on most systems. The program is started
minimised through `cmd /c start /min`, so it does not cover the desktop.

The functions here only build command lines (testable on any platform);
main() in __main__ runs them on Windows."""
from __future__ import annotations

import os
import sys

RUN_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "pushscan2folder"
# Options whose value is a path; made absolute because the autostart entry
# does not run in the current directory.
PATH_OPTIONS = ("--config", "--log-file", "--output")
COMMANDS = ("run", "probe", "scan")
# Marks a start from the logon entry. `cmd /c start` opens a console of its
# own, which must never wait for Enter when the program ends.
NO_PAUSE = "--no-pause"


def program_command() -> list[str]:
    """The command that starts this program: the exe itself when frozen
    (PyInstaller), else this Python with -m pushscan2folder."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "pushscan2folder"]


def absolute_args(args: list[str]) -> list[str]:
    """Copy of args with the values of PATH_OPTIONS made absolute."""
    result: list[str] = []
    expect_path = False
    for arg in args:
        if expect_path:
            arg, expect_path = os.path.abspath(arg), False
        elif arg in PATH_OPTIONS:
            expect_path = True
        else:
            for option in PATH_OPTIONS:
                if arg.startswith(option + "="):
                    arg = option + "=" + os.path.abspath(arg[len(option) + 1:])
        result.append(arg)
    return result


def _quote(token: str) -> str:
    if '"' in token or "%" in token or "\n" in token or "\r" in token:
        raise ValueError(f"cannot use {token!r} in an autostart entry "
                         '(no double quotes or percent signs)')
    return f'"{token}"'


def run_value(args: list[str]) -> str:
    """The value of the Run entry. Every token is quoted, so spaces and shell
    characters in paths are harmless; `start` gets an empty-looking title and /min."""
    tokens = program_command() + ([] if NO_PAUSE in args else [NO_PAUSE]) + absolute_args(args)
    if not any(a in COMMANDS for a in args):
        tokens.append("run")
    return 'cmd.exe /c start "pushscan2folder" /min ' + " ".join(_quote(t) for t in tokens)


def install_command(args: list[str]) -> list[str]:
    """Argument list for subprocess.run (never through a shell)."""
    return ["reg.exe", "add", RUN_KEY, "/v", VALUE_NAME, "/t", "REG_SZ",
            "/d", run_value(args), "/f"]


def remove_command() -> list[str]:
    return ["reg.exe", "delete", RUN_KEY, "/v", VALUE_NAME, "/f"]
