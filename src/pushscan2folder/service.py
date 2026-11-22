"""Push-scan service: keep one or more targets registered, poll and scan.

Platen scans whose panel document type is in `multipage` (default:
"document") use Canon's native protocol, which lets the panel ask for further
pages (multi-page PDF). Everything else uses eSCL."""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from . import panel
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
    """Parse "right=3,bottom=2" (keys left/top/right/bottom, mm, any subset).
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
                             f"e.g. right=3,bottom=2")
        if key in values:
            raise ValueError(f"trim side {key!r} given twice")
        try:
            values[key] = float(raw)
        except ValueError:
            raise ValueError(f"trim {key}: {raw.strip()!r} is not a number") from None
        if not values[key] == values[key] or values[key] in (float("inf"), float("-inf")):
            raise ValueError(f"trim {key}: {raw.strip()!r} is not a finite number")
    return Trim(**values)


def output_names(directory: Path, fmt: str, count: int, now: datetime) -> list[Path]:
    """scan_YYYYmmdd_HHMMSS[_NN].ext, never overwriting existing files."""
    ext = EXTENSIONS[FORMATS[fmt]]
    stem = now.strftime("scan_%Y%m%d_%H%M%S")
    names = []
    for i in range(count):
        base = stem if count == 1 else f"{stem}_{i + 1:02d}"
        path = directory / f"{base}.{ext}"
        n = 1
        while path.exists() or path in names:
            path = directory / f"{base}-{n}.{ext}"
            n += 1
        names.append(path)
    return names


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


# Which panel document types get the "next page" dialog on platen scans.
MULTIPAGE_MODES = {
    "document": frozenset({"document"}),
    "auto": frozenset({"auto"}),
    "both": frozenset({"document", "auto"}),
    "off": frozenset(),
}

RESOLUTIONS = (75, 150, 300, 600)


@dataclass
class Target:
    """One entry on the printer panel and the folder its scans go to.

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


def parse_preset(text: str) -> tuple[dict, frozenset[str] | None]:
    """Parse "300dpi+jpeg+a4+mp:auto" into ScanSettings fields and a
    multi-page mode. Unknown tokens raise ValueError."""
    preset: dict = {}
    multipage = None
    for token in text.split("+"):
        tok = token.strip().lower()
        m = re.fullmatch(r"(\d+)dpi", tok)
        if m and int(m.group(1)) in RESOLUTIONS:
            preset["resolution"] = int(m.group(1))
        elif tok in ("pdf", "jpeg"):
            preset["fmt"] = tok
        elif tok in panel.REGIONS:
            preset["width"], preset["height"] = panel.REGIONS[tok]
        elif tok.startswith("mp:") and tok[3:] in MULTIPAGE_MODES:
            multipage = MULTIPAGE_MODES[tok[3:]]
        else:
            raise ValueError(
                f"unknown target option {token!r} (use e.g. 300dpi, pdf, "
                f"jpeg, a4, letter, legal, 10x15, 13x18, mp:document|auto|both|off; "
                f"dpi: {', '.join(map(str, RESOLUTIONS))})")
    return preset, multipage


def parse_targets(spec: str, base: Path) -> list[Target]:
    """Parse "scan1,paperless=/data/consume@300dpi+pdf,archiv@600dpi".

    Entries are separated by commas. "NAME" stores into base/NAME (sanitised),
    "NAME=DIR" stores into DIR (relative paths are resolved against base).
    An optional "@OPTION+OPTION..." suffix sets a preset (see parse_preset).
    """
    targets: list[Target] = []
    seen: set[str] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        preset, multipage = {}, None
        if "@" in part:
            part, _, options = part.rpartition("@")
            preset, multipage = parse_preset(options)
        name, sep, directory = part.partition("=")
        name = name.strip()
        if not name:
            raise ValueError(f"empty target name in {part!r}")
        check_name(name)
        if name in seen:
            raise ValueError(f"duplicate target name {name!r}")
        seen.add(name)
        outdir = base / (directory.strip() if sep and directory.strip() else safe_dirname(name))
        targets.append(Target(name, outdir, preset=preset, multipage=multipage))
    if not targets:
        raise ValueError("no targets given")
    return targets


def check_targets(targets: list[Target]) -> list[str]:
    """Final checks over all targets. Raises ValueError for clashing output
    folders; returns warnings (e.g. names the panel shortens)."""
    warnings = []
    folders: dict[Path, str] = {}
    for t in targets:
        key = t.outdir.resolve()
        if key in folders:
            raise ValueError(f"targets {folders[key]!r} and {t.name!r} both use the folder "
                             f"{t.outdir}; give one of them its own folder (NAME=DIR)")
        folders[key] = t.name
        if len(t.name) > VISIBLE_NAME_CHARS:
            warnings.append(f"target name {t.name!r} is longer than {VISIBLE_NAME_CHARS} "
                            f"characters; the panel shows only the start")
    return warnings


class PushScanService:
    def __init__(self, chmp: ChmpClient, escl: EsclClient, targets: list[Target],
                 settings: ScanSettings, interval: float = 4.0, auto_source: bool = True,
                 use_panel: bool = True, native: NativeScanner | None = None,
                 multipage: frozenset[str] = frozenset({"document"}),
                 trim: Trim | None = None):
        self.trim = trim or Trim()
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

    def register(self, target: Target) -> None:
        target.session = self.chmp.register(target.name).session
        log.info("registered %r, session 0x%x", target.name, target.session)

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
        """Shrink the scan region by the configured trim. Platen only: ADF
        scans are not trimmed. Skipped (with a warning) if less than 1 inch
        would remain in either direction."""
        if not self.trim or settings.source != "platen":
            return settings
        left, top, right, bottom = self.trim.units()
        width = settings.width - left - right
        height = settings.height - top - bottom
        if width < MIN_TRIMMED or height < MIN_TRIMMED:
            log.warning("trim too large for the scan area (%dx%d, 1/300 inch left), "
                        "scanning without trim", width, height)
            return settings
        log.debug("trim left=%s top=%s right=%s bottom=%s mm: offset %d,%d size %dx%d",
                  self.trim.left, self.trim.top, self.trim.right, self.trim.bottom,
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
        return self.use_panel and panel.decode(interrupt).doc_type in modes

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
            multipage=True, keepalive=self.keepalive)
        complete = [p for p in pages if is_complete(p, "jpeg")]
        self._pages = len(complete)
        if len(complete) != len(pages):
            log.warning("discarded %d incomplete page(s)", len(pages) - len(complete))
        if not complete:
            return []
        if settings.fmt == "pdf":
            return [jpegs_to_pdf(complete, settings.resolution)]
        return complete

    def scan_to(self, target: Target, event: int = 0, interrupt: bytes = b"") -> list[Path]:
        """Scan for target and save the files; the result goes to self.status."""
        self.status.set_busy(target.name)
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
        self.status.record(ScanRecord(time.time(), target.name, self._method, self._pages,
                                      tuple(str(p) for p in paths),
                                      "ok" if paths else "nothing saved"))
        return paths

    def _scan_to(self, target: Target, event: int, interrupt: bytes) -> list[Path]:
        log.info("scan requested: event=0x%x interrupt=%s", event, interrupt.hex())
        outdir = target.outdir
        settings = self.settings_for(interrupt, target)
        native = self.use_native(settings, interrupt, target)
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
        outdir.mkdir(parents=True, exist_ok=True)
        paths = output_names(outdir, settings.fmt, len(complete), datetime.now())
        for path, data in zip(paths, complete):
            path.write_bytes(data)
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
            try:
                self.step()
                backoff = self.interval
                self.status.poll_ok()
            except Exception as exc:
                log.warning("printer not reachable (%s), retrying in %.0fs", exc, backoff)
                self.status.poll_failed(str(exc))
                for target in self.targets:
                    target.session = None
                # Short cap: after a printer restart the names should reappear quickly.
                backoff = min(backoff * 2, MAX_BACKOFF)
            self.status.set_targets(self.targets)
            self.stop_event.wait(backoff)
        self.release()

    def stop(self) -> None:
        self.stop_event.set()
