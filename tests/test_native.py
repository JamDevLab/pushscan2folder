"""Native (port3) scan protocol: message building and a fake printer flow."""
import struct
import tempfile
import threading
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pushscan2folder import native, pdf, protocol
from pushscan2folder.client import ChmpClient
from pushscan2folder.escl import EsclClient, ScanSettings
from pushscan2folder.native import NativeScanner, PageSettings
from pushscan2folder.service import PushScanService, Target

# Scan parameter block of an observed A4 / 300 dpi / colour scan at 01:50.
CAPTURED_PARAM = bytes.fromhex(
    "d82000000000000000000000000000380101010000000100812c812c0000000000000000"
    "000009b000000db308180001ff82000201003031353000000000000003000000000000bb")


def fake_jpeg(width=16, height=8, comps=3, fill=b"\x00" * 300):
    sof = struct.pack(">BHHB", 8, height, width, comps) + b"\x01\x11\x00" * comps
    return (b"\xff\xd8"
            + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x02\x01" + struct.pack(">HH", 300, 300) + b"\x00\x00"
            + b"\xff\xc0" + struct.pack(">H", len(sof) + 2) + sof
            + fill + b"\xff\xd9")


def reply(data=b""):
    return b"\x06\x06" + bytes(6) + data


def with_sum(data):
    return data + bytes([native.checksum(data)])


class FakeNativePrinter(BaseHTTPRequestHandler):
    """CHMP push registration on port2 plus the port3 scan protocol."""

    protocol_version = "HTTP/1.1"
    state = {}

    def log_message(self, *args):
        pass

    def _send(self, body=b""):
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        st = self.state
        if self.path == protocol.PATH:
            req_type = int.from_bytes(body[:2], "big")
            status = 0
            if req_type == protocol.TYPE_POLL and st.get("pending"):
                st["pending"] = False
                status = protocol.STATUS_SCAN_REQUESTED
            st["port2"] = st.get("port2", 0) + 1
            self._send(status.to_bytes(4, "big") + (0x10).to_bytes(4, "big")
                       + bytes.fromhex("00000024c5f16de8") + st.get("interrupt", bytes(32)))
            return
        st.setdefault("log", []).append(body)
        st["answer"] = self.answer(body)
        self._send()

    def do_GET(self):
        self._send(self.state.pop("answer", b""))

    def answer(self, body):
        st = self.state
        if body.startswith(b"<?xml"):
            op = body.split(b"<ivec:operation>")[1].split(b"<")[0].decode()
            return (f"<cmd><ivec:operation>{op}Response</ivec:operation>"
                    "<ivec:response>OK</ivec:response></cmd>").encode()
        op = int.from_bytes(body[:2], "big")
        if op == native.OP_SCAN_START:
            st["chunks"] = list(st["pages"].pop(0))
            st["ready"] = 2
        if op == native.OP_SCAN_STATE:
            st["ready"] -= 1
            return reply(with_sum(bytes([1 if st["ready"] > 0 else 3]) + bytes(6)))
        if op == native.OP_READ_IMAGE:
            if st.get("cancel"):
                return b"\x15\x15" + bytes(6)
            if st["chunks"]:
                chunk = st["chunks"].pop(0)
                flag = native.IMAGE_LAST_DATA if not st["chunks"] else 0
                return reply(bytes([flag, 0, 0, 0]) + struct.pack(">I", len(chunk)) + chunk)
            return reply(bytes([native.IMAGE_LAST_DATA | native.IMAGE_PAGE_END]) + bytes(7))
        if op == native.OP_NEXT_PAGE:
            return reply(with_sum(bytes([st["decisions"].pop(0)]) + bytes(6)))
        if op == native.OP_STATUS:
            return reply(bytes(16))
        if op == native.OP_IMAGE_INFO:
            return reply(bytes(256))
        return reply()


def split(data, size=100):
    return [data[i:i + size] for i in range(0, len(data), size)]


class NativeTests(unittest.TestCase):
    def setUp(self):
        FakeNativePrinter.state = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeNativePrinter)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]
        self.scanner = NativeScanner("127.0.0.1", self.port, poll_delay=0.01)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_scan_param_matches_capture(self):
        self.assertEqual(native.build_scan_param(PageSettings(), datetime(2026, 1, 1, 1, 50)),
                         CAPTURED_PARAM)

    def test_command_header(self):
        self.assertEqual(native.build_command(native.OP_STATUS, 0x10).hex(),
                         "f3200000000000000000000000000010")
        self.assertEqual(native.build_command(native.OP_START_SESSION, arg=2).hex(),
                         "db200002000000000000000000000000")
        self.assertEqual(native.build_command(native.OP_READ_IMAGE, native.READ_IMAGE_LENGTH).hex(),
                         "d4200000000000000000000000100008")

    def test_region_is_clamped_to_platen(self):
        x, y, w, h = native.pixels(PageSettings(resolution=600, width=2550, height=4200))
        self.assertEqual((x, y, w, h), (0, 0, 5100, 7014))

    def test_offsets_are_converted_and_clamped(self):
        x, y, w, h = native.pixels(PageSettings(resolution=600, width=2400, height=3400,
                                                x_offset=35, y_offset=24))
        self.assertEqual((x, y, w, h), (70, 48, 4800, 6800))
        # offset + width must stay within PLATEN_MAX
        x, y, w, h = native.pixels(PageSettings(x_offset=100, y_offset=200, width=2480, height=3507))
        self.assertEqual((x, y, w, h), (100, 200, 2450, 3307))

    def test_scan_param_holds_offsets(self):
        data = native.build_scan_param(PageSettings(x_offset=10, y_offset=20, width=2000,
                                                    height=3000), datetime(2026, 1, 1, 1, 50))
        body = data[16:]
        self.assertEqual(struct.unpack_from(">IIII", body, 0x0C), (10, 20, 2000, 3000))

    def test_two_pages_then_finish(self):
        p1, p2 = fake_jpeg(fill=b"\x01" * 250), fake_jpeg(fill=b"\x02" * 250)
        FakeNativePrinter.state.update(pages=[split(p1), split(p2)],
                                       decisions=[0, 0, native.NEXT_GRAY, native.NEXT_FINISH])
        pages = self.scanner.scan(PageSettings())
        self.assertEqual(pages, [p1, p2])
        log = FakeNativePrinter.state["log"]
        params = [b for b in log if b[:2] == b"\xd8\x20"]
        self.assertEqual([b[16 + 0x1c] for b in params], [0x08, 0x04])  # colour, then gray
        self.assertTrue(log[-1].startswith(b"<?xml") and b"EndJob" in log[-1])
        self.assertEqual(log[-2][:2], b"\xef\x20")

    def test_cancel_during_first_page_returns_nothing(self):
        FakeNativePrinter.state.update(pages=[split(fake_jpeg())], decisions=[], cancel=True)
        self.assertEqual(self.scanner.scan(PageSettings()), [])
        log = FakeNativePrinter.state["log"]
        self.assertTrue(b"EndJob" in log[-1])

    def test_single_page_without_dialog(self):
        p1 = fake_jpeg()
        FakeNativePrinter.state.update(pages=[split(p1)], decisions=[])
        self.assertEqual(self.scanner.scan(PageSettings(), multipage=False), [p1])
        self.assertFalse(any(b[:2] == b"\xec\x20" for b in FakeNativePrinter.state["log"]))

    def test_service_saves_one_pdf(self):
        p1, p2 = fake_jpeg(), fake_jpeg(width=20)
        interrupt = bytes.fromhex("0000000001010101010001030301010200000000000000000000000000000000")
        FakeNativePrinter.state.update(pages=[split(p1), split(p2)],
                                       decisions=[native.NEXT_COLOR, native.NEXT_FINISH],
                                       interrupt=interrupt, pending=True)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            service = PushScanService(ChmpClient("127.0.0.1", self.port),
                                      EsclClient("127.0.0.1", self.port),
                                      [Target("scan1", out)], ScanSettings(),
                                      native=self.scanner)
            service.step()
            files = list(out.iterdir())
            self.assertEqual(len(files), 1)
            data = files[0].read_bytes()
            self.assertTrue(data.startswith(b"%PDF") and data.rstrip().endswith(b"%%EOF"))
            self.assertEqual(data.count(b"/Type /Page "), 2)


class MultipageModeTests(unittest.TestCase):
    DOCUMENT = bytes.fromhex("0000000001010101010001030301010200000000000000000000000000000000")
    AUTO = bytes.fromhex("0000000001010301010000000000000000000000000000000000000000000000")
    ADF_DOC = bytes.fromhex("0000000001010101020001030301010201000000000000000000000000000000")

    def service(self, modes):
        return PushScanService(None, None, [], ScanSettings(), auto_source=False,
                               native=NativeScanner("127.0.0.1"), multipage=modes)

    def check(self, modes, interrupt):
        svc = self.service(modes)
        return svc.use_native(svc.settings_for(interrupt), interrupt)  # no target: global modes

    def test_modes(self):
        from pushscan2folder.__main__ import MULTIPAGE_MODES as M
        self.assertTrue(self.check(M["document"], self.DOCUMENT))
        self.assertFalse(self.check(M["document"], self.AUTO))
        self.assertTrue(self.check(M["auto"], self.AUTO))
        self.assertFalse(self.check(M["auto"], self.DOCUMENT))
        self.assertTrue(self.check(M["both"], self.AUTO))
        self.assertFalse(self.check(M["off"], self.DOCUMENT))
        self.assertFalse(self.check(M["both"], self.ADF_DOC))  # ADF stays eSCL

    def test_env_aliases(self):
        import os
        from pushscan2folder import __main__ as cli
        for value, mode in (("1", "document"), ("no", "off"), ("Both", "both")):
            os.environ["PUSHSCAN_MULTIPAGE"] = value
            try:
                self.assertEqual(cli.multipage_env(), mode)
            finally:
                del os.environ["PUSHSCAN_MULTIPAGE"]


class PdfTests(unittest.TestCase):
    def test_jpeg_info(self):
        self.assertEqual(pdf.jpeg_info(fake_jpeg(16, 8, 1)), (16, 8, 1, (300, 300)))

    def test_pdf_structure(self):
        doc = pdf.jpegs_to_pdf([fake_jpeg(2480, 3507), fake_jpeg(10, 10, 1)])
        self.assertIn(b"/Count 2", doc)
        self.assertIn(b"/MediaBox [0 0 595.20 841.68]", doc)
        self.assertIn(b"/DeviceGray", doc)
        # xref offsets point at the objects
        xref = int(doc.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
        entries = doc[xref:].split(b"\n")[3:]
        for i, line in enumerate(entries[:5], 1):
            off = int(line[:10])
            self.assertTrue(doc[off:].startswith(b"%d 0 obj" % i))


if __name__ == "__main__":
    unittest.main()
