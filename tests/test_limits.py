"""Bounds on data a misbehaving printer can send (127.0.0.1 only)."""
import http.client
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from pushscan2folder import escl, native
from pushscan2folder.client import ChmpClient, ChmpError, read_body
from pushscan2folder.escl import EsclClient, EsclError, ScanSettings
from pushscan2folder.native import NativeError, NativeScanner, PageSettings


class BigBody(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    size = 0
    chunked = False

    def log_message(self, *args):
        pass

    def _answer(self):
        body = b"x" * self.size
        self.send_response(200)
        if self.chunked:
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for i in range(0, len(body), 100):
                part = body[i:i + 100]
                self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
            self.wfile.write(b"0\r\n\r\n")
        else:
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    do_GET = _answer

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._answer()


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass   # the client hangs up early on purpose


class ReadBodyTests(unittest.TestCase):
    def setUp(self):
        self.server = QuietServer(("127.0.0.1", 0), BigBody)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

    def get(self, limit):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", "/")
            return read_body(conn.getresponse(), limit, ValueError)
        finally:
            conn.close()

    def test_limits(self):
        for chunked in (False, True):
            BigBody.chunked = chunked
            BigBody.size = 1000
            self.assertEqual(len(self.get(1000)), 1000)
            with self.assertRaises(ValueError):
                self.get(999)

    def test_chmp_response_bounded(self):
        BigBody.chunked, BigBody.size = True, 200 * 1024
        with self.assertRaises(ChmpError):
            ChmpClient("127.0.0.1", self.port, timeout=5).poll(1)

    def test_escl_status_bounded(self):
        BigBody.chunked, BigBody.size = False, escl.MAX_RESPONSE + 1
        with self.assertRaises(EsclError):
            EsclClient("127.0.0.1", self.port, timeout=5).status()


class EsclCountTests(unittest.TestCase):
    def test_document_count_and_job_bytes(self):
        limits = []

        def fake_request(method, path, body=None, headers=None, limit=escl.MAX_RESPONSE):
            if method == "POST":
                return 201, {"Location": "/eSCL/ScanJobs/1"}, b""
            limits.append(limit)
            if 10 > limit:
                raise EsclError("over the limit")
            return 200, {}, b"x" * 10

        client = EsclClient("127.0.0.1")
        with mock.patch.object(client, "_request", fake_request), \
                mock.patch.object(escl, "MAX_DOCUMENTS", 3), \
                mock.patch.object(escl, "MAX_JOB_BYTES", 1000), \
                mock.patch.object(escl, "MAX_DOCUMENT_BYTES", 500):
            docs = client.scan(ScanSettings())
        self.assertEqual(len(docs), 3)
        self.assertEqual(limits, [500, 500, 500])
        limits.clear()
        with mock.patch.object(client, "_request", fake_request), \
                mock.patch.object(escl, "MAX_DOCUMENTS", 3), \
                mock.patch.object(escl, "MAX_JOB_BYTES", 25):
            docs = client.scan(ScanSettings())
        self.assertEqual(limits, [25, 15, 5])      # third one is too large: kept two
        self.assertEqual(len(docs), 2)
        limits.clear()
        with mock.patch.object(client, "_request", fake_request), \
                mock.patch.object(escl, "MAX_JOB_BYTES", 20):
            docs = client.scan(ScanSettings())
        self.assertEqual((limits, len(docs)), ([20, 10], 2))   # budget used up: stop
        with mock.patch.object(client, "_request", fake_request), \
                mock.patch.object(escl, "MAX_DOCUMENT_BYTES", 5):
            with self.assertRaises(EsclError):                 # nothing received yet
                client.scan(ScanSettings())


class NativeLimitTests(unittest.TestCase):
    def scanner(self):
        s = NativeScanner("127.0.0.1", poll_delay=0)
        s.xml = mock.Mock(return_value="")
        s.command = mock.Mock(return_value=b"")
        s.exchange = mock.Mock(return_value=b"")
        return s

    def test_page_count_bounded(self):
        s = self.scanner()
        s._scan_page = mock.Mock(return_value=b"page")
        s._next_page = mock.Mock(return_value=native.NEXT_COLOR)   # "more" forever
        with mock.patch.object(native, "MAX_PAGES", 4):
            pages = s.scan(PageSettings())
        self.assertEqual(len(pages), 4)

    def test_scan_bytes_bounded(self):
        s = self.scanner()
        limits = []

        def page(settings, keepalive, limit):
            limits.append(limit)
            if limit < 400:
                raise NativeError("page larger than the limit")
            return b"p" * 400

        s._scan_page = page
        s._next_page = mock.Mock(return_value=native.NEXT_COLOR)
        with mock.patch.object(native, "MAX_SCAN_BYTES", 1000), \
                mock.patch.object(native, "MAX_PAGE_BYTES", 500):
            pages = s.scan(PageSettings())
        self.assertEqual(limits, [500, 500, 200])
        self.assertEqual(len(pages), 2)                       # pages so far are kept
        limits.clear()
        with mock.patch.object(native, "MAX_SCAN_BYTES", 800):
            pages = s.scan(PageSettings())
        self.assertEqual((len(limits), len(pages)), (2, 2))  # budget used up: no 3rd page

    def test_page_size_bounded(self):
        s = self.scanner()
        chunk = bytes(4) + (100).to_bytes(4, "big") + b"y" * 100   # never ends the page
        s.command = mock.Mock(return_value=chunk)
        with mock.patch.object(native, "MAX_PAGE_BYTES", 1000):
            with self.assertRaises(NativeError):
                s._read_page(lambda: None)


if __name__ == "__main__":
    unittest.main()
