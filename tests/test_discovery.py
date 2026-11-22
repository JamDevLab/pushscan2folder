import socket
import struct
import unittest

from pushscan2folder import discovery
from pushscan2folder.discovery import Scanner, build_query, parse_response


def name(text):
    return b"".join(bytes([len(p)]) + p.encode() for p in text.split(".")) + b"\0"


def record(owner: bytes, rtype: int, rdata: bytes) -> bytes:
    return owner + struct.pack(">HHIH", rtype, 0x8001, 120, len(rdata)) + rdata


def answer(instance="Canon TR8500 series", model="Canon TR8500 series"):
    """A response as a printer sends it: PTR with a compressed name, TXT, SRV, A."""
    header = struct.pack(">HHHHHH", 0x5032, 0x8400, 0, 1, 0, 3)
    service = name("_uscan._tcp.local")            # at offset 12
    ptr_target = bytes([len(instance)]) + instance.encode() + b"\xc0\x0c"
    body = record(service, discovery.TYPE_PTR, ptr_target)
    inst_offset = 12 + len(service) + 10            # where the instance name starts
    owner = struct.pack(">H", 0xC000 | inst_offset)
    txt = b"".join(bytes([len(x)]) + x for x in (b"txtvers=1", b"ty=" + model.encode()))
    body += record(owner, discovery.TYPE_TXT, txt)
    body += record(owner, discovery.TYPE_SRV, struct.pack(">HHH", 0, 0, 80) + name("printer.local"))
    body += record(name("printer.local"), discovery.TYPE_A, bytes([192, 168, 1, 50]))
    return header + body


class ParseTests(unittest.TestCase):
    def test_query(self):
        q = build_query()
        self.assertEqual(struct.unpack(">HHHHHH", q[:12])[2], 1)      # one question
        self.assertIn(b"\x06_uscan\x04_tcp\x05local\x00", q)
        self.assertEqual(q[-4:], struct.pack(">HH", 12, 1))

    def test_answer_with_compression(self):
        instances, models = parse_response(answer())
        self.assertEqual(instances, ["Canon TR8500 series._uscan._tcp.local"])
        self.assertEqual(models, {instances[0]: "Canon TR8500 series"})
        self.assertEqual(discovery.instance_label(instances[0]), "Canon TR8500 series")

    def test_malformed_packets(self):
        good = answer()
        for bad in (b"", good[:11], good[:40], good[:-3],
                    good[:12] + b"\xc0\xff" + good[14:],            # forward pointer
                    struct.pack(">HHHHHH", 0, 0, 0, 1, 0, 0) + b"\x3f" + b"a" * 5):
            with self.assertRaises(ValueError):
                parse_response(bad)

    def test_pointer_loop_is_refused(self):
        data = struct.pack(">HHHHHH", 0, 0, 0, 1, 0, 0) + b"\xc0\x0c"
        with self.assertRaises(ValueError):
            parse_response(data)

    def test_other_services_are_ignored(self):
        data = struct.pack(">HHHHHH", 0, 0, 0, 1, 0, 0) + record(
            name("_ipp._tcp.local"), discovery.TYPE_PTR, name("x._ipp._tcp.local"))
        self.assertEqual(parse_response(data), ([], {}))


class FakeSocket:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def setsockopt(self, *args):
        pass

    def settimeout(self, value):
        pass

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def recvfrom(self, size):
        if not self.replies:
            raise socket.timeout()
        return self.replies.pop(0)


class DiscoverTests(unittest.TestCase):
    def test_collects_answers_by_sender(self):
        sock = FakeSocket([(answer(), ("192.168.1.50", 5353)),
                           (b"garbage", ("192.168.1.9", 5353)),
                           (answer("Other", ""), ("192.168.1.7", 5353)),
                           (answer(), ("192.168.1.50", 5353))])       # repeated answer
        found = discovery.discover(timeout=1, sock_factory=lambda: sock)
        self.assertEqual(sock.sent[0][1], discovery.MDNS_ADDR)
        self.assertEqual(found, [Scanner("192.168.1.7", "Other", ""),
                                 Scanner("192.168.1.50", "Canon TR8500 series",
                                         "Canon TR8500 series")])

    def test_network_errors_give_an_empty_list(self):
        def broken():
            raise OSError("no network")
        self.assertEqual(discovery.discover(timeout=0.1, sock_factory=broken), [])


if __name__ == "__main__":
    unittest.main()
