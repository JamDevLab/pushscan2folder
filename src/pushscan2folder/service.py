"""Push-scan service: keep one or more targets registered, poll and scan.

Platen scans whose panel document type is in `multipage` (default:
"document") use Canon's native protocol, which lets the panel ask for further
pages (multi-page PDF). Everything else uses eSCL."""
from __future__ import annotations

import logging
import os
import re
import secrets
import string
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import crop, desktop, panel
from .client import ChmpClient
from .escl import EXTENSIONS, FORMATS, EsclClient, ScanSettings
from .native import NativeScanner, PageSettings
from .pdf import jpegs_to_pdf
from .platform_support import is_reserved_name
from .status import ScanRecord, ServiceStatus
from .protocol import STATUS_OK, STATUS_SCAN_REQUESTED, VISIBLE_NAME_CHARS, check_name

log = logging.getLogger(__name__)

MAX_BACKOFF = 10.0
# Keep registrations alive while a long scan runs (the printer drops them
# after about 60 s without a poll).
KEEPALIVE_INTERVAL = 5.0
# How often the poll loop looks for a stop request while it waits.
STOP_CHECK_INTERVAL = 1.0


TRIM_MAX_MM = 50.0
MIN_TRIMMED = 300  # 1 inch in 1/300 inch: a smaller remaining area skips trimming


@dataclass(frozen=True)
class Trim:
    """Border to cut off by scanning a smaller area, in mm per side."""
    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0

    def __post_init__(self):
        for side in ("left", "top", "right", "bottom"):
            value = getattr(self, side)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not 0 <= value <= TRIM_MAX_MM):
                raise ValueError(f"trim {side} must be a number from 0 to "
                                 f"{TRIM_MAX_MM:g} mm, got {value!r}")

    def __bool__(self) -> bool:
        return any((self.left, self.top, self.right, self.bottom))

    def units(self) -> tuple[int, int, int, int]:
        """(left, top, right, bottom) in 1/300 inch."""
        return tuple(round(mm * 300 / 25.4)
                     for mm in (self.left, self.top, self.right, self.bottom))


def parse_trim(text: str | None) -> Trim:
    """Parse "right=1,bottom=2" (keys left/top/right/bottom, mm, any subset).
    Empty means no trim. Raises ValueError."""
    values: dict[str, float] = {}
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        key, sep, raw = part.partition("=")
        key = key.strip().lower()
        if not sep or key not in ("left", "top", "right", "bottom"):
            raise ValueError(f"invalid trim entry {part!r}: use left/top/right/bottom=MM, "
                             f"e.g. right=1,bottom=2")
        if key in values:
            raise ValueError(f"trim side {key!r} given twice")
        try:
            values[key] = float(raw)
        except ValueError:
            raise ValueError(f"trim {key}: {raw.strip()!r} is not a number") from None
        if not values[key] == values[key] or values[key] in (float("inf"), float("-inf")):
            raise ValueError(f"trim {key}: {raw.strip()!r} is not a finite number")
    return Trim(**values)


DEFAULT_FILENAME = "scan_{now:%Y%m%d_%H%M%S}"
MAX_FILENAME_CHARS = 120
_FILENAME_FIELDS = ("name", "date", "time", "now")


class _FilenameFormatter(string.Formatter):
    """str.format with only the plain fields of _FILENAME_FIELDS: no attribute
    or index access ({now.__class__}) and no positional fields."""

    def get_field(self, field_name, args, kwargs):
        if field_name not in _FILENAME_FIELDS:
            raise ValueError(f"unknown field {{{field_name}}}: use "
                             + ", ".join("{" + f + "}" for f in _FILENAME_FIELDS))
        return kwargs[field_name], field_name


def render_filename(template: str, name: str, now: datetime) -> str:
    """The file name (without extension) for a scan of target `name` at `now`.
    Fields: {name} (panel name as a safe file name), {date} (2026-11-22),
    {time} (183000), {now:FORMAT} (strftime codes, e.g. {now:%Y%m%d_%H%M%S}).
    Characters that are not allowed in a Windows file name become "_".
    Raises ValueError for a template that cannot be used."""
    try:
        text = _FilenameFormatter().format(
            template, name=safe_dirname(name), date=now.strftime("%Y-%m-%d"),
            time=now.strftime("%H%M%S"), now=now)
    except (ValueError, IndexError, KeyError) as exc:
        raise ValueError(f"file name {template!r}: {exc}") from None
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", text).strip(" .")
    if is_reserved_name(text):
        text = "_" + text
    if not text:
        raise ValueError(f"file name {template!r} gives an empty name")
    return text[:MAX_FILENAME_CHARS]


def check_filename(template: str) -> None:
    """Raise ValueError if `template` cannot be used as a file name template."""
    render_filename(template, "scan", datetime(2026, 1, 2, 3, 4, 5))


class _FolderFormatter(_FilenameFormatter):
    """Like file names, but every field value becomes one safe path part:
    no separator, no "." or "..", so a field can never change which folders
    a path goes through ({now:../x} gives "_x")."""

    def format_field(self, value, format_spec):
        text = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_",
                      super().format_field(value, format_spec)).strip(" .")
        return text or "_"


def render_folder(path: Path | str, name: str, now: datetime) -> Path:
    """The folder of a scan: `path` with the fields of render_filename
    filled in ({name}, {date}, {time}, {now:FORMAT}). A path without
    braces is returned unchanged. Raises ValueError."""
    text = str(path)
    if "{" not in text and "}" not in text:
        return Path(path)
    try:
        return Path(_FolderFormatter().format(
            text, name=safe_dirname(name), date=now.strftime("%Y-%m-%d"),
            time=now.strftime("%H%M%S"), now=now))
    except (ValueError, IndexError, KeyError) as exc:
        raise ValueError(f"folder {text!r}: {exc}") from None


def check_folder(path: str) -> None:
    """Raise ValueError if the fields in folder `path` cannot be used."""
    render_folder(path, "scan", datetime(2026, 1, 2, 3, 4, 5))


def _publish(tmp: Path, final: Path) -> None:
    """Give the finished temp file its final name. Raises FileExistsError if
    the name is taken (a dangling symlink counts), so nothing is replaced or
    followed. A rename, not a hard link: folder watchers such as the
    Paperless consumer react to "moved to" or "closed after writing", and a
    new hard link is neither."""
    if os.path.lexists(final):
        raise FileExistsError(final)
    os.rename(tmp, final)   # same folder; on Windows it never overwrites


def save_files(directory: Path, files: list[tuple[bytes, str]], now: datetime,
               template: str = DEFAULT_FILENAME, name: str = "scan") -> list[Path]:
    """Write (data, fmt) pairs as TEMPLATE[_NN].ext (default
    scan_YYYYmmdd_HHMMSS), never overwriting existing files: a "-1", "-2" ...
    is added instead. Each file goes to a hidden temp file first, so a folder
    watcher never sees a half-written file, and is published without
    replacing or following anything that exists."""
    stem = render_filename(template, name, now)
    paths = []
    for i, (data, fmt) in enumerate(files):
        ext = EXTENSIONS[FORMATS[fmt]]
        base = stem if len(files) == 1 else f"{stem}_{i + 1:02d}"
        tmp = directory / f".{secrets.token_hex(8)}.part"
        # 0o666 and the umask, like a plain write (mkstemp would make it 0600
        # and a folder watcher running as another user could not read it).
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                     0o666)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            n = 0
            while True:
                path = directory / (f"{base}.{ext}" if n == 0 else f"{base}-{n}.{ext}")
                try:
                    _publish(tmp, path)
                    break
                except FileExistsError:
                    n += 1
            paths.append(path)
        finally:
            tmp.unlink(missing_ok=True)
    return paths


def is_complete(data: bytes, fmt: str) -> bool:
    """True if a document was transferred completely (not cut off by a cancel)."""
    tail = data[-1024:].rstrip(b"\r\n\0 ")
    if fmt == "pdf":
        return data.startswith(b"%PDF") and tail.endswith(b"%%EOF")
    if fmt == "jpeg":
        return data.startswith(b"\xff\xd8") and tail.endswith(b"\xff\xd9")
    return bool(data)


def safe_dirname(name: str) -> str:
    """Folder name derived from a panel name: no path separators or odd characters,
    and a valid Windows name (no reserved device names, no trailing dot)."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip()).strip("._")
    if is_reserved_name(cleaned):
        cleaned = "_" + cleaned   # CON, aux, NUL.x ... are device names on Windows
    return cleaned or "scan"


# Panel document types, and those that get the "next page" dialog on platen
# scans unless the config says otherwise.
DOC_TYPES = ("document", "auto", "photo")
DEFAULT_NEXT_PAGE = frozenset({"document"})

RESOLUTIONS = (75, 150, 300, 600)


@dataclass
class Target:
    """One entry on the printer panel and the folder its scans go to.

    outdir: the folder; may contain the fields of render_folder.
    type_dirs: another folder for some panel document types
    ("document", "auto", "photo"), same rules as outdir.
    preset: ScanSettings fields set for this target (resolution, fmt, width,
    height). They replace the global fallback, and with document type
    "auto scan" they also win over the panel.
    multipage: document types with the next page dialog; None = global setting.
    """
    name: str
    outdir: Path
    session: int | None = None
    preset: dict = field(default_factory=dict)
    multipage: frozenset[str] | None = None
    type_dirs: dict[str, Path] = field(default_factory=dict)
    filename: str | None = None  # file name template; None = the global one
    open_after_scan: bool | None = None   # None = the global one


def check_targets(targets: list[Target]) -> list[str]:
    """Final checks over all targets. Raises ValueError for clashing output
    folders; returns warnings (e.g. names the panel shortens)."""
    warnings = []
    folders: dict[Path, str] = {}
    for t in targets:
        # Compared as written: two templates that render alike are not found.
        key = t.outdir.resolve()
        if key in folders:
            raise ValueError(f"targets {folders[key]!r} and {t.name!r} both use the folder "
                             f"{t.outdir}; give one of them its own folder")
        folders[key] = t.name
        if len(t.name) > VISIBLE_NAME_CHARS:
            warnings.append(f"target name {t.name!r} is longer than {VISIBLE_NAME_CHARS} "
                            f"characters; the panel shows only the start")
    return warnings


class PushScanService:
    def __init__(self, chmp: ChmpClient, escl: EsclClient, targets: list[Target],
                 settings: ScanSettings, interval: float = 4.0, auto_source: bool = True,
                 use_panel: bool = True, native: NativeScanner | None = None,
                 multipage: frozenset[str] = DEFAULT_NEXT_PAGE,
                 trim: Trim | None = None, open_after_scan: bool = False,
                 filename: str = DEFAULT_FILENAME, adf_trim: Trim | None = None):
        self.trim = trim or Trim()
        self.adf_trim = adf_trim or Trim()
        self.filename = filename
        # Optional file touched after every successful contact with the
        # printer (`pushscan2folder health`, the Docker healthcheck).
        self.heartbeat: Path | None = None
        self.open_after_scan = open_after_scan
        # Optional callable: True asks the loop to stop (background `stop`).
        self.stop_check: Callable[[], bool] | None = None
        # Optional callable, called with True when a scan starts and False when
        # it ends (the background instance marks itself busy for `stop`).
        self.busy_hook: Callable[[bool], None] | None = None
        # Optional callable run by the poll loop before each cycle, never during
        # a scan (the config file watcher uses it to apply a changed file).
        self.before_step: Callable[[], None] | None = None
        self.use_panel = use_panel
        self.native = native
        self.multipage = multipage
        self._last_keepalive = 0.0
        self.chmp = chmp
        self.escl = escl
        self.targets = targets
        self.settings = settings
        self.interval = interval
        self.auto_source = auto_source
        self.stop_event = threading.Event()
        self.status = ServiceStatus()
        self.status.set_targets(targets)
        self._pending_lock = threading.Lock()
        self._pending: list[Target] | None = None
        self._pages = 0  # pages of the scan in progress, for the status record

    def request_targets(self, targets: list[Target]) -> None:
        """Replace the targets (thread safe, e.g. from the web page). They are
        applied by the poll loop before its next cycle, never during a scan.
        The caller must have validated them (parse/build + check_targets)."""
        with self._pending_lock:
            self._pending = list(targets)
        self.status.set_pending(True)

    def apply_pending_targets(self) -> None:
        """Called from the poll loop: switch to requested targets. The panel
        lists names in registration order. Sessions of unchanged names are
        kept only if that order stays right: the kept names in their old
        order, followed by new names. Otherwise (reordered, or a new name
        inserted in the middle) all targets are released and registered
        again in the new order. Removed names are released right away."""
        with self._pending_lock:
            new, self._pending = self._pending, None
        if new is None:
            return
        old = {t.name: t for t in self.targets}
        new_names = [t.name for t in new]
        kept = [t.name for t in self.targets if t.name in set(new_names)]
        order_ok = new_names[:len(kept)] == kept and not any(n in old for n in new_names[len(kept):])
        if not order_ok and any(t.session is not None for t in self.targets):
            log.info("target order changed, registering all targets again")
        for target in self.targets:
            if target.session is None:
                continue
            if order_ok and target.name in set(new_names):
                continue
            try:
                self.chmp.release(target.session)
                log.info("released %r (%s)", target.name,
                         "removed" if target.name not in new_names else "new order")
            except Exception as exc:
                log.warning("release of %r failed: %s", target.name, exc)
        if order_ok:
            for target in new:
                if target.name in old:
                    target.session = old[target.name].session
        self.targets = new
        self.status.set_targets(self.targets)
        self.status.set_pending(False)
        log.info("targets updated: %s", ", ".join(new_names) or "none")

    OPTIONS = ("settings", "interval", "auto_source", "use_panel", "multipage", "trim",
               "adf_trim", "open_after_scan", "filename")

    def update_options(self, **options) -> None:
        """Change scan options (names in OPTIONS). Call it from the poll loop
        (before_step), so a running scan never sees a mix of old and new."""
        for key, value in options.items():
            if key not in self.OPTIONS:
                raise TypeError(f"unknown option {key!r}")
            setattr(self, key, value)

    def change_printer(self, chmp: ChmpClient, escl: EsclClient,
                       native: NativeScanner | None) -> None:
        """Switch to another printer (from the poll loop). The names on the old
        one are released (best effort, it may be gone); step() registers them
        on the new one."""
        self.release()
        self.chmp, self.escl, self.native = chmp, escl, native
        self._last_keepalive = 0.0

    def register(self, target: Target) -> None:
        target.session = self.chmp.register(target.name).session
        log.info("%r is now on the printer panel under Scan to PC", target.name)
        log.debug("session of %r: 0x%x", target.name, target.session)

    def release(self) -> None:
        for target in self.targets:
            if target.session is None:
                continue
            try:
                self.chmp.release(target.session)
                log.info("released %r (session 0x%x)", target.name, target.session)
            except Exception as exc:  # best effort on shutdown
                log.warning("release of %r failed: %s", target.name, exc)
            target.session = None

    def settings_for(self, interrupt: bytes, target: Target | None = None) -> ScanSettings:
        """Scan settings for one request.

        Order: panel values, then the target preset, then the global defaults.
        With document type "auto scan" the target preset wins over the panel,
        except for the colour: presets have none, the panel colour (the start
        button that was pressed) always wins.
        """
        preset = target.preset if target else {}
        settings = replace(self.settings, **preset)
        panel_source = None
        if self.use_panel and interrupt:
            p = panel.decode(interrupt)
            log.info("panel settings: %s", p.describe())
            unknown = panel.unknown_values(interrupt)
            if unknown:
                log.warning("unknown panel value(s): %s; please report them together "
                            "with the 'scan requested' line above", ", ".join(unknown))
            settings = panel.apply(p, settings)
            if p.doc_type == "auto" and preset:
                settings = replace(settings, **preset)
            panel_source = p.source
        if self.auto_source and panel_source is None:
            try:
                source = "adf" if self.escl.adf_loaded() else "platen"
            except Exception as exc:
                log.warning("could not read ADF state (%s), using platen", exc)
                source = "platen"
            settings = replace(settings, source=source)
        return self.apply_trim(settings)

    def apply_trim(self, settings: ScanSettings) -> ScanSettings:
        """Shrink the scan region by the configured trim: `trim` for the
        platen, `adf_trim` for the document feeder. Skipped (with a warning)
        if less than 1 inch would remain in either direction."""
        trim = self.adf_trim if settings.source == "adf" else self.trim
        if not trim or settings.source not in ("platen", "adf"):
            return settings
        what = "feeder" if settings.source == "adf" else "glass"
        left, top, right, bottom = trim.units()
        width = settings.width - left - right
        height = settings.height - top - bottom
        if width < MIN_TRIMMED or height < MIN_TRIMMED:
            log.warning("%s trim too large for the scan area (%dx%d, 1/300 inch left), "
                        "scanning without trim", what, width, height)
            return settings
        log.debug("%s trim left=%s top=%s right=%s bottom=%s mm: offset %d,%d size %dx%d",
                  what, trim.left, trim.top, trim.right, trim.bottom,
                  settings.x_offset + left, settings.y_offset + top, width, height)
        return replace(settings, x_offset=settings.x_offset + left,
                       y_offset=settings.y_offset + top, width=width, height=height)

    def use_native(self, settings: ScanSettings, interrupt: bytes,
                   target: Target | None = None) -> bool:
        """Multi-page platen scan for the configured panel document types. The
        official software offers further pages only for "document"."""
        if self.native is None or settings.source != "platen" or not interrupt:
            return False
        modes = self.multipage if target is None or target.multipage is None else target.multipage
        if not self.use_panel:
            return False
        p = panel.decode(interrupt)
        if p.doc_type == "photo" and p.size in panel.AUTO_SIZES:
            # The whole glass is scanned and the photos are cut out (eSCL).
            return False
        return p.doc_type in modes

    def cut_mode(self, settings: ScanSettings, interrupt: bytes) -> str | None:
        """"single" or "multi" when the photos are to be cut out of the scan:
        panel size auto scan or auto multi scan on the glass, Pillow installed."""
        if not (self.use_panel and interrupt) or settings.source != "platen":
            return None
        size = panel.decode(interrupt).size
        if size not in panel.AUTO_SIZES:
            return None
        if not crop.available():
            log.info("install Pillow to cut the photos out of the scan; saving the "
                     "whole glass")
            return None
        return "multi" if size == "auto-multi" else "single"

    def keepalive(self) -> None:
        """Poll all targets during a scan so the printer keeps them registered."""
        now = time.monotonic()
        if now - self._last_keepalive < KEEPALIVE_INTERVAL:
            return
        self._last_keepalive = now
        for target in self.targets:
            try:
                if target.session is None:
                    self.register(target)
                    continue
                resp = self.chmp.poll(target.session)
                self.beat()
                if resp.scan_requested:
                    log.warning("scan request for %r during a running scan ignored", target.name)
                elif resp.status != STATUS_OK:
                    self.register(target)
            except Exception as exc:
                log.debug("keepalive for %r failed: %s", target.name, exc)

    def scan_escl(self, settings: ScanSettings) -> list[bytes]:
        """eSCL blocks while the printer scans (about 50 s for a 600 dpi page),
        so keep the registrations alive from a helper thread meanwhile."""
        done = threading.Event()

        def keep():
            while not done.wait(KEEPALIVE_INTERVAL):
                self.keepalive()

        helper = threading.Thread(target=keep, name="keepalive", daemon=True)
        helper.start()
        try:
            return self.escl.scan(settings)
        finally:
            done.set()
            helper.join()

    def scan_native(self, settings: ScanSettings) -> list[bytes]:
        pages = self.native.scan(
            PageSettings(settings.color, settings.resolution, settings.width, settings.height,
                         settings.x_offset, settings.y_offset),
            multipage=True, keepalive=self.keepalive, should_stop=self.stop_wanted)
        complete = [p for p in pages if is_complete(p, "jpeg")]
        self._pages = len(complete)
        if len(complete) != len(pages):
            log.warning("discarded %d incomplete page(s)", len(pages) - len(complete))
        if not complete:
            return []
        if settings.fmt == "pdf":
            try:
                return [jpegs_to_pdf(complete, settings.resolution)]
            except ValueError as exc:
                log.warning("cannot build a PDF (%s), saving the pages as JPEG files", exc)
        return complete

    @staticmethod
    def _photo_pdf(photo: bytes, dpi: int) -> bytes:
        try:
            return jpegs_to_pdf([photo], dpi)
        except ValueError as exc:
            log.warning("cannot build a PDF (%s), saving the page as a JPEG file", exc)
            return photo

    def scan_to(self, target: Target, event: int = 0, interrupt: bytes = b"") -> list[Path]:
        """Scan for target and save the files; the result goes to self.status."""
        self.status.set_busy(target.name)
        if self.busy_hook is not None:
            self.busy_hook(True)
        self._pages = 0
        self._method = ""
        try:
            paths = self._scan_to(target, event, interrupt)
        except Exception as exc:
            self.status.record(ScanRecord(time.time(), target.name, self._method, self._pages,
                                          (), "error", str(exc)))
            raise
        finally:
            self.status.set_busy(None)
            if self.busy_hook is not None:
                self.busy_hook(False)
        self.status.record(ScanRecord(time.time(), target.name, self._method, self._pages,
                                      tuple(str(p) for p in paths),
                                      "ok" if paths else "nothing saved"))
        if paths:
            wanted = (self.open_after_scan if target.open_after_scan is None
                      else target.open_after_scan)  # False of a target wins, too
            desktop.open_saved(wanted, paths)  # once per job
        return paths

    def _scan_to(self, target: Target, event: int, interrupt: bytes) -> list[Path]:
        log.info("scan requested: event=0x%x interrupt=%s", event, interrupt.hex())
        now = datetime.now()
        doc_type = panel.decode(interrupt).doc_type if interrupt and self.use_panel else None
        outdir = render_folder(target.type_dirs.get(doc_type, target.outdir), target.name, now)
        settings = self.settings_for(interrupt, target)
        native = self.use_native(settings, interrupt, target)
        cut = None if native else self.cut_mode(settings, interrupt)
        saved_fmt = settings.fmt
        if cut:
            settings = replace(settings, fmt="jpeg")   # cut out on the JPEG, then convert
        log.info("scanning (%s): source=%s color=%s dpi=%d format=%s region=%dx%d",
                 "native, multi-page" if native else "eSCL",
                 settings.source, settings.color, settings.resolution, settings.fmt,
                 settings.width, settings.height)
        self._method = "native" if native else "eSCL"
        if native:
            complete = self.scan_native(settings)
        else:
            docs = self.scan_escl(settings)
            complete = [d for d in docs if is_complete(d, settings.fmt)]
            self._pages = len(complete)
            if len(complete) != len(docs):
                # Cancelling on the panel leaves a truncated document behind.
                log.warning("discarded %d incomplete document(s), scan was probably cancelled",
                            len(docs) - len(complete))
        if not complete:
            return []
        if cut:
            complete = [photo for page in complete
                        for photo in crop.cut_out(page, settings.resolution, cut == "multi")]
            if saved_fmt == "pdf":
                complete = [self._photo_pdf(photo, settings.resolution) for photo in complete]
            settings = replace(settings, fmt=saved_fmt)
        outdir.mkdir(parents=True, exist_ok=True)
        # A page that could not be made a PDF stays a JPEG (see _photo_pdf, scan_native).
        files = [(d, "jpeg" if settings.fmt == "pdf" and not d.startswith(b"%PDF")
                  else settings.fmt) for d in complete]
        paths = save_files(outdir, files, now,
                           target.filename or self.filename, target.name)
        for path in paths:
            log.info("saved %s", path)
        return paths

    def step(self) -> None:
        """One poll cycle over all targets. Raises on transport errors."""
        self.apply_pending_targets()
        for target in self.targets:
            if target.session is None:
                self.register(target)
            resp = self.chmp.poll(target.session)
            log.debug("poll %r status=0x%x raw=%s", target.name, resp.status, resp.raw.hex())
            if resp.status not in (STATUS_OK, STATUS_SCAN_REQUESTED):
                # 0x1: registration dropped by the printer. Anything else is
                # unknown; registering again is the safe reaction for both.
                log.warning("printer answered status 0x%x for %r, registering again",
                            resp.status, target.name)
                self.register(target)
                continue
            if resp.scan_requested:
                log.info("panel selected %r", target.name)
                try:
                    self.scan_to(target, resp.event, resp.interrupt)
                except Exception as exc:
                    log.error("scan for %r failed: %s", target.name, exc)
        self.status.set_targets(self.targets)

    def run(self) -> None:
        backoff = self.interval
        while not self.stop_event.is_set():
            if self.before_step is not None:
                try:
                    self.before_step()
                except Exception as exc:   # never let it end the service
                    log.warning("could not apply the changed config: %s", exc)
            try:
                self.step()
                backoff = self.interval
                self.status.poll_ok()
                self.beat()
            except Exception as exc:
                log.warning("printer not reachable (%s), retrying in %.0fs", exc, backoff)
                self.status.poll_failed(str(exc))
                for target in self.targets:
                    target.session = None
                # Short cap: after a printer restart the names should reappear quickly.
                backoff = min(backoff * 2, MAX_BACKOFF)
            self.status.set_targets(self.targets)
            self._wait(backoff)
        self.release()

    def beat(self) -> None:
        """Mark the printer as reachable just now (heartbeat file)."""
        if self.heartbeat is None:
            return
        try:
            self.heartbeat.write_text(f"{time.time():.0f}\n", encoding="ascii")
        except OSError as exc:
            log.debug("heartbeat file %s: %s", self.heartbeat, exc)

    def stop_wanted(self) -> bool:
        """True after stop() or a stop request (does not set the event)."""
        return self.stop_event.is_set() or (self.stop_check is not None and self.stop_check())

    def _wait(self, seconds: float) -> None:
        """Sleep between poll cycles, but end early on stop() or a stop request."""
        end = time.monotonic() + seconds
        while not self.stop_event.is_set():
            if self.stop_check is not None and self.stop_check():
                log.info("stop requested")
                self.stop_event.set()
                return
            left = end - time.monotonic()
            if left <= 0:
                return
            self.stop_event.wait(min(left, STOP_CHECK_INTERVAL))

    def stop(self) -> None:
        self.stop_event.set()
