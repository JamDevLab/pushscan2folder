"""Optional TOML configuration file (see config.example.toml)."""
from __future__ import annotations

import errno
import math
import os
import stat
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import panel
from .desktop import OPEN_MODES
from .platform_support import replace_file
from .protocol import check_name
from .service import (MULTIPAGE_MODES, RESOLUTIONS, TRIM_MAX_MM, Target, Trim,
                      safe_dirname)


COLORS = ("color", "gray")
FORMATS = ("pdf", "jpeg")
SOURCES = ("auto", "platen", "adf")


class ConfigError(ValueError):
    """The configuration file is unreadable or invalid."""


@dataclass
class TargetSpec:
    """A [[target]] table; turned into a Target once the output dir is known."""
    name: str
    output: str | None = None
    preset: dict = field(default_factory=dict)
    document_multipage: bool | None = None
    auto_multipage: bool | None = None


@dataclass
class Config:
    printer: str | None = None
    output: Path | None = None
    interval: float | None = None
    verbose: bool | None = None
    ignore_panel: bool | None = None
    multipage: str | None = None
    resolution: int | None = None
    color: str | None = None
    format: str | None = None
    source: str | None = None
    open_after_scan: str | None = None
    size: str | None = None
    trim_left: float | None = None
    trim_top: float | None = None
    trim_right: float | None = None
    trim_bottom: float | None = None
    web_enabled: bool | None = None
    web_bind: str | None = None
    web_port: int | None = None
    web_password_file: str | None = None
    targets: list[TargetSpec] = field(default_factory=list)

    def trim(self) -> Trim:
        """The [defaults] trim_* values (unset sides are 0)."""
        return Trim(self.trim_left or 0.0, self.trim_top or 0.0,
                    self.trim_right or 0.0, self.trim_bottom or 0.0)

    def build_targets(self, base: Path, global_mode: str) -> list[Target]:
        """Targets for output dir `base`. Relative target outputs resolve
        against it; an unset multipage keeps the global mode (None)."""
        result = []
        for spec in self.targets:
            outdir = base / (spec.output if spec.output else safe_dirname(spec.name))
            multipage = None
            if spec.document_multipage is not None or spec.auto_multipage is not None:
                modes = set(MULTIPAGE_MODES[global_mode])
                for key, flag in (("document", spec.document_multipage),
                                  ("auto", spec.auto_multipage)):
                    if flag is True:
                        modes.add(key)
                    elif flag is False:
                        modes.discard(key)
                multipage = frozenset(modes)
            result.append(Target(spec.name, outdir, preset=dict(spec.preset),
                                 multipage=multipage))
        return result


def _choice(values) -> str:
    return ", ".join(str(v) for v in values)


class _Reader:
    """Typed access to one TOML table that rejects unknown keys."""

    def __init__(self, table: dict, where: str, allowed: set[str]):
        self.table, self.where = table, where
        for key in table:
            if key not in allowed:
                raise ConfigError(f'{where}: unknown key "{key}"')

    def _bad(self, key: str, expected: str) -> ConfigError:
        return ConfigError(f'{self.where}: key "{key}" must be {expected}, '
                           f"got {self.table[key]!r}")

    def str_(self, key: str, choices=None) -> str | None:
        if key not in self.table:
            return None
        value = self.table[key]
        if not isinstance(value, str) or not value.strip():
            raise self._bad(key, "a non-empty string")
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

    def mm(self, key: str) -> float | None:
        if key not in self.table:
            return None
        value = self.table[key]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not 0 <= value <= TRIM_MAX_MM):
            raise self._bad(key, f"a number of mm from 0 to {TRIM_MAX_MM:g}")
        return float(value)

    def port(self, key: str) -> int | None:
        if key not in self.table:
            return None
        value = self.table[key]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
            raise self._bad(key, "a port number from 1 to 65535")
        return value

    def table_(self, key: str) -> dict | None:
        if key not in self.table:
            return None
        if not isinstance(self.table[key], dict):
            raise self._bad(key, "a table")
        return self.table[key]


def _preset(rd: _Reader) -> dict:
    preset: dict = {}
    for key, dest in (("resolution", "resolution"), ("format", "fmt")):
        value = rd.int_(key, RESOLUTIONS) if key == "resolution" else rd.str_(key, FORMATS)
        if value is not None:
            preset[dest] = value
    size = rd.str_("size", tuple(panel.REGIONS))
    if size is not None:
        preset["width"], preset["height"] = panel.REGIONS[size]
    return preset


def _target(table, index: int, name_for_msgs: str) -> TargetSpec:
    if not isinstance(table, dict):
        raise ConfigError(f"{name_for_msgs}: [[target]] #{index} must be a table")
    label = f"{name_for_msgs}: target #{index}"
    name = table.get("name")
    if name is not None and isinstance(name, str) and name.strip():
        label = f'{name_for_msgs}: target "{name}"'
    rd = _Reader(table, label, {"name", "output", "document_multipage", "auto"})
    if "name" not in table:
        raise ConfigError(f'{label}: missing required key "name"')
    name = rd.str_("name").strip()
    try:
        check_name(name)
    except ValueError as exc:
        raise ConfigError(f"{label}: {exc}") from exc
    spec = TargetSpec(name, output=rd.str_("output"),
                      document_multipage=rd.bool_("document_multipage"))
    auto = rd.table_("auto")
    if auto is not None:
        arw = _Reader(auto, f"{label}.auto",
                      {"resolution", "format", "size", "multipage"})
        spec.preset = _preset(arw)
        spec.auto_multipage = arw.bool_("multipage")
    return spec


def load_config(path: Path) -> Config:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"{path.name}: cannot read file: {exc.strerror or exc}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{path.name}: invalid TOML: {exc}") from exc
    return load_config_text(text, path.name)


def load_config_text(text: str, fname: str = "config.toml") -> Config:
    """Parse and validate config text (the same rules as load_config).
    `fname` only appears in error messages. Raises ConfigError."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{fname}: invalid TOML: {exc}") from exc
    return parse_config(data, fname)


def parse_config(data: dict, fname: str = "config.toml") -> Config:
    """Validate an already parsed TOML table. Raises ConfigError."""
    top = _Reader(data, fname, {"printer", "output", "interval", "verbose",
                                "ignore_panel", "multipage", "defaults", "web", "target"})
    cfg = Config(printer=top.str_("printer"), interval=top.number("interval"),
                 verbose=top.bool_("verbose"), ignore_panel=top.bool_("ignore_panel"),
                 multipage=top.str_("multipage", tuple(MULTIPAGE_MODES)))
    output = top.str_("output")
    cfg.output = Path(output) if output is not None else None

    defaults = top.table_("defaults")
    if defaults is not None:
        d = _Reader(defaults, f"{fname}: [defaults]",
                    {"resolution", "color", "format", "source", "size", "open_after_scan",
                     "trim_left", "trim_top", "trim_right", "trim_bottom"})
        cfg.resolution = d.int_("resolution", RESOLUTIONS)
        cfg.color = d.str_("color", COLORS)
        cfg.format = d.str_("format", FORMATS)
        cfg.source = d.str_("source", SOURCES)
        cfg.size = d.str_("size", tuple(panel.REGIONS))
        cfg.open_after_scan = d.str_("open_after_scan", OPEN_MODES)
        cfg.trim_left = d.mm("trim_left")
        cfg.trim_top = d.mm("trim_top")
        cfg.trim_right = d.mm("trim_right")
        cfg.trim_bottom = d.mm("trim_bottom")

    web = top.table_("web")
    if web is not None:
        w = _Reader(web, f"{fname}: [web]", {"enabled", "bind", "port", "password_file"})
        cfg.web_enabled = w.bool_("enabled")
        cfg.web_bind = w.str_("bind")
        cfg.web_port = w.port("port")
        cfg.web_password_file = w.str_("password_file")

    raw_targets = data.get("target", [])
    if not isinstance(raw_targets, list):
        raise ConfigError(f'{fname}: "target" must be an array of tables ([[target]])')
    seen: set[str] = set()
    for i, table in enumerate(raw_targets, 1):
        spec = _target(table, i, fname)
        if spec.name in seen:
            raise ConfigError(f'{fname}: duplicate target name "{spec.name}"')
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


_ESCAPES = {"\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def _value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return _quote(str(value))


def _lines(pairs) -> list[str]:
    return [f"{key} = {_value(value)}" for key, value in pairs if value is not None]


def dump_config(cfg: Config) -> str:
    """Render a Config as TOML (the exact schema load_config reads).
    Comments are not preserved. A preset size that matches no known paper
    size is dropped."""
    blocks: list[list[str]] = []
    top = _lines([("printer", cfg.printer),
                  ("output", str(cfg.output) if cfg.output is not None else None),
                  ("interval", cfg.interval), ("verbose", cfg.verbose),
                  ("ignore_panel", cfg.ignore_panel), ("multipage", cfg.multipage)])
    if top:
        blocks.append(top)
    defaults = _lines([("resolution", cfg.resolution), ("color", cfg.color),
                       ("format", cfg.format), ("source", cfg.source), ("size", cfg.size),
                       ("open_after_scan", cfg.open_after_scan),
                       ("trim_left", cfg.trim_left), ("trim_top", cfg.trim_top),
                       ("trim_right", cfg.trim_right), ("trim_bottom", cfg.trim_bottom)])
    if defaults:
        blocks.append(["[defaults]"] + defaults)
    web = _lines([("enabled", cfg.web_enabled), ("bind", cfg.web_bind),
                  ("port", cfg.web_port), ("password_file", cfg.web_password_file)])
    if web:
        blocks.append(["[web]"] + web)
    for spec in cfg.targets:
        block = ["[[target]]"] + _lines([("name", spec.name), ("output", spec.output),
                                         ("document_multipage", spec.document_multipage)])
        blocks.append(block)
        auto = _lines([("resolution", spec.preset.get("resolution")),
                       ("format", spec.preset.get("fmt")),
                       ("size", size_name(spec.preset)),
                       ("multipage", spec.auto_multipage)])
        if auto:
            blocks.append(["[target.auto]"] + auto)
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
