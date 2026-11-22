"""Canon's own scanner protocol over CHMP (HTTP), used for platen multi-page scans.

Independent implementation for interoperability, based on observing the
traffic of the official software; see docs/PROTOCOL.md.

Every exchange is an HTTP POST of the request body to /canon/ij/command2/port3
followed by an HTTP GET of the same path, which returns the answer. Bodies are
either XML job control documents (StartJob, VendorCmd/ModeShift, EndJob) or
binary scanner commands:

  command: 16 byte header, big endian
    +0x00 u16 opcode
    +0x02 u16 argument
    +0x0c u32 length (bytes expected back, or bytes of data that follow)
    data, last byte is a checksum (all data bytes sum to 0 mod 256)
  reply:
    +0x00 u16 status (0x0606 = ok), then 6 bytes 0, then the data

The page image arrives as a JPEG stream in chunks. After each page the PC asks
the printer whether another page follows; that request makes the printer show
its "next page" dialog.
"""
from __future__ import annotations

import http.client
import logging
import struct
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .client import read_body

log = logging.getLogger(__name__)

PATH = "/canon/ij/command2/port3"
HEADERS_POST = {"Content-Type": "application/octet-stream", "X-CHMP-Version": "1.0"}
HEADERS_GET = {"X-CHMP-Version": "1.0"}

STATUS_OK = 0x0606
STATUS_CANCELLED = 0x1515  # seen when Stop is pressed while a page is scanned

OP_START_SESSION = 0xDB20
OP_STATUS = 0xF320
OP_SCAN_PARAM = 0xD820
OP_SCAN_START = 0xD920
OP_SCAN_STATE = 0xDA20
OP_DC20 = 0xDC20          # unknown, sent once before reading the image
OP_READ_IMAGE = 0xD420
OP_IMAGE_INFO = 0xE120
OP_NEXT_PAGE = 0xEC20     # ask the user (panel dialog) for another page
OP_END_SESSION = 0xEF20

SCAN_STATE_READY = 0x03

# Read image: the official software asks for up to 1 MiB + 8; the printer
# answers with chunks of at most 16 KiB.
READ_IMAGE_LENGTH = 0x00100008

# Bounds for what the printer sends (all pages stay in memory until saved).
MAX_REPLY = READ_IMAGE_LENGTH + 64 * 1024
MAX_PAGE_BYTES = 256 * 1024 * 1024
MAX_PAGES = 200
MAX_SCAN_BYTES = 1024 * 1024 * 1024   # all pages of one scan together

# Flags in byte 8 of a read image reply.
IMAGE_LAST_DATA = 0x20    # set on the last data chunk and afterwards
IMAGE_PAGE_END = 0x08     # page finished, no more data

# Answers to OP_NEXT_PAGE (first data byte).
NEXT_WAITING = 0x00
NEXT_COLOR = 0x01         # "Colour" pressed: scan another page in colour
NEXT_GRAY = 0x02          # "Black and white" pressed (*unconfirmed*)
NEXT_FINISH = 0xFF        # "Finish" pressed

# Largest platen area in 1/300 inch (A4 / Letter).
PLATEN_MAX = (2550, 3507)

XML_HEAD = ('<?xml version="1.0" encoding="utf-8" ?><cmd '
            'xmlns:ivec="http://www.canon.com/ns/cmd/2008/07/common/"')
XML_VCN = ' xmlns:vcn="http://www.canon.com/ns/cmd/2008/07/canon/"'


class NativeError(RuntimeError):
    pass


class NativeCancelled(NativeError):
    """The scan was cancelled on the panel."""


def checksum(data: bytes) -> int:
    return -sum(data) & 0xFF


def build_command(opcode: int, length: int = 0, arg: int = 0, data: bytes = b"") -> bytes:
    """Header plus data. If data is given, length is its size incl. checksum."""
    if data:
        data = bytes(data) + bytes([checksum(data)])
        length = len(data)
    return struct.pack(">HH8xI", opcode, arg, length) + data


def xml_start_job(job: str) -> bytes:
    return (XML_HEAD + "><ivec:contents><ivec:operation>StartJob</ivec:operation>"
            '<ivec:param_set servicetype="scan">'
            f"<ivec:jobID>{job}</ivec:jobID><ivec:bidi>1</ivec:bidi>"
            "</ivec:param_set></ivec:contents></cmd>").encode()


def xml_mode_shift(job: str) -> bytes:
    return (XML_HEAD + XML_VCN + "><ivec:contents><ivec:operation>VendorCmd</ivec:operation>"
            '<ivec:param_set servicetype="scan">'
            f"<ivec:jobID>{job}</ivec:jobID>"
            "<vcn:ijoperation>ModeShift</vcn:ijoperation><vcn:ijmode>1</vcn:ijmode>"
            "</ivec:param_set></ivec:contents></cmd>").encode()


def xml_end_job(job: str) -> bytes:
    return (XML_HEAD + "><ivec:contents><ivec:operation>EndJob</ivec:operation>"
            '<ivec:param_set servicetype="scan">'
            f"<ivec:jobID>{job}</ivec:jobID>"
            "</ivec:param_set></ivec:contents></cmd>").encode()


@dataclass(frozen=True)
class PageSettings:
    color: str = "color"      # color | gray
    resolution: int = 300
    width: int = 2480         # 1/300 inch
    height: int = 3507        # 1/300 inch
    x_offset: int = 0         # 1/300 inch
    y_offset: int = 0         # 1/300 inch


def pixels(settings: PageSettings) -> tuple[int, int, int, int]:
    """(x_offset, y_offset, width, height) in pixels at the scan resolution.
    The region is clamped so that offset + size stays within PLATEN_MAX."""
    x = max(0, min(settings.x_offset, PLATEN_MAX[0]))
    y = max(0, min(settings.y_offset, PLATEN_MAX[1]))
    w = min(settings.width, PLATEN_MAX[0] - x)
    h = min(settings.height, PLATEN_MAX[1] - y)
    r = settings.resolution
    return x * r // 300, y * r // 300, w * r // 300, h * r // 300


def build_scan_param(settings: PageSettings, now: datetime) -> bytes:
    """Scan parameter block (platen, JPEG). Fields not listed are constant in
    every observed scan; their meaning is unknown."""
    x, y, width, height = pixels(settings)
    d = bytearray(55)  # + checksum = 56
    d[0x00] = 0x01                    # source: platen
    d[0x01] = 0x01
    d[0x02] = 0x01
    d[0x06] = 0x01
    dpi = 0x8000 | settings.resolution
    struct.pack_into(">HH", d, 0x08, dpi, dpi)
    # Non-zero x/y offsets are unconfirmed on real hardware: only 0 was observed.
    struct.pack_into(">IIII", d, 0x0C, x, y, width, height)
    gray = settings.color == "gray"
    d[0x1C] = 0x04 if gray else 0x08  # gray: *unconfirmed*
    d[0x1D] = 0x08 if gray else 0x18  # bits per pixel
    d[0x1F] = 0x01
    d[0x20] = 0xFF
    d[0x21] = 0x82
    d[0x23] = 0x02
    d[0x24] = 0x01
    d[0x26:0x2A] = now.strftime("%H%M").encode()  # local time, shown by the printer?
    d[0x30] = 0x03
    return build_command(OP_SCAN_PARAM, data=bytes(d))


class NativeScanner:
    def __init__(self, printer: str, port: int = 80, timeout: float = 30.0,
                 poll_delay: float = 0.5, decision_timeout: float = 600.0):
        self.printer = printer
        self.port = port
        self.timeout = timeout
        self.poll_delay = poll_delay
        self.decision_timeout = decision_timeout
        self._conn: http.client.HTTPConnection | None = None

    # --- transport -------------------------------------------------------
    def _close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _http(self, method: str, body: bytes | None, headers: dict) -> bytes:
        for attempt in (1, 2):
            if self._conn is None:
                self._conn = http.client.HTTPConnection(self.printer, self.port,
                                                        timeout=self.timeout)
            try:
                self._conn.request(method, PATH, body=body, headers=headers)
                resp = self._conn.getresponse()
                try:
                    data = read_body(resp, MAX_REPLY, NativeError)
                except NativeError:
                    self._close()
                    raise
            except (OSError, http.client.HTTPException):
                self._close()
                if attempt == 2:
                    raise
                continue
            if resp.status != 200:
                raise NativeError(f"{method} {PATH}: HTTP {resp.status}")
            return data
        raise AssertionError("unreachable")

    def exchange(self, body: bytes) -> bytes:
        self._http("POST", body, HEADERS_POST)
        return self._http("GET", None, HEADERS_GET)

    def command(self, opcode: int, length: int = 0, arg: int = 0, data: bytes = b"") -> bytes:
        return self.checked(build_command(opcode, length, arg, data))

    def checked(self, body: bytes) -> bytes:
        """Send a prebuilt binary command and check the reply status."""
        reply = self.exchange(body)
        status = struct.unpack_from(">H", reply)[0] if len(reply) >= 2 else None
        if status == STATUS_CANCELLED:
            raise NativeCancelled(f"command 0x{body[:2].hex()}: cancelled on the panel")
        if status != STATUS_OK:
            raise NativeError(f"command 0x{body[:2].hex()}: status "
                              + (f"0x{status:04x}" if status is not None else "missing"))
        return reply[8:]

    def xml(self, body: bytes) -> str:
        text = self.exchange(body).decode("utf-8", "replace")
        if "<ivec:response>OK</ivec:response>" not in text:
            raise NativeError(f"XML command failed: {text[:300]}")
        return text

    # --- scan ------------------------------------------------------------
    def _wait_ready(self, keepalive: Callable[[], None]) -> None:
        deadline = time.monotonic() + 60
        while True:
            state = self.command(OP_SCAN_STATE, 8)
            if state and state[0] == SCAN_STATE_READY:
                return
            if time.monotonic() > deadline:
                raise NativeError(f"scanner not ready, state {state.hex()}")
            keepalive()
            time.sleep(self.poll_delay)

    def _read_page(self, keepalive: Callable[[], None], limit: int | None = None) -> bytes:
        limit = MAX_PAGE_BYTES if limit is None else limit
        image = bytearray()
        idle_since = time.monotonic()
        while True:
            reply = self.command(OP_READ_IMAGE, READ_IMAGE_LENGTH)
            if len(reply) < 8:
                raise NativeError(f"short image reply: {reply.hex()}")
            flags = reply[0]
            (size,) = struct.unpack_from(">I", reply, 4)
            image += reply[8:8 + size]
            if len(image) > limit:
                raise NativeError(f"page larger than {limit} bytes (limit)")
            if flags & IMAGE_PAGE_END:
                return bytes(image)
            if size:
                idle_since = time.monotonic()
            else:
                if time.monotonic() - idle_since > 120:
                    raise NativeError("no image data for 120 s")
                keepalive()
                time.sleep(0.05)

    def _scan_page(self, settings: PageSettings, keepalive: Callable[[], None],
                   limit: int | None = None) -> bytes:
        self.command(OP_STATUS, 0x10)
        self.checked(build_scan_param(settings, datetime.now()))
        self.command(OP_SCAN_START, arg=1)
        self._wait_ready(keepalive)
        self.command(OP_DC20, 8)
        page = self._read_page(keepalive, limit)
        self.command(OP_IMAGE_INFO, 0x100)
        return page

    def _next_page(self, keepalive: Callable[[], None],
                   should_stop: Callable[[], bool] = lambda: False) -> int:
        deadline = time.monotonic() + self.decision_timeout
        while time.monotonic() < deadline:
            if should_stop():
                log.info("stop requested, finishing the job with the pages scanned so far")
                return NEXT_FINISH
            answer = self.command(OP_NEXT_PAGE, 8)
            code = answer[0] if answer else NEXT_WAITING
            if code != NEXT_WAITING:
                log.info("panel decision 0x%02x (%s)", code, answer.hex())
                return code
            keepalive()
            time.sleep(self.poll_delay)
        log.warning("no decision on the panel within %.0f s", self.decision_timeout)
        return NEXT_FINISH

    def scan(self, settings: PageSettings, multipage: bool = True,
             keepalive: Callable[[], None] = lambda: None,
             job: str = "00000001",
             should_stop: Callable[[], bool] = lambda: False) -> list[bytes]:
        """Scan from the platen; with multipage the panel asks for more pages.
        Returns one JPEG per page. Pages already scanned are kept if a later
        page fails or is cancelled, or if `should_stop` turns true while the
        panel waits for the next-page decision."""
        pages: list[bytes] = []
        # The official software switches the mode once before starting the job.
        self.xml(xml_mode_shift(" "))
        self.command(OP_STATUS, 0x10)
        self.xml(xml_start_job(job))
        try:
            self.xml(xml_mode_shift(job))
            self.command(OP_START_SESSION, arg=2)
            while True:
                try:
                    budget = MAX_SCAN_BYTES - sum(len(p) for p in pages)
                    page = self._scan_page(settings, keepalive, min(MAX_PAGE_BYTES, budget))
                except NativeCancelled:
                    log.info("page %d cancelled on the panel, keeping %d page(s)",
                             len(pages) + 1, len(pages))
                    break
                except NativeError as exc:
                    if not pages:
                        raise
                    log.warning("page %d failed (%s), keeping %d page(s)",
                                len(pages) + 1, exc, len(pages))
                    break
                pages.append(page)
                log.info("received page %d (%d bytes)", len(pages), len(page))
                if not multipage:
                    break
                if len(pages) >= MAX_PAGES or sum(map(len, pages)) >= MAX_SCAN_BYTES:
                    log.warning("stopping after %d pages (size or page limit)", len(pages))
                    break
                try:
                    code = self._next_page(keepalive, should_stop)
                except NativeError as exc:
                    log.warning("next page request failed (%s), finishing", exc)
                    break
                if code == NEXT_COLOR:
                    settings = PageSettings(**{**settings.__dict__, "color": "color"})
                elif code == NEXT_GRAY:
                    settings = PageSettings(**{**settings.__dict__, "color": "gray"})
                else:
                    if code != NEXT_FINISH:
                        log.info("panel answered 0x%02x, finishing", code)
                    break
                log.info("next page requested (%s)", settings.color)
        finally:
            for body in (build_command(OP_END_SESSION), xml_end_job(job)):
                try:
                    self.exchange(body)
                except Exception as exc:  # best effort
                    log.warning("ending scan job failed: %s", exc)
            self._close()
        return pages
