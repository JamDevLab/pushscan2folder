"""Find scanners in the local network with mDNS (Bonjour), for the setup.

Printers with eSCL announce the service "_uscan._tcp.local". The query is a
"legacy unicast" query (RFC 6762, section 6.7): it goes to the mDNS multicast
address from an ordinary port, and every responder answers directly to that
port. So no listening on port 5353 is needed, which Bonjour on Windows may
already use. The address of a printer is the sender of its answer.

Plain stdlib; build_query and parse_response work on bytes, so they are
tested without a network."""
from __future__ import annotations

import socket
import struct
import time
from dataclasses import dataclass

MDNS_ADDR = ("224.0.0.251", 5353)
SERVICE = "_uscan._tcp.local"
TYPE_A, TYPE_PTR, TYPE_TXT, TYPE_SRV = 1, 12, 16, 33
MAX_PACKET = 9000


@dataclass(frozen=True)
class Scanner:
    address: str   # IPv4 address (the sender of the answer)
    name: str      # instance name, e.g. "Canon TR8500 series"
    model: str     # TXT "ty" if given, else ""


def build_query(service: str = SERVICE, query_id: int = 0x5032) -> bytes:
    """One PTR question for `service`."""
    header = struct.pack(">HHHHHH", query_id, 0, 1, 0, 0, 0)
    name = b"".join(bytes([len(p)]) + p.encode("ascii") for p in service.split(".")) + b"\0"
    return header + name + struct.pack(">HH", TYPE_PTR, 1)


def _name(data: bytes, offset: int, depth: int = 0) -> tuple[str, int]:
    """Read a (possibly compressed) DNS name. Returns (name, offset after it)."""
    labels = []
    while True:
        if offset >= len(data) or depth > 20:
            raise ValueError("bad name")
        length = data[offset]
        if length & 0xC0 == 0xC0:              # pointer to an earlier name
            if offset + 1 >= len(data):
                raise ValueError("bad pointer")
            pointer = ((length & 0x3F) << 8) | data[offset + 1]
            if pointer >= offset:
                raise ValueError("forward pointer")
            rest, _ = _name(data, pointer, depth + 1)
            labels.append(rest)
            return ".".join(x for x in labels if x), offset + 2
        if length == 0:
            return ".".join(labels), offset + 1
        start, offset = offset + 1, offset + 1 + length
        if offset > len(data):
            raise ValueError("bad label")
        labels.append(data[start:offset].decode("utf-8", "replace"))


def _txt(rdata: bytes) -> dict[str, str]:
    values, i = {}, 0
    while i < len(rdata):
        length = rdata[i]
        item = rdata[i + 1:i + 1 + length].decode("utf-8", "replace")
        i += 1 + length
        key, _, value = item.partition("=")
        values.setdefault(key.lower(), value)
    return values


def parse_response(data: bytes, service: str = SERVICE) -> tuple[list[str], dict[str, str]]:
    """Instance names for `service` (from PTR records) and the TXT "ty"
    values per instance. Raises ValueError for a malformed packet."""
    if len(data) < 12:
        raise ValueError("short packet")
    _, _, qd, an, ns, ar = struct.unpack(">HHHHHH", data[:12])
    offset = 12
    for _ in range(qd):
        _, offset = _name(data, offset)
        offset += 4
    instances: list[str] = []
    models: dict[str, str] = {}
    suffix = "." + service.lower()
    for _ in range(an + ns + ar):
        owner, offset = _name(data, offset)
        if offset + 10 > len(data):
            raise ValueError("short record")
        rtype, _, _, length = struct.unpack(">HHIH", data[offset:offset + 10])
        start = offset + 10
        offset = start + length
        if offset > len(data):
            raise ValueError("short record data")
        if rtype == TYPE_PTR and owner.lower() == service.lower():
            target, _ = _name(data, start)
            if target.lower().endswith(suffix) and target not in instances:
                instances.append(target)
        elif rtype == TYPE_TXT and owner.lower().endswith(suffix):
            model = _txt(data[start:offset]).get("ty", "")
            if model:
                models[owner] = model
    return instances, models


def instance_label(instance: str, service: str = SERVICE) -> str:
    """"Canon TR8500 series._uscan._tcp.local" -> "Canon TR8500 series"."""
    if instance.lower().endswith("." + service.lower()):
        return instance[:-(len(service) + 1)]
    return instance


def discover(timeout: float = 2.0, service: str = SERVICE,
             sock_factory=None) -> list[Scanner]:
    """Ask the local network for eSCL scanners and collect the answers for
    `timeout` seconds. Returns [] if the network does not allow it."""
    found: dict[str, Scanner] = {}
    try:
        sock = (sock_factory or (lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM)))()
    except OSError:
        return []
    with sock:
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
            sock.sendto(build_query(service), MDNS_ADDR)
        except OSError:
            return []
        end = time.monotonic() + timeout
        while True:
            left = end - time.monotonic()
            if left <= 0:
                break
            sock.settimeout(left)
            try:
                data, (address, _port) = sock.recvfrom(MAX_PACKET)
            except socket.timeout:
                break
            except OSError:
                break
            try:
                instances, models = parse_response(data, service)
            except ValueError:
                continue
            for instance in instances:
                found.setdefault(address, Scanner(address, instance_label(instance, service),
                                                  models.get(instance, "")))
    return sorted(found.values(), key=lambda s: tuple(int(p) for p in s.address.split(".")))
