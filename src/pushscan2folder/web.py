"""Optional web page for local (LAN / NAS) use: status, log, target editor,
settings form and raw config file editor.

Plain HTTP, stdlib only. The pages work without JavaScript; one small script
(APP_JS, edit pages only) warns about unsaved changes. Security model: one shared password,
in-memory sessions (only token hashes are stored), a global login lockout,
CSRF tokens on every POST form, Origin check and strict response headers.
Target folders set here must stay inside the base output directory; the
raw editor enforces the same and cannot change "output" or "printer". Meant
for a trusted LAN only. With PUSHSCAN_WEB_AUTH=0 there is no login at all (password
None): the CSRF token is then one per process and the page says so in the nav.

Thread safety: request threads only use ServiceStatus.snapshot(),
LogBuffer.lines(), service.request_targets() and file I/O. They never touch
service.targets (owned by the poll loop).
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import html
import ipaddress
import logging
import os
import re
import secrets
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlsplit

from . import SOURCE_URL, __version__, panel
from .config import (COLORS, FORMATS, SAME_FOLDER, SOURCES, Config, ConfigError, TargetSpec,
                     dump_config,
                     load_config, load_config_text, parse_config, size_name, write_config)
from .desktop import OPEN_MODES
from .platform_support import component_problem
from .protocol import PANEL_CHARS, VISIBLE_NAME_CHARS, check_name
from .service import (DEFAULT_FILENAME, MULTIPAGE_MODES, RESOLUTIONS, TRIM_MAX_MM,
                      check_targets, safe_dirname)
from .status import LogBuffer

log = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 8
SESSION_IDLE_SECONDS = 2 * 3600       # without any request
SESSION_MAX_SECONDS = 12 * 3600       # absolute lifetime, also the cookie Max-Age
MAX_SESSIONS = 20                     # the oldest session is dropped beyond this
MAX_FAILURES = 5
LOCKOUT_SECONDS = 60                  # doubles with every further lockout ...
MAX_LOCKOUT_SECONDS = 15 * 60         # ... up to this; a successful login resets it
MAX_BODY = 64 * 1024
MAX_CONNECTIONS = 32                  # concurrent connections (threads)
REQUEST_TIMEOUT = 30                  # seconds of socket inactivity (slowloris)
LOG_LINES_SHOWN = 500
MAX_ROWS = 100
ARIA_CURRENT = ' aria-current="page"'
MAX_FOLDER_CHARS = 255
COOKIE = "p2f_session"
SECURE_COOKIE = "__Host-p2f_session"  # needs Secure, Path=/ and no Domain
def _read_resource(name: str) -> bytes:
    """Data file next to this module; also found in a PyInstaller bundle."""
    path = Path(__file__).with_name(name)
    if not path.is_file() and getattr(sys, "_MEIPASS", None):
        path = Path(sys._MEIPASS) / "pushscan2folder" / name
    return path.read_bytes()


FAVICON = _read_resource("favicon.svg")

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; connect-src 'self'; "
                              "style-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    # "same-origin": with "no-referrer" browsers send Origin: null on form posts
    "Referrer-Policy": "same-origin",
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
}


def _now() -> float:
    """Monotonic clock; a function so tests can patch it."""
    return time.monotonic()


def esc(value) -> str:
    return html.escape(str(value), quote=True)


@dataclass
class WebContext:
    """What the web page needs to know about the running service.

    targets_from_env: targets come from --targets/PUSHSCAN_TARGETS, which
    would override the config file again at the next start.
    config_path: file the editors write (None = unknown, no editing).
    overrides: config key -> what overrides its file value (environment
    variable or command line option), shown on the settings page.
    effective: config key -> the value in use (display text).
    auth: False when the web page runs without a login (PUSHSCAN_WEB_AUTH=0).
    discover_fn: searches the network for scanners (discovery.discover); None
    hides the search. found: the result of the last search. Only an address
    from it can be set as the printer, so the page cannot point the service
    at any other host.
    """
    service: object                  # .status, .request_targets()
    log_buffer: LogBuffer
    printer: str
    output: Path
    multipage_mode: str = "document"
    config_path: Path | None = None
    targets_from_env: bool = False
    overrides: dict = field(default_factory=dict)
    effective: dict = field(default_factory=dict)
    auth: bool = True
    discover_fn: object = None       # () -> list[discovery.Scanner]
    found: list = field(default_factory=list)
    printer_pending: str | None = None   # set from the page, not yet read back

    def default_label(self, key: str, builtin: str) -> str:
        """The value in use for a setting without a per-target value."""
        return self.effective.get(key, builtin)

    def config_block_reason(self) -> str | None:
        if self.config_path is None:
            return ("No config file is known. Set PUSHSCAN_CONFIG to a writable file "
                    "to edit the configuration here.")
        return None

    def edit_block_reason(self) -> str | None:
        if self.targets_from_env:
            return ("The targets are set by PUSHSCAN_TARGETS / --targets. That setting "
                    "would override the config file again at the next start, so editing "
                    "is disabled. Remove it to edit the targets here.")
        if self.config_path is None:
            return ("No config file is known. Set PUSHSCAN_CONFIG to a writable file "
                    "to edit the targets here.")
        return None


def _digest(value: str | bytes) -> bytes:
    if isinstance(value, str):
        value = value.encode("utf-8", "surrogatepass")
    return hashlib.sha256(value).digest()


class Sessions:
    """In-memory sessions plus the global login lockout (thread safe).

    Only the SHA-256 of a session token is kept, so a memory dump or a debug
    print of this object does not reveal a usable cookie. A session ends
    after SESSION_IDLE_SECONDS without a request, SESSION_MAX_SECONDS after
    login, or when more than MAX_SESSIONS exist (oldest first). All sessions
    end with the process, so changing the password (a restart) logs out
    everyone.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # sha256(token) -> [csrf, created, last_seen]
        self._sessions: dict[bytes, list] = {}
        self._failures = 0
        self._lockouts = 0
        self._locked_until = 0.0

    def locked(self) -> bool:
        with self._lock:
            return _now() < self._locked_until

    def login(self, password_ok) -> str | None:
        """One login attempt, atomic with respect to the lockout counter.
        password_ok() is only called when not locked. Returns the new session
        token, None for a wrong password. Raises PermissionError while locked."""
        with self._lock:
            now = _now()
            if now < self._locked_until:
                raise PermissionError("locked")
            if not password_ok():
                self._failures += 1
                if self._failures >= MAX_FAILURES:
                    self._failures = 0
                    self._locked_until = now + min(LOCKOUT_SECONDS * 2 ** self._lockouts,
                                                   MAX_LOCKOUT_SECONDS)
                    self._lockouts += 1
                return None
            self._failures = 0
            self._lockouts = 0
            self._expire(now)
            while len(self._sessions) >= MAX_SESSIONS:
                oldest = min(self._sessions, key=lambda k: self._sessions[k][1])
                del self._sessions[oldest]
            token = secrets.token_urlsafe(32)
            self._sessions[_digest(token)] = [secrets.token_urlsafe(32), now, now]
            return token

    def _expire(self, now: float) -> None:
        for key in [k for k, e in self._sessions.items() if self._expired(e, now)]:
            del self._sessions[key]

    @staticmethod
    def _expired(entry: list, now: float) -> bool:
        return now - entry[2] > SESSION_IDLE_SECONDS or now - entry[1] > SESSION_MAX_SECONDS

    def lookup(self, token: str | None) -> str | None:
        """CSRF token of a valid session (refreshes its idle timer), else None."""
        if not token:
            return None
        key = _digest(token)
        with self._lock:
            entry = self._sessions.get(key)
            if entry is None:
                return None
            now = _now()
            if self._expired(entry, now):
                del self._sessions[key]
                return None
            entry[2] = now
            return entry[0]

    def delete(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(_digest(token), None)

    def clear(self) -> None:
        """End all sessions."""
        with self._lock:
            self._sessions.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)


# --- target editor model -------------------------------------------------------

_FOLDER_BAD_CHARS = re.compile(r"[\x00-\x1f\x7f\\]")


def check_web_folder(value: str, base: Path) -> None:
    """A folder typed on the web page must be "." (the base output directory
    itself) or a plain relative path below it: no absolute path, no "." or ".." component, no
    empty component, no backslash, control character or any of : < > " | ? *
    (drive letters, NTFS streams, wildcards), no Windows device name (CON,
    NUL, COM1 ...) and no component ending in a dot or a space. These rules
    are the same on every platform. Finally (symlinks resolved, UNC paths
    included) it must end up strictly inside the resolved base. Raises
    ValueError."""
    if not value:
        raise ValueError("folder is empty")
    if value == SAME_FOLDER:
        return  # "." alone: straight into the output directory
    if len(value) > MAX_FOLDER_CHARS:
        raise ValueError(f"folder is longer than {MAX_FOLDER_CHARS} characters")
    if _FOLDER_BAD_CHARS.search(value):
        raise ValueError("folder must not contain backslashes or control characters")
    if value.startswith("/") or PurePosixPath(value).is_absolute():
        raise ValueError("folder must be relative to the output directory, "
                         "absolute paths can only be set in the config file")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError('folder must not contain empty, "." or ".." parts')
    for part in parts:
        problem = component_problem(part)
        if problem:
            raise ValueError(f"folder part {part!r}: {problem}")
    root = Path(base).resolve(strict=False)
    resolved = (root / value).resolve(strict=False)
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError("folder resolves outside the output directory (symlink?)")


def web_editable(spec: TargetSpec, base: Path) -> bool:
    """True if the folder of a config file target passes check_web_folder.
    Others (absolute paths, "..", symlinks leading out) are set in the
    config file only; the web page shows such targets read-only."""
    try:
        check_web_folder(spec.output if spec.output else safe_dirname(spec.name), base)
    except ValueError:
        return False
    return True


def locked_specs(cfg: Config, base: Path) -> dict[str, TargetSpec]:
    """name -> config target the web page may not change (only delete)."""
    return {s.name: s for s in cfg.targets if not web_editable(s, base)}


@dataclass
class Row:
    name: str = ""
    output: str = ""
    docmp: bool = False
    res: str = ""
    fmt: str = ""
    size: str = ""
    automp: bool = False
    delete: bool = False
    existing: bool = False
    orig: str = ""          # name in the config file when the form was rendered


def row_from_spec(spec: TargetSpec, global_mode: str) -> Row:
    modes = MULTIPAGE_MODES[global_mode]
    p = spec.preset
    return Row(
        name=spec.name, output=spec.output or "",
        docmp=("document" in modes) if spec.document_multipage is None else spec.document_multipage,
        res=str(p["resolution"]) if "resolution" in p else "",
        fmt=p.get("fmt", ""), size=size_name(p) or "",
        automp=("auto" in modes) if spec.auto_multipage is None else spec.auto_multipage,
        existing=True, orig=spec.name)


def blank_row(global_mode: str) -> Row:
    modes = MULTIPAGE_MODES[global_mode]
    return Row(docmp="document" in modes, automp="auto" in modes)


def rows_from_form(form: dict[str, str]) -> list[Row]:
    try:
        count = max(0, min(int(form.get("rows", "0")), MAX_ROWS))
    except ValueError:
        count = 0
    rows = []
    for i in range(count):
        def get(key, i=i):
            return form.get(f"{key}_{i}", "")
        rows.append(Row(name=get("name").strip(), output=get("output").strip(),
                        docmp=bool(get("docmp")), res=get("res"),
                        fmt=get("fmt"), size=get("size"), automp=bool(get("automp")),
                        delete=bool(get("del")), existing=get("existing") == "1",
                        orig=get("orig") if get("existing") == "1" else ""))
    return rows


def claim_locked(rows: list[Row], locked: dict[str, TargetSpec]) -> list[str | None]:
    """For each row the name of the read-only target it stands for, else
    None. Each one is claimed by the first row that names it, so a forged
    form can keep or delete a read-only target but never copy its folder
    to a further target."""
    free = set(locked)
    claims: list[str | None] = []
    for row in rows:
        if row.orig in free:
            free.discard(row.orig)
            claims.append(row.orig)
        else:
            claims.append(None)
    return claims


def specs_from_rows(rows: list[Row], base: Path,
                    locked: dict[str, TargetSpec] | None = None
                    ) -> tuple[list[TargetSpec], list[str]]:
    """Validate the rows like the config file does, and their folders with
    check_web_folder. A row standing for a read-only target (see
    claim_locked) keeps it exactly as in the config file, whatever the form
    sent; it can only be deleted. Returns (specs, errors)."""
    locked = locked or {}
    specs: list[TargetSpec] = []
    errors: list[str] = []
    claims = claim_locked(rows, locked)
    seen = {c for row, c in zip(rows, claims) if c is not None and not row.delete}
    for n, (row, claim) in enumerate(zip(rows, claims), 1):
        if claim is not None:
            if not row.delete:
                specs.append(copy.deepcopy(locked[claim]))
            continue
        if row.delete or not row.name:
            continue
        label = f"Row {n}"
        try:
            check_name(row.name)
        except ValueError as exc:
            errors.append(f"{label}: {exc}")
            continue
        if row.name in seen:
            errors.append(f'{label}: duplicate target name "{row.name}"')
            continue
        seen.add(row.name)
        output = row.output or None
        try:
            check_web_folder(output or safe_dirname(row.name), base)
        except ValueError as exc:
            errors.append(f"{label}: {exc}")
        preset: dict = {}
        if row.res:
            if not row.res.isdigit() or int(row.res) not in RESOLUTIONS:
                errors.append(f"{label}: invalid resolution {row.res!r}")
            else:
                preset["resolution"] = int(row.res)
        if row.fmt:
            if row.fmt not in ("pdf", "jpeg"):
                errors.append(f"{label}: invalid format {row.fmt!r}")
            else:
                preset["fmt"] = row.fmt
        if row.size:
            if row.size not in panel.REGIONS:
                errors.append(f"{label}: invalid size {row.size!r}")
            else:
                preset["width"], preset["height"] = panel.REGIONS[row.size]
        specs.append(TargetSpec(row.name, output=output, preset=preset,
                                document_multipage=row.docmp, auto_multipage=row.automp))
    if not errors and not specs:
        errors.append("At least one target is required.")
    return specs, errors


def read_config(ctx: WebContext) -> Config:
    path = ctx.config_path
    return load_config(path) if path.exists() else Config()


def apply_targets(ctx: WebContext, rows: list[Row]) -> tuple[list[TargetSpec], list[str]]:
    """Validate the rows against the config file as it is on disk now, write
    it and hand the targets to the service. Only the targets of the file
    change; other keys are re-read so manual edits are not lost. Returns
    (specs, errors); nothing is written if there are errors. Raises
    ConfigError/OSError; warnings are logged."""
    cfg = read_config(ctx)
    specs, errors = specs_from_rows(rows, ctx.output, locked_specs(cfg, ctx.output))
    if errors:
        return specs, errors
    # The form has no file name field: keep a target's own template from the file.
    on_disk = {spec.name: spec for spec in cfg.targets}
    for spec in specs:
        if spec.filename is None and spec.name in on_disk:
            spec.filename = on_disk[spec.name].filename
    cfg.targets = list(specs)
    targets = cfg.build_targets(ctx.output, ctx.multipage_mode)
    try:
        warnings = check_targets(targets)
    except ValueError as exc:
        return specs, [str(exc)]
    write_config(ctx.config_path, dump_config(cfg))
    ctx.service.request_targets(targets)
    for w in warnings:
        log.warning(w)
    return specs, []


# --- settings form and raw editor model ----------------------------------------------

# Built-in values used when a key is not set anywhere.
BUILTIN = {"resolution": "300", "color": "color", "format": "pdf", "source": "auto",
           "size": "a4", "multipage": "document", "interval": "4", "open_after_scan": "off",
           "filename": DEFAULT_FILENAME,
           "trim_left": "0", "trim_top": "0", "trim_right": "0", "trim_bottom": "0"}
TRIM_KEYS = ("trim_left", "trim_top", "trim_right", "trim_bottom")
# Config keys the settings form edits (top level and [defaults]).
SETTING_KEYS = ("interval", "ignore_panel", "multipage", "resolution", "color", "format",
                "source", "size", "open_after_scan", "filename") + TRIM_KEYS
NUMBER_KEYS = ("interval",) + TRIM_KEYS


def settings_values(cfg: Config) -> dict[str, str]:
    """Form values (strings) for the settings of a config; "" = not set."""
    values = {}
    for key in SETTING_KEYS:
        value = getattr(cfg, key)
        if key == "ignore_panel":
            values[key] = "1" if value else ""
        else:
            values[key] = "" if value is None else f"{value:g}" if isinstance(value, float) else str(value)
    return values


def settings_from_form(form: dict[str, str]) -> dict[str, str]:
    values = {key: form.get(key, "").strip() for key in SETTING_KEYS}
    values["ignore_panel"] = "1" if form.get("ignore_panel") else ""
    return values


def check_settings(values: dict[str, str]) -> tuple[Config | None, list[str]]:
    """Validate form values with the config file rules (config.parse_config,
    so the allowed values and limits are the same). Returns (Config holding
    only these settings, errors)."""
    top: dict = {}
    defaults: dict = {}
    for key, text in values.items():
        if not text:
            continue
        value: object = text
        if key in NUMBER_KEYS:
            try:
                value = float(text)
            except ValueError:
                return None, [f'{key}: "{text}" is not a number']
        elif key == "resolution" and text.isdigit():
            value = int(text)
        elif key == "ignore_panel":
            value = True
        (top if key in ("interval", "ignore_panel", "multipage") else defaults)[key] = value
    if defaults:
        top["defaults"] = defaults
    try:
        return parse_config(top, "settings"), []
    except ConfigError as exc:
        return None, [str(exc)]


def apply_settings(ctx: WebContext, values: dict[str, str]) -> list[str]:
    """Validate and write the settings into the config file as it is on disk
    now (everything else, targets included, is kept). Returns errors;
    nothing is written then. Raises ConfigError/OSError. The running service
    is not changed here: it reads the changed file before its next poll cycle
    (ConfigWatcher)."""
    new, errors = check_settings(values)
    if errors:
        return errors
    cfg = read_config(ctx)
    for key in SETTING_KEYS:
        setattr(cfg, key, getattr(new, key))
    write_config(ctx.config_path, dump_config(cfg))
    return []


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def read_config_text(ctx: WebContext) -> str:
    """Text of the config file ("" if it does not exist). Raises OSError,
    UnicodeDecodeError."""
    path = ctx.config_path
    return path.read_bytes().decode("utf-8") if path.exists() else ""


def check_raw_config(ctx: WebContext, new: Config, disk: Config) -> list[str]:
    """What the raw editor must not change: the web page gets no file access
    beyond the output directory. `disk` is the file as it is now."""
    errors = []
    if new.output != disk.output and (new.output is None or Path(new.output) != Path(ctx.output)):
        errors.append('"output" cannot be changed on the web page, only in the file '
                      "itself or by the environment.")
    if new.printer != disk.printer and new.printer != ctx.printer:
        errors.append('"printer" cannot be changed on the web page, only in the file '
                      "itself or by the environment.")
    # [web] decides who can reach this page and which file holds the password:
    # changing it from here could expose the page or point the password at a
    # file with known content.
    web_keys = ("web_enabled", "web_bind", "web_port", "web_password_file")
    if any(getattr(new, k) != getattr(disk, k) for k in web_keys):
        errors.append('The [web] table cannot be changed on the web page, only in the '
                      "file itself or with pushscan2folder setup.")
    locked = locked_specs(disk, ctx.output)
    for spec in new.targets:
        if web_editable(spec, ctx.output):
            continue
        old = locked.get(spec.name)
        if old is not None and old.output == spec.output:
            continue                      # unchanged read-only target
        errors.append(f'Target "{spec.name}": the output folder '
                      f'{spec.output or safe_dirname(spec.name)!r} must be a relative path '
                      f"inside the output directory {str(ctx.output)!r}. Absolute paths and "
                      '".." can only be set by editing the file itself.')
    return errors


def apply_raw_config(ctx: WebContext, text: str, base_hash: str) -> tuple[list[str], str | None]:
    """Validate and write the config text from the raw editor. Returns
    (errors, current_text): current_text is set instead of errors when the
    file changed on disk since the form was shown. Nothing is written on an
    error. Targets are handed to the service (not with PUSHSCAN_TARGETS or
    without targets in the file); the service reads the rest of the changed
    file before its next poll cycle, except [web], which needs a restart. Raises
    OSError/UnicodeDecodeError."""
    disk_text = read_config_text(ctx)
    if text_hash(disk_text) != base_hash:
        return [], disk_text
    text = text.replace("\r\n", "\n")
    name = ctx.config_path.name
    try:
        new = load_config_text(text, name)
    except ConfigError as exc:
        return [str(exc)], None
    try:
        disk = load_config_text(disk_text, name)
    except ConfigError:
        disk = Config()                   # a broken file locks everything down
    errors = check_raw_config(ctx, new, disk)
    if errors:
        return errors, None
    targets = new.build_targets(ctx.output, ctx.multipage_mode)
    try:
        warnings = check_targets(targets)
    except ValueError as exc:
        return [str(exc)], None
    write_config(ctx.config_path, text)
    if targets and not ctx.targets_from_env:
        ctx.service.request_targets(targets)
    for w in warnings:
        log.warning(w)
    return [], None


# --- rendering -------------------------------------------------------------------

CSS = """\
:root { color-scheme: light dark; --bg:#f3f6fa; --fg:#18202d; --card:#fff; --line:#d3dce8;
        --soft:#ecf1f8; --muted:#556275; --accent:#1F5FAD; --accent-dark:#174A87;
        --on-accent:#fff; --accent-bg:#dce8f7;
        --bad:#b42318; --ok:#17703f; --warn:#8f5f00;
        --bad-bg:#fdecea; --ok-bg:#e0f3e8; --warn-bg:#fdf3d8; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#0e141f; --fg:#e2e8f1; --card:#161e2c; --line:#2a3548; --soft:#1d2736;
          --muted:#9aa7bb; --accent:#6FA3DE; --accent-dark:#8fb9e8; --on-accent:#08182c;
          --accent-bg:#1b2f4b;
          --bad:#ff9a8f; --ok:#6fd49a; --warn:#e8c060;
          --bad-bg:#3a1e1b; --ok-bg:#16321f; --warn-bg:#352c13; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
       font:16px/1.5 system-ui, sans-serif; }
main { max-width: 62rem; margin: 0 auto; padding: 0 16px 24px; }
a { color:var(--accent); }
code { font-size:.9em; word-break:break-all; }
nav { position:sticky; top:0; z-index:10; display:flex; flex-wrap:wrap; gap:4px 6px; align-items:center; padding:8px 16px;
      background:var(--card); border-bottom:1px solid var(--line); }
nav .brand { display:flex; align-items:center; gap:10px; font-weight:700; margin-right:14px;
             color:var(--fg); text-decoration:none; }
nav a.tab { padding:6px 12px; border-radius:6px; text-decoration:none; font-weight:600;
            color:var(--muted); }
nav a.tab:hover { background:var(--soft); }
nav a.tab.current { background:var(--accent-bg); color:var(--accent); }
nav form { margin-left:auto; }
nav button { background:transparent; border-color:transparent; color:var(--muted);
             font-weight:400; padding:6px 10px; }
nav button:hover { color:var(--fg); text-decoration:underline; }
h1 { font-size:1.45rem; margin:1.2rem 0 .6rem; }
h2 { font-size:1.05rem; margin:1.6rem 0 .5rem; }
section { background:var(--card); border:1px solid var(--line);
                    border-radius:10px; padding:10px 16px; margin:12px 0; min-width:0; }
.card h2 { margin:0; font-size:1.1rem; overflow-wrap:anywhere; }
.card-head { display:flex; align-items:center; justify-content:space-between; gap:12px;
             padding:2px 0 8px; margin-bottom:4px; border-bottom:1px solid var(--line); }
.card-tools { display:flex; gap:6px; flex:none; }
button.icon { padding:0; width:2.1rem; height:2.1rem; line-height:1; font-size:1.1rem;
              background:transparent; color:var(--accent); }
button.icon:hover { background:var(--soft); border-color:var(--accent); color:var(--accent); }
.group { min-width:0; margin:6px 0 4px; }
.group h3 { margin:6px 0 0; font-size:.78rem; text-transform:uppercase; letter-spacing:.05em;
            color:var(--muted); }
.group .hint { margin:0 0 2px; }
.checks { display:flex; flex-wrap:wrap; gap:0 28px; }
.card-foot { display:flex; justify-content:flex-end; margin-top:8px; padding-top:6px;
             border-top:1px dashed var(--line); }
label.check.danger { color:var(--bad); margin:4px 0; }
.savebar { position:sticky; bottom:0; z-index:5; display:flex; flex-wrap:wrap; align-items:center;
           gap:8px 12px; margin:16px 0 0; padding:10px 16px; background:var(--card);
           border:1px solid var(--line); border-radius:10px; }
.savebar button { padding:9px 26px; }
.savebar button.secondary { margin-left:auto; padding:7px 14px; }
.savebar .badge { margin-left:0; }
.pill.nopw { margin-left:auto; }
.cards { display:grid; grid-template-columns:repeat(auto-fit, minmax(10rem, 1fr)); gap:12px; }
.cards > div { background:var(--card); border:1px solid var(--line); border-radius:10px;
               padding:10px 14px; min-width:0; overflow-wrap:anywhere; }
.cards small { display:block; color:var(--muted); font-size:.8rem; margin-bottom:2px; }
.scroll { overflow-x:auto; padding:2px 0; }
table { border-collapse:collapse; width:100%; min-width:38rem; }
th, td { text-align:left; padding:7px 10px; vertical-align:top; }
th { font-size:.8rem; color:var(--muted); font-weight:600; border-bottom:1px solid var(--line);
     white-space:nowrap; }
tbody tr:nth-child(even) { background:var(--soft); }
.pill { display:inline-block; padding:1px 10px; border-radius:99px; font-size:.85rem;
        font-weight:600; white-space:nowrap; }
.pill.ok { background:var(--ok-bg); } .pill.bad { background:var(--bad-bg); }
.pill.warn { background:var(--warn-bg); }
pre { background:var(--card); border:1px solid var(--line); border-radius:10px;
      padding:10px 14px; overflow-x:auto; font-size:.82rem; line-height:1.4; }
pre .bad { font-weight:600; }
input[type=text], input[type=password], select, textarea { width:100%; padding:7px 9px;
      font:inherit; background:var(--bg); color:var(--fg);
      border:1px solid var(--line); border-radius:6px; }
input:focus-visible, select:focus-visible, textarea:focus-visible, button:focus-visible, a:focus-visible {
      outline:2px solid var(--accent); outline-offset:1px; }
button { font:inherit; font-weight:600; padding:8px 18px; border-radius:6px; cursor:pointer;
         border:1px solid var(--accent); background:var(--accent); color:var(--on-accent); }
button:hover { background:var(--accent-dark); border-color:var(--accent-dark); }
button.secondary { background:transparent; color:var(--accent); font-weight:600;
                   padding:5px 12px; }
button.secondary:hover { background:var(--soft); border-color:var(--accent); color:var(--accent); }
.sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0);
           white-space:nowrap; padding:0; border:0; margin:-1px; }
.badge { display:inline-block; margin-left:12px; padding:2px 10px; border-radius:99px;
         font-size:.85rem; font-weight:600; background:var(--warn-bg); color:var(--warn); }
.badge[hidden] { display:none; }
textarea { font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
           font-size:.88rem; line-height:1.45; tab-size:2; resize:vertical; }
.wrap { white-space:pre-wrap; overflow-wrap:anywhere; }
.hint { margin:2px 0 0; color:var(--muted); font-size:.85rem; }
.override { margin:4px 0 0; padding:3px 10px; border-radius:6px; font-size:.85rem;
            background:var(--warn-bg); color:var(--warn); }
label { display:block; margin:8px 0 3px; font-size:.9rem; }
label.check { display:flex; gap:8px; align-items:center; margin:10px 0 2px; font-size:1rem; }
.fields { display:grid; grid-template-columns:1fr; gap:0 24px; }
@media (min-width: 700px) { .fields { grid-template-columns:1fr 1fr; } }
.card.locked { background:var(--soft); }
.card.locked .locked-info { color:var(--muted); }
.locked-info p { margin:.4rem 0; }
.login { max-width:22rem; margin:12vh auto 0; text-align:center; }
.login section { padding:20px; }
.login h1 { margin:.6rem 0 1rem; }
.login label { text-align:left; }
.login button { width:100%; margin-top:14px; }
.save { margin:16px 0; } .save button { padding:10px 28px; }
form.inline { display:inline-block; margin:.3rem 0; }
.ro { margin:.4rem 0 0; } .ro + .hint { margin-bottom:.6rem; } .ro code { word-break:break-all; }
.ok { color:var(--ok); } .bad { color:var(--bad); } .warn { color:var(--warn); }
.error { border-color:var(--bad); } .muted { color:var(--muted); font-size:.9rem; }
footer { max-width:62rem; margin:0 auto; padding:0 16px 24px; color:var(--muted);
         font-size:.82rem; }
footer a { color:inherit; }
body.login-page footer { max-width:22rem; text-align:center; }
"""

# The only script. Served from memory at /app.js and used on the edit pages
# only; the pages work without it.
APP_JS = """\
// Edit forms (data-warn-unsaved): warn before the page is left with changes
// that were not saved. Textareas with data-tab-indent insert two spaces on Tab.
(function () {
  // Remember the state of a form and show or hide the "Unsaved changes" badge.
  function watch(form) {
    var badge = document.getElementById("unsaved");
    var dirty = false;
    function setDirty(value) {
      dirty = value;
      if (badge) { badge.hidden = !value; }
    }

    // Typing in a field, or changing a menu or checkbox, makes the form dirty.
    form.addEventListener("input", function () { setDirty(true); });
    form.addEventListener("change", function () { setDirty(true); });
    // Any button of the form sends the data to the server: not dirty any more.
    form.addEventListener("submit", function () { setDirty(false); });

    // The browser asks "Leave site?" when this handler cancels the event.
    window.addEventListener("beforeunload", function (event) {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    });

    // The server sets data-dirty="1" after add, move or an error (not saved yet).
    setDirty(form.getAttribute("data-dirty") === "1");
  }

  // Tab inserts two spaces instead of moving focus (Escape, then Tab, leaves).
  function tabIndent(area) {
    var escaped = false;
    area.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { escaped = true; return; }
      if (event.key !== "Tab" || event.shiftKey || event.ctrlKey || event.altKey ||
          event.metaKey || escaped) {
        escaped = false;
        return;
      }
      event.preventDefault();
      var start = area.selectionStart;
      area.value = area.value.slice(0, start) + "  " + area.value.slice(area.selectionEnd);
      area.selectionStart = area.selectionEnd = start + 2;
      area.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }

  // Status and log: fetch the page every few seconds and replace only the
  // content when it changed, so nothing flickers. A logged-out session
  // (redirect to the login page) reloads the whole page instead.
  function autoRefresh(main) {
    var seconds = parseInt(main.getAttribute("data-refresh"), 10) || 10;
    setInterval(function () {
      if (document.hidden) { return; }
      fetch(window.location.href, { credentials: "same-origin", cache: "no-store" })
        .then(function (resp) {
          if (!resp.ok || resp.redirected) { window.location.reload(); return null; }
          return resp.text();
        })
        .then(function (text) {
          if (text === null) { return; }
          var doc = new DOMParser().parseFromString(text, "text/html");
          var fresh = doc.querySelector("main");
          if (fresh && fresh.innerHTML !== main.innerHTML) {
            main.innerHTML = fresh.innerHTML;
          }
        })
        .catch(function () { /* offline for a moment: try again next time */ });
    }, seconds * 1000);
  }

  document.querySelectorAll("main[data-refresh]").forEach(autoRefresh);
  document.querySelectorAll("form[data-warn-unsaved]").forEach(watch);
  document.querySelectorAll("textarea[data-tab-indent]").forEach(tabIndent);
})();
"""

FOOTER = (f'<footer>pushscan2folder {esc(__version__)} &middot; '
          f'<a href="{esc(SOURCE_URL)}" rel="noopener noreferrer">Source code</a> '
          "(AGPL-3.0)</footer>")


def _page(title: str, body: str, *, nav: str = "", refresh: bool = False,
          script: bool = False, body_class: str = "") -> bytes:
    # Status and log update themselves: app.js swaps in the new content without
    # reloading the page; without JavaScript the browser reloads every 10 s.
    script_tag = '<script src="/app.js" defer></script>' if script or refresh else ""
    cls = f' class="{body_class}"' if body_class else ""
    meta = ('<noscript><meta http-equiv="refresh" content="10"></noscript>'
            if refresh else "")
    main = '<main data-refresh="10">' if refresh else "<main>"
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">{meta}'
            f'<title>{esc(title)} - pushscan2folder</title>'
            f'<link rel="icon" href="/favicon.svg" type="image/svg+xml">'
            f'<link rel="stylesheet" href="/style.css">{script_tag}</head>'
            f'<body{cls}>{nav}'
            f"{main}{body}</main>{FOOTER}</body></html>").encode()


def _nav(ctx: WebContext, csrf: str, active: str = "") -> str:
    tabs = "".join(
        f'<a class="tab{" current" if key == active else ""}" href="{href}"'
        f'{ARIA_CURRENT if key == active else ""}>{label}</a>'
        for key, href, label in (("status", "/", "Status"), ("log", "/log", "Log"),
                                 ("targets", "/targets", "Targets"),
                                 ("settings", "/settings", "Settings"),
                                 ("config", "/config", "config.toml")))
    if ctx.auth:
        end = ('<form method="post" action="/logout">'
               f'<input type="hidden" name="csrf" value="{esc(csrf)}">'
               '<button type="submit">Log out</button></form>')
    else:
        end = ('<span class="pill warn nopw" title="Anyone who can reach this port can change '
               'targets and settings">No password set</span>')
    return ('<nav><a class="brand" href="/"><img src="/favicon.svg" width="28" height="28" '
            f'alt="">pushscan2folder</a>{tabs}{end}</nav>')


def _fmt_time(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _preset_summary(preset: dict) -> str:
    parts = []
    if "resolution" in preset:
        parts.append(f"{preset['resolution']} dpi")
    if "fmt" in preset:
        parts.append(preset["fmt"])
    if "width" in preset or "height" in preset:
        parts.append(size_name(preset) or f"{preset.get('width')}x{preset.get('height')}")
    return ", ".join(parts) or "panel settings"


def render_login(message: str = "") -> bytes:
    note = f'<p class="bad">{esc(message)}</p>' if message else ""
    body = ('<div class="login"><section><img src="/favicon.svg" width="56" height="56" alt="">'
            '<h1>pushscan2folder</h1>' + note +
            '<form method="post" action="/login"><label for="pw">Password</label>'
            '<input id="pw" type="password" name="password" autocomplete="current-password" '
            'autofocus><button type="submit">Log in</button></form></section></div>')
    return _page("Log in", body, body_class="login-page")


def render_status(ctx: WebContext, csrf: str) -> bytes:
    snap = ctx.service.status.snapshot()
    last_ok, last_err = snap["last_ok"], snap["last_error"]
    if last_err and (not last_ok or last_err[0] >= last_ok):
        conn = '<span class="pill bad">Poll failed</span>'
    elif last_ok:
        conn = '<span class="pill ok">Connected</span>'
    else:
        conn = '<span class="pill warn">No poll yet</span>'
    if snap["busy"]:
        work = f'<span class="pill warn">Scanning for {esc(snap["busy"])} ...</span>'
    elif snap["pending"]:
        work = '<span class="pill warn">Changes pending</span>'
    else:
        work = '<span class="pill ok">Idle</span>'
    parts = ["<h1>Status</h1>", '<div class="cards">'
             f'<div><small>Printer</small><strong>{esc(ctx.printer)}</strong></div>'
             f"<div><small>Connection</small>{conn}</div>"
             f'<div><small>Last successful poll</small>'
             f'{esc(_fmt_time(last_ok)) if last_ok else "-"}</div>'
             f"<div><small>State</small>{work}</div></div>"]
    if last_err:
        when, msg = last_err
        parts.append(f'<p class="bad">Last poll failed at {esc(_fmt_time(when))}: {esc(msg)}</p>')
    if snap["pending"]:
        parts.append('<p class="warn">Target changes are pending; they are applied '
                     'before the next poll cycle.</p>')

    modes = MULTIPAGE_MODES.get(ctx.multipage_mode, frozenset())
    rows = []
    long_names = False
    for t in snap["targets"]:
        eff = frozenset(t.multipage) if t.multipage is not None else modes
        mp = (f'Document: {"yes" if "document" in eff else "no"}, '
              f'Auto: {"yes" if "auto" in eff else "no"}')
        long = len(t.name) > VISIBLE_NAME_CHARS
        long_names = long_names or long
        rows.append(f"<tr><td>{esc(t.name)}{' *' if long else ''}</td><td>{esc(t.outdir)}</td>"
                    f'<td><span class="pill {"ok" if t.registered else "bad"}">'
                    f'{"yes" if t.registered else "no"}</span></td>'
                    f"<td>{esc(_preset_summary(t.preset))}</td><td>{esc(mp)}</td></tr>")
    parts.append('<h2>Targets</h2><section class="scroll"><table><thead><tr><th>Name</th><th>Folder</th>'
                 "<th>Registered</th><th>Auto scan preset</th><th>Multi-page</th></tr></thead><tbody>"
                 + ("".join(rows) or '<tr><td colspan="5">none</td></tr>') + "</tbody></table></section>")
    if long_names:
        parts.append(f'<p class="muted">* The printer panel shows only the first '
                     f"{VISIBLE_NAME_CHARS} characters of this name.</p>")

    rows = []
    for r in snap["history"]:
        files = ", ".join(os.path.basename(f) for f in r.files)
        cls = "bad" if r.result == "error" else ("ok" if r.result == "ok" else "warn")
        rows.append(f"<tr><td>{esc(_fmt_time(r.time))}</td><td>{esc(r.target)}</td>"
                    f"<td>{esc(r.method)}</td><td>{esc(r.pages)}</td>"
                    f'<td><span class="pill {cls}">{esc(r.result)}</span></td><td>{esc(files)}</td>'
                    f"<td>{esc(r.detail)}</td></tr>")
    parts.append('<h2>Last scans</h2><section class="scroll"><table><thead><tr><th>Time</th>'
                 "<th>Target</th><th>Method</th><th>Pages</th><th>Result</th><th>Files</th>"
                 "<th>Detail</th></tr></thead><tbody>"
                 + ("".join(rows) or '<tr><td colspan="7">no scans yet</td></tr>')
                 + "</tbody></table></section>")
    return _page("Status", "".join(parts), nav=_nav(ctx, csrf, "status"), refresh=True)


def _log_line(line: str) -> str:
    """Escaped log line; ERROR / WARNING lines get a colour class."""
    html = esc(line)
    if " ERROR " in line or " CRITICAL " in line:
        return f'<span class="bad">{html}</span>'
    if " WARNING " in line:
        return f'<span class="warn">{html}</span>'
    return html


def render_log(ctx: WebContext, csrf: str) -> bytes:
    lines = ctx.log_buffer.lines()[-LOG_LINES_SHOWN:]
    body = (f"<h1>Log</h1><p class=\"muted\">Last {LOG_LINES_SHOWN} lines at most, newest "
            f"last.</p><pre>{chr(10).join(_log_line(x) for x in lines)}</pre>")
    return _page("Log", body, nav=_nav(ctx, csrf, "log"), refresh=True)


def _select(name: str, current: str, options: list[tuple[str, str]], disabled: bool) -> str:
    opts = "".join(f'<option value="{esc(v)}"{" selected" if v == current else ""}>{esc(t)}</option>'
                   for v, t in options)
    return f'<select name="{esc(name)}"{" disabled" if disabled else ""}>{opts}</select>'


def _check(name: str, checked: bool, label: str, disabled: bool) -> str:
    return (f'<label class="check"><input type="checkbox" name="{esc(name)}" value="1"'
            f'{" checked" if checked else ""}{" disabled" if disabled else ""}> {esc(label)}</label>')


def _tools(i: int, count: int, row: Row) -> str:
    """Small move/remove buttons in the header of card i. Plain submit buttons:
    the server does the work. The text is in aria-label and title."""
    def btn(op: str, symbol: str, label: str) -> str:
        return (f'<button type="submit" name="op" value="{op}_{i}" class="icon" '
                f'aria-label="{label}" title="{label}">{symbol}</button>')
    out = ""
    if i > 0:
        out += btn("up", "&uarr;", "Move up")
    if i < count - 1:
        out += btn("down", "&darr;", "Move down")
    if not row.existing:
        out += btn("remove", "&times;", "Remove")
    return f'<div class="card-tools">{out}</div>' if out else ""


def _card_head(title: str, tools: str) -> str:
    return f'<div class="card-head"><h2>{title}</h2>{tools}</div>'


def _card_foot(i: int, row: Row, disabled: bool) -> str:
    """The delete checkbox, set apart at the bottom right (existing targets only)."""
    if not row.existing:
        return ""
    return ('<div class="card-foot">'
            + _check(f"del_{i}", row.delete, "Delete this target", disabled).replace(
                'class="check"', 'class="check danger"', 1)
            + "</div>")


def _locked_row_html(i: int, count: int, row: Row, spec: TargetSpec, global_mode: str) -> str:
    """A target whose folder is outside the output directory: read-only."""
    shown = row_from_spec(spec, global_mode)
    folder = spec.output if spec.output else f"(default: {safe_dirname(spec.name)})"
    return (
        '<section class="card locked">' + _card_head(esc(spec.name), _tools(i, count, row)) +
        f'<input type="hidden" name="existing_{i}" value="1">'
        f'<input type="hidden" name="orig_{i}" value="{esc(spec.name)}">'
        '<div class="locked-info">'
        f'<p>Output folder: <code>{esc(folder)}</code></p>'
        f'<p>This folder is outside the output directory. It is set in the '
        f"config file and can only be changed there; the web page keeps this target "
        f"unchanged.</p>"
        f"<p>Auto scan preset: {esc(_preset_summary(spec.preset))}. Multi-page dialog: "
        f'Document {"yes" if shown.docmp else "no"}, Auto scan {"yes" if shown.automp else "no"}.</p>'
        "</div>" + _card_foot(i, row, False) + "</section>")


def _row_html(i: int, count: int, row: Row, disabled: bool,
              defaults: dict[str, str] | None = None) -> str:
    """Card of one target. `defaults`: the value in use per setting, shown in
    the "Default (...)" entry that stands for "not set for this target"."""
    defaults = defaults or {}

    def keep(key: str, suffix: str = "") -> list[tuple[str, str]]:
        return [("", f"Default ({defaults.get(key, BUILTIN[key])}{suffix})")]

    def label(text: str, name: str) -> str:
        return f'<label for="{name}_{i}">{text}</label>'

    def sel(name: str, current: str, options: list[tuple[str, str]]) -> str:
        return _select(f"{name}_{i}", current, options, disabled).replace(
            "<select ", f'<select id="{name}_{i}" ', 1)

    off = " disabled" if disabled else ""
    title = esc(row.name) if row.name else "New target"
    return (
        '<section class="card">' + _card_head(title, _tools(i, count, row)) +
        f'<input type="hidden" name="existing_{i}" value="{"1" if row.existing else "0"}">'
        + (f'<input type="hidden" name="orig_{i}" value="{esc(row.orig)}">' if row.existing else "")
        + '<div class="fields"><div class="group"><h3>Panel name and folder</h3>'
        + label("Name (panel entry)", "name")
        + f'<input type="text" id="name_{i}" name="name_{i}" value="{esc(row.name)}" maxlength="31"{off}>'
        + label("Output folder below the output directory (empty = default)", "output")
        + f'<input type="text" id="output_{i}" name="output_{i}" value="{esc(row.output)}" '
        f'maxlength="{MAX_FOLDER_CHARS}"{off}>'
        + '</div><div class="group"><h3>Auto scan preset</h3><p class="hint">Empty = the default of the '
        '<a href="/settings">Settings</a> page.</p>'
        + label("Resolution", "res")
        + sel("res", row.res, keep("resolution", " dpi") + [(str(r), f"{r} dpi") for r in RESOLUTIONS])
        + label("Format", "fmt")
        + sel("fmt", row.fmt, keep("format") + [("pdf", "pdf"), ("jpeg", "jpeg")])
        + label("Size", "size")
        + sel("size", row.size, keep("size") + [(s, s) for s in panel.REGIONS])
        + '</div></div><div class="group"><h3>Multi-page dialog</h3><div class="checks">'
        + _check(f"docmp_{i}", row.docmp, 'Multi-page dialog for "Document"', disabled)
        + _check(f"automp_{i}", row.automp, 'Multi-page dialog for "Auto scan"', disabled)
        + "</div></div>" + _card_foot(i, row, disabled) + "</section>")


def render_targets(ctx: WebContext, csrf: str, rows: list[Row] | None = None,
                   errors: list[str] = (), notes: list[str] = (),
                   dirty: bool = False) -> bytes:
    reason = ctx.edit_block_reason()
    parts = ["<h1>Targets</h1>"]
    for e in errors:
        parts.append(f'<section class="error bad">{esc(e)}</section>')
    for n in notes:
        parts.append(f'<p class="warn">{esc(n)}</p>')
    if reason:
        parts.append(f'<section class="warn">{esc(reason)}</section>')
        snap = ctx.service.status.snapshot()
        items = "".join(f"<li>{esc(t.name)} &rarr; {esc(t.outdir)}</li>" for t in snap["targets"])
        parts.append(f"<h2>Current targets</h2><ul>{items or '<li>none</li>'}</ul>")
        return _page("Targets", "".join(parts), nav=_nav(ctx, csrf, "targets"))

    parts.append(f'<p class="muted">Source: config file <code>{esc(ctx.config_path)}</code>'
                 + ("" if ctx.config_path.exists() else " (does not exist yet; saving creates it)")
                 + ". Only targets are edited here; the scan defaults and other settings are "
                 'on the <a href="/settings">Settings</a> page. Saving rewrites the file and '
                 "<strong>comments in it are not preserved</strong>. Folders typed here are always created below the "
                 f"output directory <code>{esc(ctx.output)}</code> (<code>.</code> means the "
                 "output directory itself); absolute paths and "
                 "<code>..</code> can only be set in the config file. Allowed name characters: "
                 f"{esc(PANEL_CHARS)} (max. 31).</p>")
    try:
        cfg = read_config(ctx)
    except ConfigError as exc:
        parts.append(f'<section class="error bad">Cannot read the config file: '
                     f"{esc(exc)}</section>")
        return _page("Targets", "".join(parts), nav=_nav(ctx, csrf, "targets"))
    if rows is None:
        rows = [row_from_spec(s, ctx.multipage_mode) for s in cfg.targets]
        if not rows:
            rows = [blank_row(ctx.multipage_mode)]
    locked = locked_specs(cfg, ctx.output)
    claims = claim_locked(rows, locked)
    n = len(rows)
    defaults = {k: ctx.default_label(k, BUILTIN[k]) for k in ("resolution", "color", "format", "size")}
    # Pressing Enter in a text field "clicks" the first submit button of the form, so
    # the first button must be Save (visually hidden, the visible one is in the bar below).
    dirty_attr = ' data-dirty="1"' if dirty else ""
    form = [f'<form id="targets-form" method="post" action="/targets" data-warn-unsaved{dirty_attr}>'
            f'<input type="hidden" name="csrf" '
            f'value="{esc(csrf)}"><input type="hidden" name="rows" value="{n}">'
            '<button type="submit" name="op" value="save" class="sr-only" tabindex="-1" '
            'aria-hidden="true">Save</button>']
    form += [_locked_row_html(i, n, r, locked[c], ctx.multipage_mode) if c is not None
             else _row_html(i, n, r, False, defaults) for i, (r, c) in enumerate(zip(rows, claims))]
    form.append('<div class="savebar"><button type="submit" name="op" value="save">Save</button>'
                '<span id="unsaved" class="badge" hidden>Unsaved changes</span>'
                '<button type="submit" name="op" value="add" class="secondary">Add target</button>'
                "</div></form>")
    parts.append("".join(form))
    return _page("Targets", "".join(parts), nav=_nav(ctx, csrf, "targets"), script=True)


# --- settings and raw config pages ---------------------------------------------------

def _field(label: str, control: str, key: str, help_text: str, ctx: WebContext) -> str:
    note = ""
    if key in ctx.overrides:
        note = (f'<p class="override">Overridden by {esc(ctx.overrides[key])}. In use: '
                f'<code>{esc(ctx.effective.get(key, "?"))}</code>. The value saved here has '
                "no effect while that is set.</p>")
    control = control.replace(f'name="{key}"', f'name="{key}" id="f-{key}"', 1)
    return (f'<div><label for="f-{key}">{esc(label)}</label>{control}'
            f'<p class="hint">{esc(help_text)}</p>{note}</div>')


def _text_input(name: str, value: str, placeholder: str, numeric: bool = True) -> str:
    kind = 'inputmode="decimal" maxlength="12"' if numeric else 'maxlength="120"'
    return (f'<input type="text" name="{esc(name)}" value="{esc(value)}" {kind} '
            f'placeholder="{esc(placeholder)}">')


def _setting_select(key: str, value: str, options: list[tuple[str, str]]) -> str:
    unset = [("", f"Not set (built-in: {BUILTIN[key]})")]
    return _select(key, value, unset + options, False)


def _printer_html(ctx: WebContext, csrf: str, scanners: list | None) -> str:
    """The printer line of the settings page, with the network search."""
    out = [f'<p class="ro">Printer: <code>{esc(ctx.printer)}</code></p>']
    if "printer" in ctx.overrides:
        out.append(f'<p class="hint">Overridden by {esc(ctx.overrides["printer"])}, so it '
                   "can only be changed there.</p>")
        return "".join(out)
    if ctx.discover_fn is None:
        out.append('<p class="hint">Not editable here. Change it in the config file.</p>')
        return "".join(out)
    hidden = f'<input type="hidden" name="csrf" value="{esc(csrf)}">'
    out.append('<form method="post" action="/printer/search" class="inline">' + hidden
               + '<button type="submit" class="secondary">Search the network</button></form>'
               '<p class="hint">Looks for scanners (eSCL, mDNS) for about 2 seconds. In Docker '
               "with the default bridge network it finds nothing; set the address in the "
               "config file then.</p>")
    if scanners is None:
        return "".join(out)
    if not scanners:
        out.append('<p class="warn">No scanner answered. A firewall, a VPN or a separate '
                   "network can block the search.</p>")
        return "".join(out)
    rows = []
    for scanner in scanners:
        if scanner.address == ctx.printer:
            action = '<span class="badge">in use</span>'
        else:
            action = ('<form method="post" action="/printer/use" class="inline">' + hidden
                      + f'<input type="hidden" name="address" value="{esc(scanner.address)}">'
                      '<button type="submit" class="secondary">Use</button></form>')
        rows.append(f"<tr><td><code>{esc(scanner.address)}</code></td>"
                    f"<td>{esc(scanner.model or scanner.name)}</td><td>{action}</td></tr>")
    out.append('<div class="scroll"><table><thead><tr><th>Address</th><th>Scanner</th>'
               "<th></th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")
    return "".join(out)


def set_printer(ctx: WebContext, address: str) -> None:
    """Write `address` as "printer" into the config file (everything else is
    kept). The caller checked it against ctx.found. Raises ConfigError/OSError."""
    cfg = read_config(ctx)
    cfg.printer = address
    write_config(ctx.config_path, dump_config(cfg))


def render_settings(ctx: WebContext, csrf: str, values: dict[str, str] | None = None,
                    errors: list[str] = (), notes: list[str] = (),
                    dirty: bool = False, scanners: list | None = None) -> bytes:
    parts = ["<h1>Settings</h1>"]
    for e in errors:
        parts.append(f'<section class="error bad">{esc(e)}</section>')
    for n in notes:
        parts.append(f'<p class="ok">{esc(n)}</p>')
    reason = ctx.config_block_reason()
    if reason:
        parts.append(f'<section class="warn">{esc(reason)}</section>')
        return _page("Settings", "".join(parts), nav=_nav(ctx, csrf, "settings"))
    if values is None:
        try:
            values = settings_values(read_config(ctx))
        except ConfigError as exc:
            parts.append(f'<section class="error bad">Cannot read the config file: '
                         f'{esc(exc)}</section><p><a href="/config">Edit config.toml '
                         "directly</a></p>")
            return _page("Settings", "".join(parts), nav=_nav(ctx, csrf, "settings"))
    exists = ctx.config_path.exists()
    parts.append(f'<p class="muted">Source: config file <code>{esc(ctx.config_path)}</code>'
                 + ("" if exists else " (does not exist yet; saving creates it)")
                 + ". Saving rewrites the file and comments in it are not preserved. "
                 "Changes take effect within a few seconds. Empty fields are removed from the "
                 'file, so the built-in value applies. <a href="/config">Edit config.toml '
                 "directly</a> keeps comments.</p>")

    ro = [_printer_html(ctx, csrf, scanners)]
    note = (f' Overridden by {esc(ctx.overrides["output"])}.' if "output" in ctx.overrides
            else "")
    ro.append(f'<p class="ro">Output folder: <code>{esc(ctx.output)}</code></p>'
              f'<p class="hint">Not editable here. Change it in the config file.{note}</p>')
    try:
        disk = read_config(ctx)
    except ConfigError:
        disk = Config()
    ro.append('<p class="ro">Web page: <code>enabled={}, bind={}, port={}, password file={}'
              '</code></p><p class="hint">The <code>[web]</code> table of the config file is '
              "not editable here, so the login cannot be changed from the web page.</p>".format(
                  esc("yes" if disk.web_enabled else "no"), esc(disk.web_bind or "-"),
                  esc(disk.web_port or "-"), esc(disk.web_password_file or "-")))
    parts.append('<h2>Fixed</h2><section>' + "".join(ro) + "</section>")

    def v(key):
        return values.get(key, "")

    sel = _setting_select
    scan = [
        _field("Resolution", sel("resolution", v("resolution"),
                                 [(str(r), f"{r} dpi") for r in RESOLUTIONS]), "resolution",
               "Used where the printer panel sends no resolution, and always with "
               '"Ignore panel". Higher is sharper but makes bigger files.', ctx),
        _field("Colour", sel("color", v("color"), [(c, c) for c in COLORS]), "color",
               "Colour mode, only used with \"Ignore panel\" (or if the panel sends none), "
               "because the panel always sends the colour of the start button.", ctx),
        _field("Format", sel("format", v("format"), [(f, f) for f in FORMATS]), "format",
               "File type of the scan (pdf or jpeg), same rule as the resolution.", ctx),
        _field("Source", sel("source", v("source"), [(x, x) for x in SOURCES]), "source",
               "Where the paper is: auto uses the document feeder if paper is loaded, "
               "else the glass (platen).", ctx),
        _field("Paper size", sel("size", v("size"), [(n, n) for n in panel.REGIONS]), "size",
               "Scanned area, used where the panel sends no size.", ctx),
    ]
    trims = [
        _field(f"Trim {side} (mm)", _text_input(f"trim_{side}", v(f"trim_{side}"), "0"),
               f"trim_{side}", f"Cuts this border off by scanning a smaller area, 0 to "
               f"{TRIM_MAX_MM:g} mm. Glass only, the document feeder is not trimmed.", ctx)
        for side in ("left", "top", "right", "bottom")]
    behaviour = [
        _field("Multi-page dialog", sel("multipage", v("multipage"),
                                        [(m, m) for m in MULTIPAGE_MODES]), "multipage",
               "For which panel document types a glass scan asks for further pages "
               "(multi-page PDF): document, auto, both or off. Targets can override it.", ctx),
        _field("Poll interval (seconds)", _text_input("interval", v("interval"), "4"),
               "interval", "How often the printer is asked for scan requests. Must be "
               "greater than 0.", ctx),
        _field("File name", _text_input("filename", v("filename"), DEFAULT_FILENAME, numeric=False),
               "filename", "Name of a scan without extension. Fields: {name} (panel "
               "name), {date} (2026-11-22), {time} (183000) and {now:...} with strftime "
               "codes. An existing file is never overwritten, a -1, -2 ... is added. "
               "Targets can set their own in the config file.", ctx),
        _field("Open after scan", sel("open_after_scan", v("open_after_scan"),
                                      [(m, m) for m in OPEN_MODES]), "open_after_scan",
               "off, folder (opens the folder, on Windows with the new file selected) or "
               "file (opens the scan). Only works when the program runs on a desktop PC "
               "with a logged-in user, not in Docker or on a server.", ctx),
        _field("Ignore panel", _check("ignore_panel", bool(v("ignore_panel")),
                                      "Always use the values above", False),
               "ignore_panel", "Off: the choices made on the printer panel (colour, size, "
               "format, ...) are used. On: they are ignored.", ctx),
    ]
    dirty_attr = " data-dirty=\"1\"" if dirty else ""
    form = (f'<form id="settings-form" method="post" action="/settings" data-warn-unsaved'
            f'{dirty_attr}><input type="hidden" name="csrf" value="{esc(csrf)}">'
            '<h2>Scan defaults</h2><section><p class="muted">Used when neither the printer '
            "panel nor the target (Auto scan preset) sets a value.</p>"
            '<div class="fields">' + "".join(scan) + "</div></section>"
            "<h2>Trim</h2><section>" '<div class="fields">' + "".join(trims) + "</div></section>"
            "<h2>Behaviour</h2><section>" '<div class="fields">' + "".join(behaviour)
            + "</div></section>"
            '<p class="save"><button type="submit">Save</button>'
            '<span id="unsaved" class="badge" hidden>Unsaved changes</span></p></form>')
    parts.append(form)
    return _page("Settings", "".join(parts), nav=_nav(ctx, csrf, "settings"), script=True)


def render_config(ctx: WebContext, csrf: str, text: str | None = None,
                  digest: str | None = None, errors: list[str] = (),
                  notes: list[str] = (), dirty: bool = False) -> bytes:
    parts = ["<h1>config.toml</h1>"]
    for e in errors:
        parts.append(f'<section class="error bad wrap">{esc(e)}</section>')
    for n in notes:
        parts.append(f'<p class="ok">{esc(n)}</p>')
    reason = ctx.config_block_reason()
    if reason:
        parts.append(f'<section class="warn">{esc(reason)}</section>')
        return _page("config.toml", "".join(parts), nav=_nav(ctx, csrf, "config"))
    if text is None:
        try:
            text = read_config_text(ctx)
        except (OSError, UnicodeDecodeError) as exc:
            parts.append(f'<section class="error bad">Cannot read the config file: '
                         f'{esc(getattr(exc, "strerror", None) or exc)}</section>')
            return _page("config.toml", "".join(parts), nav=_nav(ctx, csrf, "config"))
        digest = text_hash(text)
    exists = ctx.config_path.exists()
    parts.append(f'<p class="muted">File <code>{esc(ctx.config_path)}</code>'
                 + ("" if exists else " (does not exist yet; saving creates it)")
                 + '. Saved exactly as written, comments included; the '
                 '<a href="/targets">Targets</a> and <a href="/settings">Settings</a> forms '
                 "rewrite the file and drop comments. The file is checked like at startup "
                 "and nothing is written if it is invalid.</p>"
                 '<p class="muted">Rules for the web page: "output" and "printer" cannot be '
                 "changed here. A target folder must be a relative path inside the output "
                 f"directory <code>{esc(ctx.output)}</code>; a target with an absolute path or "
                 '".." can only stay as it is in the file. Changes apply within a poll '
                 "cycle, except the [web] table, which needs a restart. The size limit is "
                 f"{MAX_BODY // 1024} KB. Press Escape, then Tab, to leave the text field "
                 "with the keyboard.</p>")
    dirty_attr = ' data-dirty="1"' if dirty else ""
    parts.append(
        f'<form id="config-form" method="post" action="/config" data-warn-unsaved{dirty_attr}>'
        f'<input type="hidden" name="csrf" value="{esc(csrf)}">'
        f'<input type="hidden" name="hash" value="{esc(digest)}">'
        '<label for="config-text" class="sr-only">config.toml</label>'
        # the HTML parser drops one newline right after <textarea>, so add one
        f'<textarea id="config-text" name="text" rows="30" spellcheck="false" wrap="off" '
        f'autocapitalize="off" autocomplete="off" data-tab-indent>\n{esc(text)}</textarea>'
        '<p class="save"><button type="submit">Save</button>'
        '<span id="unsaved" class="badge" hidden>Unsaved changes</span></p></form>')
    return _page("config.toml", "".join(parts), nav=_nav(ctx, csrf, "config"), script=True)


# Host names accepted without a login (PUSHSCAN_WEB_AUTH=0). A public name
# would allow DNS rebinding: a foreign site whose name later points to this
# host is "same origin" for the browser and could read and post the forms.
LOCAL_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".internal", ".fritz.box")


def local_host(host: str | None) -> bool:
    """True for an IP address, localhost, a name without dots or a local suffix."""
    if not host:
        return False
    host = host.strip().lower()
    if host.startswith("["):                       # [IPv6]:port
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    host = host.rstrip(".")
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    return host == "localhost" or "." not in host or host.endswith(LOCAL_SUFFIXES)


# --- HTTP ------------------------------------------------------------------------

def _printable(text: str) -> str:
    """Escape control characters (e.g. CR/LF in a request line) for the log."""
    return "".join(c if c.isprintable() else f"\\x{ord(c):02x}" for c in text)


class WebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, ctx: WebContext, password: str | None,
                 secure_cookie: bool = False):
        super().__init__(address, Handler)
        self.ctx = ctx
        # password None: no login. Every client then shares one CSRF token that
        # exists only in this process; the Origin checks stay as they are.
        ctx.auth = password is not None
        self.password_digest = _digest(password) if password is not None else None
        self.open_csrf = secrets.token_urlsafe(32)
        self.sessions = Sessions()
        self.save_lock = threading.Lock()
        self.search_lock = threading.Lock()   # one network search at a time
        self.secure_cookie = secure_cookie
        self.cookie_name = SECURE_COOKIE if secure_cookie else COOKIE
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def cookie(self, value: str, max_age: int) -> str:
        return (f"{self.cookie_name}={value}; Max-Age={max_age}; HttpOnly; SameSite=Strict; "
                f"Path=/{'; Secure' if self.secure_cookie else ''}")

    # Bound the number of handler threads; extra connections are closed.
    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            log.debug("web: too many connections, dropping %s", client_address[0])
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def handle_error(self, request, client_address):
        """Log instead of printing to stderr; dropped connections are normal."""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError)):
            log.debug("web: connection from %s ended: %s", client_address[0], exc)
            return
        log.error("web: error while handling a request from %s", client_address[0],
                  exc_info=True)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class Handler(BaseHTTPRequestHandler):
    server: WebServer
    server_version = "pushscan2folder"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_TIMEOUT   # socket timeout per read: slow clients are dropped

    def log_message(self, fmt, *args):  # never log bodies; request lines only at DEBUG
        log.debug("web %s - %s", self.address_string(), _printable(fmt % args))

    def end_headers(self):
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        super().end_headers()

    # -- helpers
    def _send(self, status: int, body: bytes, ctype: str = "text/html; charset=utf-8",
              headers: dict | None = None, close: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if close or self.close_connection:
            self.send_header("Connection", "close")
            self.close_connection = True
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _redirect(self, location: str, headers: dict | None = None) -> None:
        self._send(303, b"", headers={"Location": location, **(headers or {})})

    def _text_error(self, status: int, message: str, close: bool = False) -> None:
        body = _page("Error", f"<h1>{status}</h1><p>{esc(message)}</p>"
                              '<p><a href="/">Back</a></p>')
        self._send(status, body, close=close)

    def _token(self) -> str | None:
        for part in self.headers.get("Cookie", "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == self.server.cookie_name:
                return value
        return None

    def _csrf(self) -> str | None:
        """CSRF token of this request's session; without login the one of the process."""
        if not self.server.ctx.auth:
            return self.server.open_csrf
        return self.server.sessions.lookup(self._token())

    def _path(self) -> str:
        return urlsplit(self.path).path

    def _content_length(self) -> int | None:
        """Body length of this request; None after an error response was sent.
        Ambiguous framing (Transfer-Encoding, several or non-numeric
        Content-Length headers) is refused and the connection closed, so no
        unread bytes can be taken as the next request (request smuggling)."""
        if self.headers.get("Transfer-Encoding") is not None:
            self._text_error(400, "Transfer-Encoding is not supported", close=True)
            return None
        values = self.headers.get_all("Content-Length") or []
        if len(values) > 1:
            self._text_error(400, "Several Content-Length headers", close=True)
            return None
        if not values:
            return 0
        text = values[0].strip()
        if not (text.isascii() and text.isdigit()):
            self._text_error(400, "Invalid Content-Length", close=True)
            return None
        return int(text)

    # -- GET
    def do_GET(self):
        if self.headers.get("Transfer-Encoding") is not None or \
                self.headers.get("Content-Length", "0").strip() not in ("", "0"):
            self.close_connection = True   # a body we do not read: end after this answer
        path = self._path()
        if not self._host_ok():
            return
        if path == "/style.css":
            return self._send(200, CSS.encode(), "text/css; charset=utf-8")
        if path == "/favicon.svg":
            return self._send(200, FAVICON, "image/svg+xml")
        if path == "/app.js":
            return self._send(200, APP_JS.encode(), "text/javascript; charset=utf-8")
        csrf = self._csrf()
        if path == "/login":
            if csrf:
                return self._redirect("/")
            return self._send(200, render_login())
        if csrf is None:
            return self._redirect("/login")
        ctx = self.server.ctx
        if path == "/":
            return self._send(200, render_status(ctx, csrf))
        if path == "/log":
            return self._send(200, render_log(ctx, csrf))
        if path == "/targets":
            return self._send(200, render_targets(ctx, csrf))
        saved = "1" in parse_qs(urlsplit(self.path).query).get("saved", [])
        if path == "/settings":
            notes = ["Saved. The new values are used from the next poll cycle."] if saved else []
            if "1" in parse_qs(urlsplit(self.path).query).get("printer", []):
                notes = [f"Saved. The printer {ctx.printer_pending or ctx.printer} is used from "
                         "the next poll cycle."]
            return self._send(200, render_settings(ctx, csrf, notes=notes))
        if path == "/config":
            notes = (["Saved. The changes are used from the next poll cycle; changes to "
                      "[web] need a restart."] if saved else [])
            return self._send(200, render_config(ctx, csrf, notes=notes))
        self._text_error(404, "Not found")

    # -- POST
    def _read_form(self) -> dict[str, str] | None:
        """Parsed form body, or None after an error response was sent."""
        if "Content-Length" not in self.headers:
            self._text_error(411, "Content-Length required", close=True)
            return None
        length = self._content_length()
        if length is None:
            return None
        if length > MAX_BODY:
            # Drain a bounded amount so the client can read our answer.
            remaining = min(length, 4 * MAX_BODY)
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 16384))
                if not chunk:
                    break
                remaining -= len(chunk)
            self._text_error(413, "Request body too large", close=True)
            return None
        raw = self.rfile.read(length)
        if len(raw) != length:
            self.close_connection = True
            return None
        try:
            parsed = parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True,
                              max_num_fields=2000)
        except ValueError:
            self._text_error(400, "Too many form fields", close=True)
            return None
        return {k: v[0] for k, v in parsed.items()}

    def _origin_ok(self) -> bool:
        """Cross-site POSTs are refused. Browsers send Origin on POST; without
        it (old browsers, curl) SameSite=Strict and the CSRF token still
        protect. "null" (sandboxed frames, file: pages, some redirects) is
        never same-origin."""
        fetch_site = self.headers.get("Sec-Fetch-Site", "").strip().lower()
        if fetch_site == "cross-site":
            return False
        if fetch_site == "same-origin":   # set by the browser, pages cannot forge it
            return True
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        origin = origin.strip()
        if origin == "null":
            return False
        host = self.headers.get("Host")
        return host is not None and urlsplit(origin).netloc == host.strip()

    def _host_ok(self) -> bool:
        """Without a login only local host names are served (DNS rebinding)."""
        if self.server.ctx.auth or local_host(self.headers.get("Host")):
            return True
        self._text_error(403, "Without a password the web page answers only to an IP "
                              "address or a local host name", close=True)
        return False

    def do_POST(self):
        if not self._host_ok():
            return
        path = self._path()
        form = self._read_form()
        if form is None:
            return
        if not self._origin_ok():
            return self._text_error(403, "Origin does not match Host")
        sessions = self.server.sessions
        if not self.server.ctx.auth and path in ("/login", "/logout"):
            return self._redirect("/")
        if path == "/login":
            return self._login(form)
        token = self._token()
        csrf = self._csrf()
        if csrf is None:
            return self._redirect("/login")
        if not hmac.compare_digest(form.get("csrf", "").encode(), csrf.encode()):
            return self._text_error(403, "Missing or wrong CSRF token")
        if path == "/logout":
            sessions.delete(token)
            return self._redirect("/login", {"Set-Cookie": self.server.cookie("", 0)})
        if path == "/targets":
            return self._save_targets(form, csrf)
        if path == "/settings":
            return self._save_settings(form, csrf)
        if path == "/config":
            return self._save_config(form, csrf)
        if path == "/printer/search":
            return self._search_printer(csrf)
        if path == "/printer/use":
            return self._use_printer(form, csrf)
        self._text_error(404, "Not found")

    def _login(self, form: dict) -> None:
        sessions = self.server.sessions
        supplied = _digest(form.get("password", ""))
        client = self.client_address[0]
        try:
            token = sessions.login(
                lambda: hmac.compare_digest(supplied, self.server.password_digest))
        except PermissionError:
            log.warning("web login from %s refused, locked after too many failures", client)
            return self._send(429, render_login("Too many attempts, wait a while and try again."))
        if token is None:
            log.warning("web login failed from %s", client)
            return self._send(401, render_login("Wrong password."))
        sessions.delete(self._token())   # a cookie sent along is replaced, never reused
        log.info("web login from %s", client)
        self._redirect("/", {"Set-Cookie": self.server.cookie(token, SESSION_MAX_SECONDS)})

    def _save_targets(self, form: dict, csrf: str) -> None:
        ctx = self.server.ctx
        reason = ctx.edit_block_reason()
        if reason:
            return self._send(403, render_targets(ctx, csrf, errors=[reason]))
        rows = rows_from_form(form)
        op = form.get("op", "save")   # no op: plain save (older clients)
        if op != "save":
            return self._edit_rows(rows, op, csrf)
        try:
            with self.server.save_lock:
                specs, errors = apply_targets(ctx, rows)
            if not errors:
                log.info("targets saved from the web page: %s", ", ".join(s.name for s in specs))
                return self._redirect("/")
        except ConfigError as exc:
            errors = [str(exc)]
        except OSError as exc:
            errors = [f"Cannot write {ctx.config_path}: {exc.strerror or exc}"]
        self._send(400, render_targets(ctx, csrf, rows=rows, errors=errors, dirty=True))

    def _save_settings(self, form: dict, csrf: str) -> None:
        ctx = self.server.ctx
        reason = ctx.config_block_reason()
        if reason:
            return self._send(403, render_settings(ctx, csrf, errors=[reason]))
        values = settings_from_form(form)
        try:
            with self.server.save_lock:
                errors = apply_settings(ctx, values)
            if not errors:
                log.info("settings saved from the web page")
                return self._redirect("/settings?saved=1")
        except ConfigError as exc:
            errors = [str(exc)]
        except OSError as exc:
            errors = [f"Cannot write {ctx.config_path}: {exc.strerror or exc}"]
        self._send(400, render_settings(ctx, csrf, values=values, errors=errors, dirty=True))

    def _search_printer(self, csrf: str) -> None:
        ctx = self.server.ctx
        if ctx.discover_fn is None or "printer" in ctx.overrides:
            return self._text_error(404, "Not found")
        if not self.server.search_lock.acquire(blocking=False):
            return self._send(409, render_settings(ctx, csrf,
                                                   errors=["A search is already running."]))
        try:
            found = list(ctx.discover_fn())
        finally:
            self.server.search_lock.release()
        ctx.found = found
        log.info("printer search from the web page: %d scanner(s) found", len(found))
        self._send(200, render_settings(ctx, csrf, scanners=found))

    def _use_printer(self, form: dict, csrf: str) -> None:
        ctx = self.server.ctx
        if ctx.discover_fn is None or "printer" in ctx.overrides:
            return self._text_error(404, "Not found")
        reason = ctx.config_block_reason()
        if reason:
            return self._send(403, render_settings(ctx, csrf, errors=[reason]))
        address = form.get("address", "").strip()
        if address not in {scanner.address for scanner in ctx.found}:
            return self._send(400, render_settings(
                ctx, csrf, errors=["Only an address found by the search can be used. "
                                   "Search again."]))
        try:
            with self.server.save_lock:
                set_printer(ctx, address)
        except ConfigError as exc:
            return self._send(400, render_settings(ctx, csrf, errors=[str(exc)]))
        except OSError as exc:
            return self._send(400, render_settings(
                ctx, csrf, errors=[f"Cannot write {ctx.config_path}: {exc.strerror or exc}"]))
        ctx.printer_pending = address
        log.info("printer set to %s from the web page", address)
        self._redirect("/settings?saved=1&printer=1")

    def _save_config(self, form: dict, csrf: str) -> None:
        ctx = self.server.ctx
        reason = ctx.config_block_reason()
        if reason:
            return self._send(403, render_config(ctx, csrf, errors=[reason]))
        text, digest = form.get("text", ""), form.get("hash", "")
        try:
            with self.server.save_lock:
                errors, current = apply_raw_config(ctx, text, digest)
            if current is not None:
                return self._send(409, render_config(
                    ctx, csrf, text=current, digest=text_hash(current),
                    errors=["The file changed on disk since you opened this page. Nothing "
                            "was saved. The current content is shown; apply your edit "
                            "to it again."]))
            if not errors:
                log.info("config file saved from the web page")
                return self._redirect("/config?saved=1")
        except (OSError, UnicodeDecodeError) as exc:
            errors = [f"Cannot access {ctx.config_path}: "
                      f"{getattr(exc, 'strerror', None) or exc}"]
        self._send(400, render_config(ctx, csrf, text=text, digest=digest, errors=errors,
                                      dirty=True))

    def _edit_rows(self, rows: list[Row], op: str, csrf: str) -> None:
        """add / up_N / down_N / remove_N: change the rows in memory and show the form
        again. Nothing is written."""
        ctx = self.server.ctx
        match = re.fullmatch(r"(up|down|remove)_(\d{1,3})", op)
        if op == "add":
            if len(rows) >= MAX_ROWS:
                return self._send(400, render_targets(
                    ctx, csrf, rows=rows, dirty=True,
                    errors=[f"At most {MAX_ROWS} targets are possible."]))
            rows.append(blank_row(ctx.multipage_mode))
        elif match:
            kind, i = match.group(1), int(match.group(2))
            if i >= len(rows):
                return self._text_error(400, "Row out of range")
            if kind == "remove":
                if rows[i].existing:
                    return self._text_error(400, "Only new rows can be removed")
                del rows[i]
            else:
                j = i - 1 if kind == "up" else i + 1
                if not 0 <= j < len(rows):
                    return self._text_error(400, "Row cannot move there")
                rows[i], rows[j] = rows[j], rows[i]
        else:
            return self._text_error(400, "Unknown operation")
        self._send(200, render_targets(ctx, csrf, rows=rows, dirty=True,
                                       notes=["Changes are not saved yet."]))


def start_server(ctx: WebContext, password: str | None, bind: str, port: int,
                 secure_cookie: bool = False):
    """Start the web server in a daemon thread. Returns (server, thread);
    server.server_address holds the real port. secure_cookie: mark the
    session cookie Secure (__Host- prefix), only for use behind a TLS
    reverse proxy. password None: no login at all (PUSHSCAN_WEB_AUTH=0).
    Raises OSError (e.g. port in use)."""
    server = WebServer((bind, port), ctx, password, secure_cookie=secure_cookie)
    thread = threading.Thread(target=server.serve_forever, name="web", daemon=True)
    thread.start()
    return server, thread


def stop_server(server: WebServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
