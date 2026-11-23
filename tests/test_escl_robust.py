"""Deadlines, empty documents, job cleanup and retry delay (no network)."""
import http.client
import time
import unittest
from unittest import mock

from pushscan2folder import client as client_mod
from pushscan2folder import escl, native
from pushscan2folder.client import read_body
from pushscan2folder.escl import EsclClient, EsclError, ScanSettings
from pushscan2folder.native import NativeError, NativeScanner


class FakeResponse:
    length = None

    def __init__(self, chunks):
        self.chunks = list(chunks)

    def read(self, n):
        return self.chunks.pop(0)[:n] if self.chunks else b""


class ReadBodyDeadlineTests(unittest.TestCase):
    def test_slow_body_is_cut_off(self):
        resp = FakeResponse([b"x"] * 1000)
        with self.assertRaises(ValueError):
            read_body(resp, 10_000, ValueError, deadline=-1)

    def test_default_deadline_is_patchable(self):
        resp = FakeResponse([b"x"] * 5)
        with mock.patch.object(client_mod, "READ_DEADLINE", -1):
            with self.assertRaises(ValueError):
                read_body(resp, 10_000, ValueError)

    def test_normal_body_and_limit(self):
        self.assertEqual(read_body(FakeResponse([b"ab", b"cd"]), 4), b"abcd")
        with self.assertRaises(ValueError):
            read_body(FakeResponse([b"abcde"]), 4, ValueError)


class ReadPageTests(unittest.TestCase):
    def scanner(self, reply):
        s = NativeScanner("127.0.0.1", poll_delay=0)
        s.command = mock.Mock(return_value=reply)
        return s

    def test_empty_chunk_is_no_progress(self):
        # size says 1, but there is no data and no page end
        s = self.scanner(bytes(4) + (1).to_bytes(4, "big"))
        slept = []
        real_sleep = time.sleep
        with mock.patch.object(native, "PAGE_DEADLINE", 0.2), \
                mock.patch.object(native.time, "sleep", side_effect=lambda t: (slept.append(t), real_sleep(0.01))):
            with self.assertRaises(NativeError):
                s._read_page(lambda: None)
        self.assertTrue(slept)                       # it waits instead of spinning

    def test_empty_chunk_does_not_reset_idle(self):
        s = self.scanner(bytes(4) + (1).to_bytes(4, "big"))
        ticks = iter([0, 0, 0, 1000, 1000, 1000, 1000])
        with mock.patch.object(native.time, "monotonic", side_effect=lambda: next(ticks)), \
                mock.patch.object(native.time, "sleep"):
            with self.assertRaises(NativeError) as cm:
                s._read_page(lambda: None)
        self.assertIn("120 s", str(cm.exception))

    def test_page_deadline_with_trickle(self):
        s = self.scanner(bytes(4) + (1).to_bytes(4, "big") + b"y")
        with mock.patch.object(native, "PAGE_DEADLINE", 0.05):
            with self.assertRaises(NativeError):
                s._read_page(lambda: None)


class HttpRetryTests(unittest.TestCase):
    def test_delay_before_retry(self):
        s = NativeScanner("127.0.0.1")
        conn = mock.Mock()
        conn.request.side_effect = [OSError("reset"), None]
        resp = mock.Mock(status=200, length=2)
        resp.read.side_effect = [b"ok", b""]
        conn.getresponse.return_value = resp
        with mock.patch.object(http.client, "HTTPConnection", return_value=conn), \
                mock.patch.object(native, "RETRY_DELAY", 0.25), \
                mock.patch.object(native.time, "sleep") as sleep:
            self.assertEqual(s._http("GET", None, {}), b"ok")
        sleep.assert_called_once_with(0.25)


class EsclJobTests(unittest.TestCase):
    def run_scan(self, answers):
        client = EsclClient("127.0.0.1")
        calls = []
        answers = list(answers)

        def fake(method, path, body=None, headers=None, limit=0, timeout=None):
            calls.append((method, path))
            if method == "POST":
                return 201, {"Location": "/eSCL/ScanJobs/7"}, b""
            if method == "DELETE":
                return 200, {}, b""
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return a

        with mock.patch.object(client, "_request", fake):
            try:
                return client.scan(ScanSettings()), calls
            except EsclError:
                return None, calls

    def test_empty_document_is_an_error_and_job_dropped(self):
        docs, calls = self.run_scan([(200, {}, b"")])
        self.assertIsNone(docs)
        self.assertEqual(calls[-1], ("DELETE", "/eSCL/ScanJobs/7"))

    def test_normal_end_sends_no_delete(self):
        docs, calls = self.run_scan([(200, {}, b"doc"), (404, {}, b"")])
        self.assertEqual(docs, [b"doc"])
        self.assertNotIn("DELETE", [m for m, _ in calls])

    def test_failure_after_document_deletes_job(self):
        docs, calls = self.run_scan([(200, {}, b"doc"), OSError("gone")])
        self.assertEqual(docs, [b"doc"])
        self.assertEqual(calls[-1][0], "DELETE")

    def test_delete_errors_are_ignored(self):
        client = EsclClient("127.0.0.1")
        with mock.patch.object(client, "_request", side_effect=OSError("down")):
            client._cancel("/eSCL/ScanJobs/7")      # must not raise


if __name__ == "__main__":
    unittest.main()
