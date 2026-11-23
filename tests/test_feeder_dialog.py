"""Next page dialog after a feeder scan: config key, choice, native dialog
job and the feeder rounds of the service (fake printer and mocks only)."""
import struct
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from pushscan2folder import config, native
from pushscan2folder.config import ConfigError, dump_config, load_config_text
from pushscan2folder.escl import ScanSettings
from pushscan2folder.native import NativeCancelled, NativeScanner
from pushscan2folder.service import PushScanService, Target

from test_native import FakeNativePrinter, fake_jpeg, split
from test_service import panel_bytes

DOCUMENT_ADF = panel_bytes(1, source=2)
AUTO_ADF = panel_bytes(3, source=2)
DOCUMENT_GLASS = panel_bytes(1, source=1)


class ConfigTests(unittest.TestCase):
    def test_default_is_off(self):
        cfg = load_config_text("")
        self.assertIsNone(cfg.feeder_next_page)
        self.assertEqual(cfg.feeder_next_page_types(), frozenset())

    def test_global_and_target(self):
        cfg = load_config_text('feeder_next_page = ["document", "auto"]\n'
                               '[[target]]\nname = "A"\nfeeder_next_page = []\n'
                               '[[target]]\nname = "B"\n')
        self.assertEqual(cfg.feeder_next_page_types(), frozenset({"document", "auto"}))
        a, b = cfg.build_targets(Path("/s"))
        self.assertEqual(a.feeder_multipage, frozenset())
        self.assertIsNone(b.feeder_multipage)

    def test_round_trip(self):
        cfg = load_config_text('feeder_next_page = ["document"]\n'
                               '[[target]]\nname = "A"\nfeeder_next_page = ["photo"]\n')
        again = load_config_text(dump_config(cfg))
        self.assertEqual(again.feeder_next_page, frozenset({"document"}))
        self.assertEqual(again.targets[0].feeder_next_page, frozenset({"photo"}))

    def test_bad_value(self):
        for text in ('feeder_next_page = "document"', 'feeder_next_page = ["glass"]'):
            with self.assertRaises(ConfigError):
                load_config_text(text)
        self.assertIn("feeder_next_page", config.TARGET_KEYS)


class ChoiceTests(unittest.TestCase):
    def use(self, interrupt, feeder=frozenset({"document"}), target=None,
            scanner=True, source=None):
        svc = PushScanService(None, None, [], ScanSettings(), auto_source=False,
                              native=NativeScanner("127.0.0.1") if scanner else None,
                              feeder_multipage=feeder)
        settings = svc.settings_for(interrupt, target)
        if source:
            settings = ScanSettings(source=source)
        return svc.use_feeder_dialog(settings, interrupt, target)

    def test_feeder_and_listed_type(self):
        self.assertTrue(self.use(DOCUMENT_ADF))
        self.assertFalse(self.use(AUTO_ADF))
        self.assertFalse(self.use(DOCUMENT_GLASS))

    def test_default_service_has_no_dialog(self):
        svc = PushScanService(None, None, [], ScanSettings(), auto_source=False,
                              native=NativeScanner("127.0.0.1"))
        self.assertFalse(svc.use_feeder_dialog(svc.settings_for(DOCUMENT_ADF), DOCUMENT_ADF))

    def test_target_list_replaces_the_global_one(self):
        self.assertFalse(self.use(DOCUMENT_ADF, target=Target("A", Path("/s"),
                                                               feeder_multipage=frozenset())))
        self.assertTrue(self.use(AUTO_ADF, feeder=frozenset(),
                                 target=Target("A", Path("/s"),
                                               feeder_multipage=frozenset({"auto"}))))

    def test_needs_native_scanner_and_panel(self):
        self.assertFalse(self.use(DOCUMENT_ADF, scanner=False))
        self.assertFalse(self.use(b"", source="adf"))


class AskNextPageTests(unittest.TestCase):
    def setUp(self):
        FakeNativePrinter.state = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeNativePrinter)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.scanner = NativeScanner("127.0.0.1", self.server.server_address[1],
                                     poll_delay=0.01)

    def test_dummy_page_then_decision(self):
        FakeNativePrinter.state.update(pages=[split(fake_jpeg())],
                                       decisions=[native.NEXT_WAITING, native.NEXT_GRAY])
        self.assertEqual(self.scanner.ask_next_page("gray"), native.NEXT_GRAY)
        log = FakeNativePrinter.state["log"]
        params = [b for b in log if b[:2] == b"\xd8\x20"]
        self.assertEqual(len(params), 1)
        body = params[0][16:]
        self.assertEqual(struct.unpack_from(">IIII", body, 0x0C), (0, 0, 150, 150))
        self.assertEqual(body[0x1c], 0x04)                  # gray, like the next round
        self.assertEqual(log[-2][:2], b"\xef\x20")
        self.assertTrue(b"EndJob" in log[-1])

    def test_job_is_ended_when_the_dummy_page_is_cancelled(self):
        FakeNativePrinter.state.update(pages=[split(fake_jpeg())], decisions=[], cancel=True)
        with self.assertRaises(NativeCancelled):
            self.scanner.ask_next_page()
        self.assertTrue(b"EndJob" in FakeNativePrinter.state["log"][-1])


class FeederRoundTests(unittest.TestCase):
    def service(self, rounds, decisions, loaded=None):
        """rounds: list of page lists (or an exception) per eSCL scan."""
        self.escl = mock.Mock()
        self.escl.scan.side_effect = rounds
        self.escl.adf_loaded.side_effect = loaded or (lambda: True)
        self.native = mock.Mock()
        self.native.ask_next_page.side_effect = decisions
        return PushScanService(None, self.escl, [], ScanSettings(), native=self.native)

    def test_rounds_until_finish_switch_colour(self):
        p = [fake_jpeg(fill=bytes([i]) * 50) for i in range(4)]
        svc = self.service([[p[0], p[1]], [p[2]], [p[3]]],
                           [native.NEXT_GRAY, native.NEXT_COLOR, native.NEXT_FINISH])
        pages = svc.scan_feeder(ScanSettings(source="adf", fmt="jpeg", color="color"))
        self.assertEqual(pages, p)
        colors = [c.args[0].color for c in self.escl.scan.call_args_list]
        self.assertEqual(colors, ["color", "gray", "color"])
        self.assertTrue(all(c.args[0].fmt == "jpeg" for c in self.escl.scan.call_args_list))
        self.assertEqual(svc._pages, 4)

    def test_pdf_holds_all_rounds(self):
        svc = self.service([[fake_jpeg()], [fake_jpeg(width=20)]],
                           [native.NEXT_COLOR, native.NEXT_FINISH])
        (data,) = svc.scan_feeder(ScanSettings(source="adf", fmt="pdf"))
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(data.count(b"/Type /Page "), 2)
        self.assertEqual(self.escl.scan.call_args_list[0].args[0].fmt, "jpeg")

    def test_cancelled_first_round_asks_nothing(self):
        svc = self.service([[fake_jpeg()[:-2]]], [])
        self.assertEqual(svc.scan_feeder(ScanSettings(source="adf")), [])
        self.native.ask_next_page.assert_not_called()

    def test_empty_feeder_asks_again_then_gives_up(self):
        svc = self.service([[fake_jpeg()]], [native.NEXT_COLOR] * 5, loaded=lambda: False)
        pages = svc.scan_feeder(ScanSettings(source="adf", fmt="jpeg"))
        self.assertEqual(len(pages), 1)
        self.assertEqual(self.escl.scan.call_count, 1)        # empty feeder: no eSCL job
        self.assertEqual(self.native.ask_next_page.call_count, 3)

    def test_failed_later_round_keeps_pages(self):
        svc = self.service([[fake_jpeg()], OSError("busy"), [fake_jpeg(width=20)]],
                           [native.NEXT_COLOR, native.NEXT_COLOR, native.NEXT_FINISH])
        pages = svc.scan_feeder(ScanSettings(source="adf", fmt="jpeg"))
        self.assertEqual(len(pages), 2)

    def test_dialog_failure_keeps_pages(self):
        svc = self.service([[fake_jpeg()]], native.NativeError("gone"))
        self.assertEqual(len(svc.scan_feeder(ScanSettings(source="adf", fmt="jpeg"))), 1)

    def test_page_limit(self):
        svc = self.service([[fake_jpeg()] * 3] * 3, [native.NEXT_COLOR] * 3)
        with mock.patch.object(native, "MAX_PAGES", 5):
            pages = svc.scan_feeder(ScanSettings(source="adf", fmt="jpeg"))
        self.assertEqual(len(pages), 6)
        self.assertEqual(self.native.ask_next_page.call_count, 1)

    def test_scan_to_saves_all_rounds(self):
        svc = self.service([[fake_jpeg()], [fake_jpeg(width=20)]],
                           [native.NEXT_COLOR, native.NEXT_FINISH])
        svc.feeder_multipage = frozenset({"document"})
        with tempfile.TemporaryDirectory() as tmp:
            target = Target("A", Path(tmp))
            paths = svc.scan_to(target, interrupt=DOCUMENT_ADF)
            fmt = svc.settings_for(DOCUMENT_ADF, target).fmt
            self.assertEqual(len(paths), 1 if fmt == "pdf" else 2)
        self.assertEqual(svc.status.snapshot()["history"][0].method,
                         "eSCL, next page dialog")

    def test_stop_request_finishes(self):
        svc = self.service([[fake_jpeg()]], [])
        svc.stop_event.set()
        self.assertEqual(len(svc.scan_feeder(ScanSettings(source="adf", fmt="jpeg"))), 1)
        self.native.ask_next_page.assert_not_called()


if __name__ == "__main__":
    unittest.main()
