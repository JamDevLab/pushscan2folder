"""Canon IJ "CHMP" push-scan notification protocol.

Independent implementation for interoperability with Canon IJ printers; see
docs/PROTOCOL.md for the observed behaviour.

The PC registers itself with the printer and then polls it. When the user picks
this PC as the scan destination on the printer panel, the poll answer carries a
"scan requested" status plus 32 bytes of interrupt data (the panel settings).

Transport: HTTP POST to http://<printer>:80/canon/ij/command1/port2 with
  Content-Type: application/octet-stream
  X-CHMP-Version: 1.0
  X-CHMP-CommandType: BJNPNotify
  X-CHMP-EventType: PuScan

Request body: 0x68 bytes, big endian
  +0x00 u16 type        1 = register, 2 = poll, 4 = release
  +0x02 u16 reserved
  +0x04 u32 session id  (poll / release)
  +0x08 64 bytes        host name, UTF-16BE, NUL padded (register only)
  +0x48 u32 reserved
  +0x60 u32 reserved

Response body: 0x110 bytes, big endian
  +0x02 u16 status      0x8000 = scan requested (poll)
  +0x04 u32 session id  (register)
  +0x08 u32 unknown
  +0x0c u32 event value (poll, status 0x8000)
  +0x10 32 bytes        interrupt data (poll, status 0x8000)
  +0x8c u32 unknown
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass

PATH = "/canon/ij/command1/port2"
REQUEST_SIZE = 0x68
RESPONSE_SIZE = 0x110
NAME_BYTES = 64
MAX_NAME_CHARS = NAME_BYTES // 2 - 1  # UTF-16 plus terminating NUL

# What the TR8550 panel can show: other characters (also ".", "&", umlauts,
# accents, emoji) are accepted by the printer but shown as blanks.
PANEL_CHARS = "A-Z, a-z, 0-9, space, - _ @"
_PANEL_RE = re.compile(r"[A-Za-z0-9 _@-]")
# The panel shows about this many characters, then "...".
VISIBLE_NAME_CHARS = 25


def invalid_name_chars(name: str) -> str:
    """Characters of name the panel cannot show, in order, without repeats."""
    return "".join(dict.fromkeys(c for c in name if not _PANEL_RE.fullmatch(c)))


def check_name(name: str) -> None:
    """Raise ValueError unless name can be registered and shown on the panel."""
    if not name.strip():
        raise ValueError("name is empty")
    if len(name) > MAX_NAME_CHARS:
        raise ValueError(f"name {name!r} is longer than {MAX_NAME_CHARS} characters")
    bad = invalid_name_chars(name)
    if bad:
        raise ValueError(f"name {name!r} contains characters the printer panel cannot show: "
                         f"{' '.join(repr(c) for c in bad)} (allowed: {PANEL_CHARS})")


def panel_safe(text: str) -> str:
    """Replace characters the panel cannot show with '-' and cut to the limit."""
    return "".join(c if _PANEL_RE.fullmatch(c) else "-" for c in text)[:MAX_NAME_CHARS]

TYPE_REGISTER = 1
TYPE_POLL = 2
TYPE_RELEASE = 4

STATUS_OK = 0x0000
STATUS_SCAN_REQUESTED = 0x8000
# Observed on a TR8550 after ~60 s without polls (e.g. during a long ADF scan):
# the printer has dropped the registration and the name is gone from the panel.
STATUS_SESSION_EXPIRED = 0x0001

HEADERS = {
    "Content-Type": "application/octet-stream",
    "X-CHMP-Version": "1.0",
    "X-CHMP-CommandType": "BJNPNotify",
    "X-CHMP-EventType": "PuScan",
}


def default_name(user: str, host: str) -> str:
    """Name format used by the Windows tool: USER + two spaces + COMPUTERNAME."""
    return f"{user}  {host}"


def encode_name(name: str) -> bytes:
    """UTF-16BE, max 31 characters plus terminating NUL, padded to 64 bytes."""
    raw = name.encode("utf-16-be")[: NAME_BYTES - 2]
    return raw.ljust(NAME_BYTES, b"\0")


def build_request(req_type: int, session: int = 0, name: str | None = None) -> bytes:
    buf = bytearray(REQUEST_SIZE)
    struct.pack_into(">HHI", buf, 0, req_type, 0, session)
    if name is not None:
        buf[8:8 + NAME_BYTES] = encode_name(name)
    return bytes(buf)


def build_register(name: str) -> bytes:
    return build_request(TYPE_REGISTER, name=name)


def build_poll(session: int) -> bytes:
    return build_request(TYPE_POLL, session=session)


def build_release(session: int) -> bytes:
    return build_request(TYPE_RELEASE, session=session)


@dataclass(frozen=True)
class Response:
    status: int
    session: int
    unknown8: int
    event: int
    interrupt: bytes
    unknown8c: int
    raw: bytes

    @property
    def scan_requested(self) -> bool:
        return self.status == STATUS_SCAN_REQUESTED


def parse_response(data: bytes) -> Response:
    """Parse a response. The printer sends fewer bytes than the 0x110 buffer the
    Windows tool reserves (e.g. 52 for register), so missing fields read as 0."""
    if len(data) < 8:
        raise ValueError(f"response too short: {len(data)} bytes")
    raw = bytes(data)
    data = raw.ljust(RESPONSE_SIZE, b"\0")
    status, session, unk8, event = struct.unpack_from(">HIII", data, 2)
    interrupt = bytes(data[0x10:0x30])
    (unk8c,) = struct.unpack_from(">I", data, 0x8C)
    return Response(status, session, unk8, event, interrupt, unk8c, raw)
