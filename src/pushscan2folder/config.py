"""The TOML configuration file (see config.example.toml).

Layout (every key is optional):

    printer, folder, filename, next_page, feeder_next_page, auto = {...},
                open_after_scan
    [advanced]  interval, verbose, trim = {...}, adf_trim = {...}
    [web]       enabled, bind, port, password_file
    [[target]]  name, folder, document_folder, auto_folder, photo_folder,
                filename, next_page, feeder_next_page, auto = {...}, open_after_scan

The printer panel decides colour, source (the feeder when paper is in it)
and, for the document types "Document" and "Photo", size, format and
resolution. The file only sets what the panel does not: the folders, the
file names, which document types get the "next page" dialog (on the glass
and, if wanted, after the feeder), and the
settings for document type "Auto".
"""
from __future__ import annotations

import errno
import logging
import math
import os
import stat
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import panel
from .platform_support import replace_file
from .protocol import check_name
from .service import (DEFAULT_FEEDER_NEXT_PAGE, DEFAULT_NEXT_PAGE, DOC_TYPES, RESOLUTIONS, TRIM_MAX_MM, Target, Trim,
                      check_filename, check_folder, safe_dirname)


FORMATS = ("pdf", "jpeg")
SIZES = tuple(panel.REGIONS)
TRIM_SIDES = ("left", "top", "right", "bottom")
AUTO_KEYS = ("resolution", "format", "size")
# Built-in values of the keys that have one.
DEFAULT_AUTO = {"resolution": 300, "format": "pdf", "size": "a4"}
DEFAULT_INTERVAL = 4.0

log = logging.getLogger(__name__)


class ConfigError(ValueError):
    """The configuration file is unreadable or invalid."""


SAME_FOLDER = "."  # target folder: the base folder itself, no subfolder

# Keys per table. A target folder key per document type: "photo_folder" ...
TYPE_FOLDER_KEYS = {kind: f"{kind}_folder" for kind in DOC_TYPES}
TOP_KEYS = ("printer", "folder", "filename", "next_page", "feeder_next_page", "auto",
            "open_after_scan", "advanced", "web", "target")
ADVANCED_KEYS = ("interval", "verbose", "trim", "adf_trim")
WEB_KEYS = ("enabled", "bind", "port", "password_file")
TARGET_KEYS = (("name", "folder") + tuple(TYPE_FOLDER_KEYS.values())
               + ("filename", "next_page", "feeder_next_page", "auto", "open_after_scan"))


@dataclass
class TargetSpec:
    """A [[target]] table; turned into a Target once the base folder is known.

    folder and type_folders (document type -> folder) are relative to the
    base folder unless absolute; they may contain date fields. auto holds
    the set keys of the target's auto table (config names). None means
    "the global value"."""
    name: str
    folder: str | None = None
    type_folders: dict[str, str] = field(default_factory=dict)
    filename: str | None = None
    next_page: frozenset[str] | None = None
    feeder_next_page: frozenset[str] | None = None
    auto: dict = field(default_factory=dict)
    open_after_scan: bool | None = None

    def folders(self) -> list[str]:
        """Every folder this target writes to, as written (relative ones
        relative to the base folder)."""
        main = self.folder if self.folder else safe_dirname(self.name)
        return [main] + [self.type_folders[k] for k in DOC_TYPES if k in self.type_folders]


@dataclass
class Config:
    printer: str | None = None
    folder: Path | None = None
    filename: str | None = None
    next_page: frozenset[str] | None = None
    feeder_next_page: frozenset[str] | None = None
    auto: dict = field(default_factory=dict)
    open_after_scan: bool | None = None
    interval: float | None = None
    verbose: bool | None = None
    trim: Trim | None = None
    adf_trim: Trim | None = None
    web_enabled: bool | None = None
    web_bind: str | None = None
    web_port: int | None = None
    web_password_file: str | None = None
    targets: list[TargetSpec] = field(default_factory=list)

    def auto_values(self) -> dict:
        """The global auto settings with the built-in values filled in."""
        return {**DEFAULT_AUTO, **self.auto}

    def next_page_types(self) -> frozenset[str]:
        return DEFAULT_NEXT_PAGE if self.next_page is None else self.next_page

    def feeder_next_page_types(self) -> frozenset[str]:
        return (DEFAULT_FEEDER_NEXT_PAGE if self.feeder_next_page is None
                else self.feeder_next_page)

    def build_targets(self, base: Path) -> list[Target]:
        """Targets for base folder `base`. Relative folders resolve against
        it; an unset next_page or feeder_next_page keeps the global one (None)."""
        result = []
        for spec in self.targets:
            outdir = base / (spec.folder if spec.folder else safe_dirname(spec.name))
            type_dirs = {kind: base / path for kind, path in spec.type_folders.items()}
            result.append(Target(spec.name, outdir, preset=auto_preset(spec.auto),
                                 multipage=spec.next_page,
                                 feeder_multipage=spec.feeder_next_page,
                                 filename=spec.filename,
                                 open_after_scan=spec.open_after_scan, type_dirs=type_dirs))
        return result


def auto_preset(auto: dict) -> dict:
    """ScanSettings fields for an auto table (resolution, format, size)."""
    preset: dict = {}
    if "resolution" in auto:
        preset["resolution"] = auto["resolution"]
    if "format" in auto:
        preset["fmt"] = auto["format"]
    if "size" in auto:
        preset["width"], preset["height"] = panel.REGIONS[auto["size"]]
    return preset


def _choice(values) -> str:
    return ", ".join(str(v) for v in values)


class _Reader:
    """Typed access to one TOML table that rejects unknown keys."""

    def __init__(self, table: dict, where: str, allowed):
        self.table, self.where = table, where
        for key in table:
            if key not in allowed:
                raise ConfigError(f'{where}: unknown key "{key}" (known keys: '
                                  f"{_choice(allowed)})")

    def _bad(self, key: str, expected: str) -> ConfigError:
        return ConfigError(f'{self.where}: "{key}" must be {expected}, '
                           f"got {self.table[key]!r}")

    def str_(self, key: str, choices=None) -> str | None:
        if key not in self.table:
            return None
        value = self.table[key]
        if not isinstance(value, str) or not value.strip():
            raise self._bad(key, "a non-empty text in quotes")
        if choices is not None and value not in choices:
            raise self._bad(key, f"one of: {_choice(choices)}")
        return value

    def bool_(self, key: str) -> bool | None:
        if key not in self.table:
            return None
        if not isinstance(self.table[key], bool):
            raise self._bad(key, "true or false")
        return self.table[key]

    def int_(self, key: str, choices) -> int | None:
        if key not in self.table:
            return None
        value = self.table[key]
        if isinstance(value, bool) or value not in choices:
            raise self._bad(key, f"one of: {_choice(choices)}")
        return value

    def number(self, key: str) -> float | None:
        if key not in self.table:
            return None
        value = self.table[key]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise self._bad(key, "a number greater than 0")
        return float(value)

    def port(self, key: str) -> int | None:
        if key not in self.table:
            return None
        value = self.table[key]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
            raise self._bad(key, "a port number from 1 to 65535")
        return value

    def filename(self, key: str) -> str | None:
        value = self.str_(key)
        if value is not None:
            try:
                check_filename(value)
            except ValueError as exc:
                raise self._bad(key, f"a file name template ({exc})") from None
        return value

    def folder(self, key: str) -> str | None:
        value = self.str_(key)
        if value is not None:
            try:
                check_folder(value)
            except ValueError as exc:
                raise self._bad(key, f"a folder ({exc})") from None
        return value

    def table_(self, key: str) -> dict | None:
        if key not in self.table:
            return None
        if not isinstance(self.table[key], dict):
            raise self._bad(key, "a table, e.g. { ... }")
        return self.table[key]

    def next_page(self, key: str) -> frozenset[str] | None:
        if key not in self.table:
            return None
        value = self.table[key]
        if (not isinstance(value, list) or not all(isinstance(v, str) for v in value)
                or not set(value) <= set(DOC_TYPES)):
            raise self._bad(key, f"a list of document types out of {_choice(DOC_TYPES)}, "
                                 'e.g. ["document"] or [] for none')
        return frozenset(value)

    def auto(self, key: str) -> dict:
        table = self.table_(key)
        if table is None:
            return {}
        rd = _Reader(table, f"{self.where}: {key}", AUTO_KEYS)
        values = {"resolution": rd.int_("resolution", RESOLUTIONS),
                  "format": rd.str_("format", FORMATS),
                  "size": rd.str_("size", SIZES)}
        return {k: v for k, v in values.items() if v is not None}

    def trim(self, key: str) -> Trim | None:
        table = self.table_(key)
        if table is None:
            return None
        rd = _Reader(table, f"{self.where}: {key}", TRIM_SIDES)
        values = {}
        for side in TRIM_SIDES:
            if side not in table:
                continue
            value = table[side]
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not 0 <= value <= TRIM_MAX_MM):
                raise rd._bad(side, f"a number of mm from 0 to {TRIM_MAX_MM:g}")
            values[side] = float(value)
        trim = Trim(**values)
        return trim if trim else None   # { } or all 0: no trim


def _target(table, index: int, fname: str) -> TargetSpec:
    if not isinstance(table, dict):
        raise ConfigError(f"{fname}: [[target]] #{index} must be a table")
    label = f"{fname}: target #{index}"
    name = table.get("name")
    if isinstance(name, str) and name.strip():
        label = f'{fname}: target "{name.strip()}"'
    rd = _Reader(table, label, TARGET_KEYS)
    if "name" not in table:
        raise ConfigError(f'{label}: missing required key "name"')
    name = rd.str_("name").strip()
    try:
        check_name(name)
    except ValueError as exc:
        raise ConfigError(f"{label}: {exc}") from exc
    type_folders = {}
    for kind, key in TYPE_FOLDER_KEYS.items():
        value = rd.folder(key)
        if value is not None:
            type_folders[kind] = value
    return TargetSpec(name, folder=rd.folder("folder"), type_folders=type_folders,
                      filename=rd.filename("filename"), next_page=rd.next_page("next_page"),
                      feeder_next_page=rd.next_page("feeder_next_page"),
                      auto=rd.auto("auto"), open_after_scan=rd.bool_("open_after_scan"))


def load_config(path: Path) -> Config:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"{path.name}: cannot read file: {exc.strerror or exc}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{path.name}: not UTF-8 text: {exc}") from exc
    return load_config_text(text, path.name)


def load_config_text(text: str, fname: str = "config.toml") -> Config:
    """Parse and validate config text (the same rules as load_config).
    `fname` only appears in error messages. Raises ConfigError."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        hint = ""
        for line in text.splitlines():
            code = line.split("#", 1)[0]
            if "{" in code and "}" not in code:
                hint = " (a { ... } table such as auto or trim must stay on one line)"
                break
        raise ConfigError(f"{fname}: invalid TOML: {exc}{hint}") from exc
    return parse_config(data, fname)


def parse_config(data: dict, fname: str = "config.toml") -> Config:
    """Validate an already parsed TOML table. Raises ConfigError."""
    top = _Reader(data, fname, TOP_KEYS)
    folder = top.str_("folder")
    cfg = Config(printer=top.str_("printer"),
                 folder=Path(folder) if folder is not None else None,
                 filename=top.filename("filename"), next_page=top.next_page("next_page"),
                 feeder_next_page=top.next_page("feeder_next_page"),
                 auto=top.auto("auto"), open_after_scan=top.bool_("open_after_scan"))

    adv = _Reader(top.table_("advanced") or {}, f"{fname}: [advanced]", ADVANCED_KEYS)
    cfg.interval = adv.number("interval")
    cfg.verbose = adv.bool_("verbose")
    cfg.trim = adv.trim("trim")
    cfg.adf_trim = adv.trim("adf_trim")

    web = _Reader(top.table_("web") or {}, f"{fname}: [web]", WEB_KEYS)
    cfg.web_enabled = web.bool_("enabled")
    cfg.web_bind = web.str_("bind")
    cfg.web_port = web.port("port")
    cfg.web_password_file = web.str_("password_file")

    raw_targets = data.get("target", [])
    if not isinstance(raw_targets, list):
        raise ConfigError(f'{fname}: "target" must be written as [[target]] blocks')
    seen: set[str] = set()
    for i, table in enumerate(raw_targets, 1):
        spec = _target(table, i, fname)
        if spec.name in seen:
            raise ConfigError(f'{fname}: two targets are called "{spec.name}"')
        seen.add(spec.name)
        cfg.targets.append(spec)
    return cfg


# --- writing -----------------------------------------------------------------

def size_name(preset: dict) -> str | None:
    """Name of the paper size matching preset width/height, if any."""
    pair = (preset.get("width"), preset.get("height"))
    for name, region in panel.REGIONS.items():
        if region == pair:
            return name
    return None


_ESCAPES = {"\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def _quote(value: str) -> str:
    """TOML basic string: escape quotes, backslashes and control characters."""
    out = []
    for ch in value:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, frozenset):
        return "[" + ", ".join(_quote(k) for k in DOC_TYPES if k in value) + "]"
    if isinstance(value, Trim):
        return "{ " + ", ".join(f"{side} = {_value(getattr(value, side))}"
                                for side in TRIM_SIDES if getattr(value, side)) + " }"
    if isinstance(value, dict):   # an auto table, one line (TOML 1.0)
        return "{ " + ", ".join(f"{k} = {_value(value[k])}" for k in AUTO_KEYS
                                if k in value) + " }"
    return _quote(str(value))


def _line(key: str, value, comment: str = "") -> list[str]:
    if value is None or (isinstance(value, (dict, Trim)) and not value):
        return []
    line = f"{key} = {_value(value)}"
    return [f"{line:<40} # {comment}" if comment else line]


HEADER = """\
# pushscan2folder configuration.
# Changes are used while the program runs, within a few seconds. Only [web]
# and verbose in [advanced] need a restart.
# The printer panel decides colour, source (the feeder when paper is in it)
# and, for "Document" and "Photo", size, format and resolution.
# All keys: https://github.com/JamDevLab/pushscan2folder/blob/main/docs/configuration.md"""

_EXAMPLE_TARGET = """\
# Another entry on the printer panel, with its own folder:
# [[target]]
# name = "Archive"
# folder = "Archive/{now:%Y}"             # date fields are allowed
# photo_folder = "Photos"                 # photos of this entry go elsewhere
# next_page = []                          # no "next page" dialog
# auto = { resolution = 600, format = "jpeg" }"""


def dump_config(cfg: Config) -> str:
    """Render a Config as TOML (the schema load_config reads), with a header
    and comments. Comments of an existing file are not kept."""
    blocks: list[list[str]] = [[HEADER]]
    top = (_line("printer", cfg.printer, "printer IP address or host name")
           + _line("folder", str(cfg.folder) if cfg.folder is not None else None,
                   "base folder of all targets"))
    general = (_line("filename", cfg.filename, "fields {name} {date} {time} {now:%Y-%m-%d}")
               + _line("next_page", cfg.next_page, "document types with the next page dialog")
               + _line("feeder_next_page", cfg.feeder_next_page,
                       "the same after a feeder scan")
               + _line("auto", cfg.auto, 'panel type "Auto": resolution, format, size')
               + _line("open_after_scan", cfg.open_after_scan, "desktop PC only"))
    if not general:
        general = ['# filename = "scan_{now:%Y-%m-%d_%H-%M-%S}"',
                   '# next_page = ["document"]          # "document", "auto", "photo"',
                   '# auto = { resolution = 300, format = "pdf", size = "a4" }']
    blocks.append(top + ([""] if top else []) + ["# Defaults for all targets"] + general)
    advanced = (_line("interval", cfg.interval, "seconds between polls")
                + _line("verbose", cfg.verbose, "debug log, needs a restart")
                + _line("trim", cfg.trim, "glass, mm cut off per side")
                + _line("adf_trim", cfg.adf_trim, "feeder, mm cut off per side"))
    if advanced:
        blocks.append(["[advanced]"] + advanced)
    web = (_line("enabled", cfg.web_enabled) + _line("bind", cfg.web_bind)
           + _line("port", cfg.web_port) + _line("password_file", cfg.web_password_file))
    if web:
        blocks.append(["[web]"] + web)
    for spec in cfg.targets:
        block = ["[[target]]"] + _line("name", spec.name) + _line("folder", spec.folder)
        for kind in DOC_TYPES:
            block += _line(TYPE_FOLDER_KEYS[kind], spec.type_folders.get(kind))
        block += (_line("filename", spec.filename) + _line("next_page", spec.next_page)
                  + _line("feeder_next_page", spec.feeder_next_page)
                  + _line("auto", spec.auto) + _line("open_after_scan", spec.open_after_scan))
        blocks.append(block)
    blocks.append([_EXAMPLE_TARGET])
    return "\n\n".join("\n".join(b) for b in blocks) + "\n"


# Errors that mean "cannot replace this file by renaming" (e.g. a Docker
# single-file bind mount, or a directory we may not write to).
_INPLACE_ERRNOS = (errno.EBUSY, errno.EXDEV, errno.EPERM, errno.EACCES)


def _write_in_place(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())


def write_config(path: Path, text: str) -> None:
    """Write `text` to `path`: atomically (temp file + os.replace) when
    possible, otherwise in place. Creates the parent directory. Keeps the
    permissions of an existing file; a new file is private (0600), as the
    web page may create it. On Windows chmod only toggles the read-only flag,
    so the file is protected by the user's profile folder instead. Raises OSError."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    mode = stat.S_IMODE(path.stat().st_mode) if existed else 0o600
    tmp = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".tmp")
        tmp = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        replace_file(tmp, path)
        tmp = None
    except OSError as exc:
        if not existed or exc.errno not in _INPLACE_ERRNOS:
            raise
        _write_in_place(path, text)
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
