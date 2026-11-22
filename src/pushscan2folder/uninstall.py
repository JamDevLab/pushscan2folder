"""`pushscan2folder uninstall`: stop the background instance, remove the
autostart entry and, on request, the settings and state folders.

Scans are never deleted: a folder that contains a scan folder is kept."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from . import background

FOLDER_NAME = "pushscan2folder"  # only folders with this name are ever deleted


def contains(folder: Path, path: Path) -> bool:
    try:
        return Path(path).resolve().is_relative_to(Path(folder).resolve())
    except (OSError, ValueError):
        return True  # unsure: treat as inside, so the folder is kept


def uninstall(inst: background.Instance, config_dir: Path, state_dir: Path,
              protected: list[Path], *, yes: bool = False, purge: bool = False,
              remove_autostart: Callable[[], str] | None = None, exe: Path | None = None,
              out: Callable[[str], None] = print,
              input_fn: Callable[[str], str] = input,
              stop: Callable[[background.Instance], str] = background.stop_instance) -> int:
    """Returns the exit code. protected: scan folders that must survive.
    remove_autostart returns a message (None: no autostart on this platform)."""
    result = stop(inst)
    if result == background.FAILED:
        out("error: the background instance could not be stopped, nothing was removed")
        return 1
    out("Background instance: " + {background.NOT_RUNNING: "was not running",
                                   background.STOPPED: "stopped",
                                   background.TERMINATED: "terminated (did not stop in time)"}[result])
    if remove_autostart is not None:
        out(remove_autostart())

    folders: list[Path] = []
    for folder in (config_dir, state_dir):
        if folder in folders or not folder.is_dir():
            continue
        if folder.name != FOLDER_NAME:
            out(f"Keeping {folder}: it is not a {FOLDER_NAME} folder")
        elif any(contains(folder, p) for p in protected):
            out(f"Keeping {folder}: your scan folder is inside it")
        else:
            folders.append(folder)
    failed = False
    if folders:
        out("These folders hold the settings (and the web password file) and the log:")
        for folder in folders:
            out(f"  {folder}")
        if yes:
            delete = purge
            if not purge:
                out("Kept (use --purge to delete them without asking).")
        else:
            delete = input_fn("Delete them? Your scans are not touched. [y/N]: ").strip().lower() \
                in ("y", "yes", "j", "ja")
        if delete:
            for folder in folders:
                try:
                    shutil.rmtree(folder)
                    out(f"Deleted {folder}")
                except OSError as exc:
                    out(f"error: cannot delete {folder}: {exc.strerror or exc}")
                    failed = True
        elif not yes:
            out("Kept.")
    else:
        out("No settings or log folders to delete.")
    out("Your scans were not touched.")
    if exe is not None:
        out(f"Last step: delete the program folder itself, {exe.parent}. A running "
            "program cannot delete its own files.")
    else:
        out("The program itself is not removed by this command (remove it the way "
            "you installed it, e.g. pip uninstall pushscan2folder).")
    return 1 if failed else 0
