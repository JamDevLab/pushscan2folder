"""Find scanners in the local network with mDNS (Bonjour), for the setup.

Printers with eSCL announce the service "_uscan._tcp.local". The query is a
"legacy unicast" query (RFC 6762, section 6.7): it goes to the mDNS multicast
address from an ordinary port, and every responder answers directly to that
port. So no listening on port 5353 is needed, which Bonjour on Windows may
already use. The address of a printer is the sender of its answer.

A multicast packet leaves through one network adapter only. On a PC with
several (WSL or Hyper-V "vEthernet", VPN, Wi-Fi and LAN) the system often
picks one without the printer, so the query is sent on every IPv4 address
of this computer. It is repeated a few times, as a responder may miss one.

Plain stdlib; build_query and parse_response work on bytes, so they are
tested without a network."""
from __future__ import annotations

import re
import socket
import struct
import time
from dataclasses import dataclass

MDNS_ADDR = ("224.0.0.251", 5353)
SERVICE = "_uscan._tcp.local"
TYPE_A, TYPE_PTR, TYPE_TXT, TYPE_SRV = 1, 12, 16, 33
MAX_PACKET = 9000
TIMEOUT = 5.0                   # seconds to collect answers
MAX_TEXT = 100                  # longest name or model text kept
RESEND_AT = (0.0, 1.0, 2.5)     # seconds after the start: send the query (again)


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def clean_text(text: str, limit: int = MAX_TEXT) -> str:
    """Text from the network, safe to print: no control characters (they
    could carry terminal escape sequences), at most `limit` characters."""
    return _CONTROL.sub("", text)[:limit]


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
        labels.append(clean_text(data[start:offset].decode("utf-8", "replace"), 255))


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
            model = clean_text(_txt(data[start:offset]).get("ty", ""))
            if model:
                models[owner] = model
    return instances, models


def instance_label(instance: str, service: str = SERVICE) -> str:
    """"Canon TR8500 series._uscan._tcp.local" -> "Canon TR8500 series"."""
    if instance.lower().endswith("." + service.lower()):
        return instance[:-(len(service) + 1)]
    return instance


def local_addresses() -> list[str]:
    """The IPv4 addresses of this computer (no loopback), best effort."""
    found = []
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        infos = []
    for info in infos:
        address = info[4][0]
        if not address.startswith("127.") and address not in found:
            found.append(address)
    return found


def _send(sock, query: bytes, interfaces: list[str]) -> bool:
    """Send the query on the default adapter and on each address in
    `interfaces`. True if at least one send worked."""
    sent = False
    for interface in ["0.0.0.0"] + interfaces:   # 0.0.0.0: the adapter the system picks
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                            socket.inet_aton(interface))
            sock.sendto(query, MDNS_ADDR)
            sent = True
        except OSError:
            continue
    return sent


def discover(timeout: float = TIMEOUT, service: str = SERVICE,
             sock_factory=None, interfaces=None) -> list[Scanner]:
    """Ask the local network for eSCL scanners and collect the answers for
    `timeout` seconds. Returns [] if the network does not allow it.
    `interfaces`: local IPv4 addresses to send on (default: all of them)."""
    found: dict[str, Scanner] = {}
    try:
        sock = (sock_factory or (lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM)))()
    except OSError:
        return []
    with sock:
        query = build_query(service)
        interfaces = local_addresses() if interfaces is None else list(interfaces)
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        except OSError:
            pass
        if not _send(sock, query, interfaces):
            return []
        start = time.monotonic()
        end = start + timeout
        resend = [start + t for t in RESEND_AT[1:] if t < timeout]
        while True:
            now = time.monotonic()
            left = end - now
            if left <= 0:
                break
            if resend and now >= resend[0]:
                resend.pop(0)
                _send(sock, query, interfaces)
            sock.settimeout(min([left] + [r - now for r in resend[:1]]) or 0.01)
            try:
                data, (address, port) = sock.recvfrom(MAX_PACKET)
            except socket.timeout:
                continue
            except OSError:
                break
            if port != MDNS_ADDR[1]:   # a real mDNS responder answers from port 5353
                continue
            try:
                instances, models = parse_response(data, service)
            except ValueError:
                continue
            by_name = {k.lower(): v for k, v in models.items()}   # DNS names ignore case
            for instance in instances:
                found.setdefault(address, Scanner(address, clean_text(instance_label(instance, service)),
                                                  by_name.get(instance.lower(), "")))
    return sorted(found.values(), key=lambda s: tuple(int(p) for p in s.address.split(".")))
