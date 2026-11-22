"""End-to-end tests against a fake printer on localhost (no real device needed)."""
import tempfile
import threading
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pushscan2folder import escl, protocol
from pushscan2folder.client import ChmpClient
from pushscan2folder.escl import EsclClient, ScanSettings
from pushscan2folder.service import (PushScanService, Target, Trim, check_targets, output_names,
                                     render_filename, check_filename,
                                     parse_trim,
                                    parse_targets, safe_dirname)

SESSION = 0x2DB


class FakePrinter(BaseHTTPRequestHandler):
    """Answers like the TR8550: register/poll/release on CHMP, a one-page eSCL job."""

    state = {}

    def log_message(self, *args):
        pass

    def _send(self, code, body=b"", headers=None):
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        st = self.state
        if self.path == protocol.PATH:
            st.setdefault("chmp", []).append((dict(self.headers), body))
            req_type = int.from_bytes(body[:2], "big")
            session = int.from_bytes(body[4:8], "big")
            status = 0
            if req_type == protocol.TYPE_REGISTER:
                session = SESSION + st.get("registered", 0)
                st["registered"] = st.get("registered", 0) + 1
            if req_type == protocol.TYPE_POLL and st.get("expire"):
                st["expire"] = False
                status = protocol.STATUS_SESSION_EXPIRED
            pending = st.get("pending")
            if req_type == protocol.TYPE_POLL and pending in (True, session):
                st["pending"] = False
                status = protocol.STATUS_SCAN_REQUESTED
            resp = (status.to_bytes(4, "big") + session.to_bytes(4, "big")
                    + bytes.fromhex("00000024c5f16de8") + st.get("interrupt", bytes(range(32))))
            self._send(200, resp)
        elif self.path == "/eSCL/ScanJobs":
            st["settings"] = body.decode()
            st["pages"] = 1
            self._send(201, headers={"Location": f"http://{self.headers['Host']}/eSCL/ScanJobs/abc"})
        else:
            self._send(404)

    def do_GET(self):
        st = self.state
        if self.path == "/eSCL/ScannerStatus":
            adf = "ScannerAdfLoaded" if st.get("adf") else "ScannerAdfEmpty"
            xml = f"<x><pwg:State>Idle</pwg:State><scan:AdfState>{adf}</scan:AdfState></x>"
            self._send(200, xml.encode())
        elif self.path == "/eSCL/ScanJobs/abc/NextDocument" and st.get("pages"):
            st["pages"] -= 1
            if st.get("delay"):
                import time
                time.sleep(st["delay"])
            self._send(200, b"%PDF-1.3 cut" if st.get("truncated") else b"%PDF-1.3 fake\n%%EOF\n")
        else:
            self._send(404)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        FakePrinter.state = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakePrinter)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        port = self.server.server_address[1]
        self.tmp = tempfile.TemporaryDirectory()
        self.port = port
        self.service = self.make_service([Target("TEST  HOST", Path(self.tmp.name))])

    def make_service(self, targets):
        return PushScanService(
            ChmpClient("127.0.0.1", self.port), EsclClient("127.0.0.1", self.port),
            targets, ScanSettings(), interval=0.01)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def test_headers_sent(self):
        self.service.step()
        headers, body = FakePrinter.state["chmp"][0]
        self.assertEqual(headers["X-CHMP-CommandType"], "BJNPNotify")
        self.assertEqual(headers["X-CHMP-EventType"], "PuScan")
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        self.assertEqual(len(body), protocol.REQUEST_SIZE)

    def test_register_then_poll_without_request(self):
        self.service.step()
        types = [int.from_bytes(b[:2], "big") for _, b in FakePrinter.state["chmp"]]
        self.assertEqual(types, [protocol.TYPE_REGISTER, protocol.TYPE_POLL])
        self.assertEqual(self.service.targets[0].session, SESSION)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_scan_request_saves_file(self):
        FakePrinter.state["pending"] = True
        self.service.step()
        files = list(Path(self.tmp.name).iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), b"%PDF-1.3 fake\n%%EOF\n")
        self.assertIn("<pwg:InputSource>Platen</pwg:InputSource>", FakePrinter.state["settings"])

    def test_auto_source_uses_adf_when_loaded(self):
        FakePrinter.state.update(pending=True, adf=True)
        self.service.step()
        self.assertIn("<pwg:InputSource>Feeder</pwg:InputSource>", FakePrinter.state["settings"])

    def test_run_releases_on_stop(self):
        t = threading.Thread(target=self.service.run)
        t.start()
        threading.Timer(0.2, self.service.stop).start()
        t.join(5)
        types = [int.from_bytes(b[:2], "big") for _, b in FakePrinter.state["chmp"]]
        self.assertEqual(types[-1], protocol.TYPE_RELEASE)
        self.assertIsNone(self.service.targets[0].session)


    def test_heartbeat_after_successful_polls(self):
        beat = Path(self.tmp.name) / "alive"
        self.service.heartbeat = beat
        t = threading.Thread(target=self.service.run)
        t.start()
        threading.Timer(0.2, self.service.stop).start()
        t.join(5)
        self.assertTrue(beat.is_file())

    def test_no_heartbeat_when_the_printer_is_unreachable(self):
        beat = Path(self.tmp.name) / "alive"
        svc = PushScanService(ChmpClient("127.0.0.1", 1), EsclClient("127.0.0.1", 1),
                              [Target("A", Path(self.tmp.name))], ScanSettings(), interval=0.01)
        svc.heartbeat = beat
        t = threading.Thread(target=svc.run)
        t.start()
        threading.Timer(0.2, svc.stop).start()
        t.join(5)
        self.assertFalse(beat.exists())

    def test_long_escl_scan_keeps_registrations_alive(self):
        from pushscan2folder import service as service_module
        old = service_module.KEEPALIVE_INTERVAL
        service_module.KEEPALIVE_INTERVAL = 0.05
        try:
            self.service.step()                    # register + first poll
            FakePrinter.state.update(pending=True, delay=0.4)
            polls_before = len(FakePrinter.state["chmp"])
            self.service.step()                    # scan request -> slow eSCL scan
            # step() itself polls once; everything beyond that is keepalive.
            self.assertGreater(len(FakePrinter.state["chmp"]) - polls_before, 2)
        finally:
            service_module.KEEPALIVE_INTERVAL = old

    def test_status_records_scans(self):
        FakePrinter.state["pending"] = True
        self.service.step()
        snap = self.service.status.snapshot()
        self.assertEqual(len(snap["history"]), 1)
        rec = snap["history"][0]
        self.assertEqual((rec.target, rec.method, rec.result, rec.pages), ("TEST  HOST", "eSCL", "ok", 1))
        self.assertEqual(len(rec.files), 1)
        self.assertIsNone(snap["busy"])
        self.assertTrue(snap["targets"][0].registered)

    def test_status_records_nothing_saved(self):
        FakePrinter.state.update(pending=True, truncated=True)
        self.service.step()
        self.assertEqual(self.service.status.snapshot()["history"][0].result, "nothing saved")

    def test_pending_targets_keep_sessions_and_release_removed(self):
        base = Path(self.tmp.name)
        service = self.make_service(parse_targets("a,b", base))
        service.step()
        sessions = {t.name: t.session for t in service.targets}
        service.request_targets(parse_targets("a,c", base))
        self.assertTrue(service.status.snapshot()["pending"])
        before = len(FakePrinter.state["chmp"])
        service.step()
        self.assertEqual([t.name for t in service.targets], ["a", "c"])
        self.assertEqual(service.targets[0].session, sessions["a"])
        new_bodies = [b for _, b in FakePrinter.state["chmp"][before:]]
        releases = [int.from_bytes(b[4:8], "big") for b in new_bodies
                    if int.from_bytes(b[:2], "big") == protocol.TYPE_RELEASE]
        self.assertEqual(releases, [sessions["b"]])
        snap = service.status.snapshot()
        self.assertFalse(snap["pending"])
        self.assertEqual([t.name for t in snap["targets"]], ["a", "c"])

    def _step_with(self, old, new):
        """Run with targets `old`, switch to `new`; returns (service, old sessions,
        released sessions, registered names during the switch)."""
        base = Path(self.tmp.name)
        service = self.make_service(parse_targets(old, base))
        service.step()
        sessions = {t.name: t.session for t in service.targets}
        service.request_targets(parse_targets(new, base))
        before = len(FakePrinter.state["chmp"])
        service.step()
        bodies = [b for _, b in FakePrinter.state["chmp"][before:]]
        releases = [int.from_bytes(b[4:8], "big") for b in bodies
                    if int.from_bytes(b[:2], "big") == protocol.TYPE_RELEASE]
        return service, sessions, releases

    def test_reorder_registers_all_again(self):
        service, sessions, releases = self._step_with("a,b,c", "c,a,b")
        self.assertEqual([t.name for t in service.targets], ["c", "a", "b"])
        self.assertEqual(sorted(releases), sorted(sessions.values()))
        self.assertNotIn(None, [t.session for t in service.targets])
        self.assertTrue(all(t.session not in sessions.values() for t in service.targets))

    def test_insert_in_the_middle_registers_all_again(self):
        service, sessions, releases = self._step_with("a,b", "a,x,b")
        self.assertEqual(sorted(releases), sorted(sessions.values()))

    def test_append_keeps_sessions(self):
        service, sessions, releases = self._step_with("a,b", "a,b,x")
        self.assertEqual(releases, [])
        self.assertEqual(service.targets[0].session, sessions["a"])
        self.assertEqual(service.targets[1].session, sessions["b"])
        self.assertNotIn(service.targets[2].session, sessions.values())

    def test_remove_in_the_middle_keeps_others(self):
        service, sessions, releases = self._step_with("a,b,c", "a,c")
        self.assertEqual(releases, [sessions["b"]])
        self.assertEqual([t.session for t in service.targets], [sessions["a"], sessions["c"]])

    def test_cancelled_scan_is_discarded(self):
        FakePrinter.state.update(pending=True, truncated=True)
        self.service.step()
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_panel_settings_are_used(self):
        # Captured from the TR8550: document, colour, ADF, Legal, PDF, 300 dpi
        FakePrinter.state.update(pending=True, interrupt=bytes.fromhex(
            "00000000010101010200030303010102010000000000000000000000000000"))
        self.service.step()
        xml = FakePrinter.state["settings"]
        self.assertIn("<pwg:InputSource>Feeder</pwg:InputSource>", xml)
        self.assertIn("<pwg:Height>4200</pwg:Height>", xml)
        self.assertIn("<scan:XResolution>300</scan:XResolution>", xml)

    def test_ignore_panel(self):
        self.service.use_panel = False
        FakePrinter.state.update(pending=True, interrupt=bytes.fromhex(
            "00000000010101010200030303010102010000000000000000000000000000"))
        self.service.step()
        self.assertIn("<pwg:Height>3508</pwg:Height>", FakePrinter.state["settings"])

    def test_expired_session_registers_again(self):
        self.service.step()
        FakePrinter.state["expire"] = True
        self.service.step()
        self.assertEqual(self.service.targets[0].session, SESSION + 1)

    def test_multiple_targets_route_to_own_folder(self):
        base = Path(self.tmp.name)
        service = self.make_service(parse_targets("scan1,paperless,archiv", base))
        FakePrinter.state["pending"] = SESSION + 1  # second registration = paperless
        service.step()
        sessions = [t.session for t in service.targets]
        self.assertEqual(sessions, [SESSION, SESSION + 1, SESSION + 2])
        self.assertEqual(len(list((base / "paperless").iterdir())), 1)
        self.assertFalse((base / "scan1").exists())
        self.assertFalse((base / "archiv").exists())

    def test_multiple_targets_all_released(self):
        service = self.make_service(parse_targets("a,b", Path(self.tmp.name)))
        service.step()
        service.release()
        released = [int.from_bytes(b[4:8], "big") for _, b in FakePrinter.state["chmp"]
                    if int.from_bytes(b[:2], "big") == protocol.TYPE_RELEASE]
        self.assertEqual(sorted(released), [SESSION, SESSION + 1])


class TargetParsingTests(unittest.TestCase):
    def test_names_and_dirs(self):
        base = Path("/scans")
        t = parse_targets(" scan1 , paperless=consume ,archiv=/data/archiv,Mein Ordner", base)
        self.assertEqual([x.name for x in t], ["scan1", "paperless", "archiv", "Mein Ordner"])
        self.assertEqual([x.outdir for x in t],
                         [Path(p) for p in ("/scans/scan1", "/scans/consume", "/data/archiv",
                                            "/scans/Mein_Ordner")])

    def test_invalid(self):
        for spec in ("", " , ", "a,a", "=dir", "x" * 32):
            with self.assertRaises(ValueError, msg=spec):
                parse_targets(spec, Path("/s"))

    def test_presets(self):
        t = parse_targets("scan1, paperless=/consume@300dpi, archiv@600dpi+JPEG+10x15+mp:both,"
                          "Mein Ordner@mp:off", Path("/scans"))
        self.assertEqual([x.name for x in t], ["scan1", "paperless", "archiv", "Mein Ordner"])
        self.assertEqual(t[1].outdir, Path("/consume"))
        self.assertEqual(t[2].outdir, Path("/scans/archiv"))
        self.assertEqual(t[0].preset, {})
        self.assertIsNone(t[0].multipage)
        self.assertEqual(t[1].preset, {"resolution": 300})
        self.assertEqual(t[2].preset, {"resolution": 600, "fmt": "jpeg", "width": 1181, "height": 1772})
        self.assertEqual(t[2].multipage, frozenset({"document", "auto"}))
        self.assertEqual(t[3].multipage, frozenset())

    def test_invalid_names(self):
        for spec in ("a.b", "Müller", "x&y=dir"):
            with self.assertRaises(ValueError, msg=spec):
                parse_targets(spec, Path("/s"))

    def test_clashing_folders(self):
        with self.assertRaises(ValueError) as cm:
            check_targets(parse_targets("Mein Ordner,Mein_Ordner", Path("/s")))
        self.assertIn("both use the folder", str(cm.exception))
        with self.assertRaises(ValueError):
            check_targets(parse_targets("a=x,b=x", Path("/s")))
        self.assertEqual(check_targets(parse_targets("a,b=x", Path("/s"))), [])

    def test_long_name_warning(self):
        warnings = check_targets(parse_targets("y" * 26, Path("/s")))
        self.assertEqual(len(warnings), 1)
        self.assertIn("panel shows only the start", warnings[0])

    def test_invalid_presets(self):
        for spec in ("a@200dpi", "a@blue", "a@mp:never", "a=/x@y/z", "a@", "a@gray", "a@color",
                     "a@gray+300dpi", "x" * 32 + "@300dpi"):
            with self.assertRaises(ValueError, msg=spec):
                parse_targets(spec, Path("/s"))

    def test_safe_dirname(self):
        self.assertEqual(safe_dirname("../etc"), "etc")
        self.assertEqual(safe_dirname("  "), "scan")
        # valid Windows names on every platform
        for name, expected in (("CON", "_CON"), ("aux", "_aux"), ("Nul", "_Nul"),
                               ("com1", "_com1"), ("LPT9", "_LPT9"), ("con.txt", "_con.txt"),
                               ("a.", "a"), ("a. .", "a"), ("COM1 ", "_COM1"),
                               ("console", "console"), ("a:b*c", "a_b_c")):
            self.assertEqual(safe_dirname(name), expected, name)


class PresetPrecedenceTests(unittest.TestCase):
    AUTO_COLOR = bytes.fromhex("0000000001010301010000000000000000000000000000000000000000000000")
    AUTO_GRAY = bytes.fromhex("0000000001010302010000000000000000000000000000000000000000000000")
    DOC_COLOR_300 = bytes.fromhex("0000000001010101010001030301010200000000000000000000000000000000")

    def setUp(self):
        self.service = PushScanService(None, None, [], ScanSettings(resolution=300),
                                       auto_source=False)
        self.target = parse_targets("p@150dpi+jpeg", Path("/s"))[0]

    def test_auto_scan_uses_preset_over_panel(self):
        s = self.service.settings_for(self.AUTO_COLOR, self.target)
        self.assertEqual((s.color, s.resolution, s.fmt), ("color", 150, "jpeg"))

    def test_auto_scan_keeps_panel_colour(self):
        target = parse_targets("p@600dpi", Path("/s"))[0]
        s = self.service.settings_for(self.AUTO_GRAY, target)
        self.assertEqual((s.color, s.resolution), ("gray", 600))
        s = self.service.settings_for(self.AUTO_COLOR, target)
        self.assertEqual((s.color, s.resolution), ("color", 600))

    def test_document_mode_panel_wins(self):
        s = self.service.settings_for(self.DOC_COLOR_300, self.target)
        self.assertEqual((s.color, s.resolution, s.fmt), ("color", 300, "pdf"))

    def test_no_panel_data_uses_preset(self):
        s = self.service.settings_for(b"", self.target)
        self.assertEqual((s.color, s.resolution, s.fmt), ("color", 150, "jpeg"))

    def test_target_without_preset_uses_global(self):
        s = self.service.settings_for(self.AUTO_COLOR, parse_targets("x", Path("/s"))[0])
        self.assertEqual((s.color, s.resolution, s.fmt), ("color", 300, "pdf"))

    def test_target_multipage_overrides_global(self):
        from pushscan2folder.native import NativeScanner
        svc = PushScanService(None, None, [], ScanSettings(), auto_source=False,
                              native=NativeScanner("127.0.0.1"))
        t = parse_targets("a@mp:auto", Path("/s"))[0]
        self.assertTrue(svc.use_native(svc.settings_for(self.AUTO_COLOR, t), self.AUTO_COLOR, t))
        self.assertFalse(svc.use_native(svc.settings_for(self.DOC_COLOR_300, t), self.DOC_COLOR_300, t))


class HelperTests(unittest.TestCase):
    def test_output_names_unique(self):
        with tempfile.TemporaryDirectory() as d:
            now = datetime(2026, 11, 22, 0, 1, 3)
            (Path(d) / "scan_20261122_000103.pdf").write_bytes(b"x")
            self.assertEqual(output_names(Path(d), "pdf", 1, now)[0].name,
                             "scan_20261122_000103-1.pdf")
            names = [p.name for p in output_names(Path(d), "jpeg", 2, now)]
            self.assertEqual(names, ["scan_20261122_000103_01.jpg", "scan_20261122_000103_02.jpg"])

    def test_filename_template(self):
        now = datetime(2026, 11, 22, 18, 30, 5)
        self.assertEqual(render_filename("scan_{now:%Y%m%d_%H%M%S}", "x", now),
                         "scan_20261122_183005")
        self.assertEqual(render_filename("{name}_{date}_{time}", "My PC", now),
                         "My_PC_2026-11-22_183005")
        # characters Windows does not allow, and device names
        self.assertEqual(render_filename("a/b\\c:d", "x", now), "a_b_c_d")
        self.assertEqual(render_filename("con", "x", now), "_con")
        self.assertEqual(len(render_filename("x" * 300, "x", now)), 120)

    def test_filename_template_rejects_unsafe_fields(self):
        for bad in ("{now.__class__}", "{0}", "{}", "{foo}", "{now:{x}}", "{", "  ", "{name[0]}"):
            with self.assertRaises(ValueError, msg=bad):
                check_filename(bad)
        check_filename("{name}")

    def test_output_names_with_template(self):
        with tempfile.TemporaryDirectory() as d:
            now = datetime(2026, 11, 22, 0, 1, 3)
            first = output_names(Path(d), "pdf", 1, now, "{name}", "Rechnung")[0]
            self.assertEqual(first.name, "Rechnung.pdf")
            first.write_bytes(b"x")
            self.assertEqual(output_names(Path(d), "pdf", 1, now, "{name}", "Rechnung")[0].name,
                             "Rechnung-1.pdf")

    def test_job_path(self):
        self.assertEqual(escl.job_path("http://1.2.3.4/eSCL/ScanJobs/x/"), "/eSCL/ScanJobs/x")
        self.assertEqual(escl.job_path("/eSCL/ScanJobs/y"), "/eSCL/ScanJobs/y")

    def test_settings_xml(self):
        xml = escl.build_scan_settings(ScanSettings(color="gray", resolution=300, fmt="jpeg"))
        self.assertIn("<scan:ColorMode>Grayscale8</scan:ColorMode>", xml)
        self.assertIn("<scan:XResolution>300</scan:XResolution>", xml)
        self.assertIn("<pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>", xml)


if __name__ == "__main__":
    unittest.main()


class TrimTests(unittest.TestCase):
    def service(self, trim, source="platen"):
        return PushScanService(None, None, [], ScanSettings(source=source), auto_source=False,
                               trim=trim)

    def test_escl_xml_offsets(self):
        xml = escl.build_scan_settings(ScanSettings(x_offset=12, y_offset=34))
        self.assertIn("<pwg:XOffset>12</pwg:XOffset><pwg:YOffset>34</pwg:YOffset>", xml)
        self.assertIn("<pwg:XOffset>0</pwg:XOffset>", escl.build_scan_settings(ScanSettings()))

    def test_units(self):
        self.assertEqual(Trim(3, 0, 2, 25.4).units(), (35, 0, 24, 300))

    def test_platen_is_trimmed(self):
        s = self.service(Trim(left=1, top=2, right=3, bottom=4)).settings_for(b"")
        left, top, right, bottom = Trim(1, 2, 3, 4).units()
        self.assertEqual((s.x_offset, s.y_offset), (left, top))
        self.assertEqual((s.width, s.height),
                         (escl.A4_WIDTH - left - right, escl.A4_HEIGHT - top - bottom))

    def test_adf_is_not_trimmed(self):
        s = self.service(Trim(right=3, bottom=2), source="adf").settings_for(b"")
        self.assertEqual((s.x_offset, s.y_offset, s.width, s.height),
                         (0, 0, escl.A4_WIDTH, escl.A4_HEIGHT))

    def test_no_trim_by_default(self):
        s = self.service(None).settings_for(b"")
        self.assertEqual((s.x_offset, s.width), (0, escl.A4_WIDTH))

    def test_too_large_trim_is_skipped(self):
        svc = self.service(Trim(left=50, right=50))  # leaves 2480 - 2 * 591 = 1298: fine
        self.assertEqual(svc.settings_for(b"").width, escl.A4_WIDTH - 2 * 591)
        svc = self.service(Trim(left=50, right=50, top=50, bottom=50))
        svc.settings = ScanSettings(width=1000, height=1000)
        with self.assertLogs("pushscan2folder.service", "WARNING"):
            s = svc.settings_for(b"")
        self.assertEqual((s.x_offset, s.width, s.height), (0, 1000, 1000))

    def test_parse_trim(self):
        self.assertEqual(parse_trim("right=3,bottom=2.5"), Trim(right=3, bottom=2.5))
        self.assertEqual(parse_trim(" Left = 1 , top=0 "), Trim(left=1))
        self.assertFalse(parse_trim(""))
        self.assertFalse(parse_trim(None))
        for bad in ("3", "right", "right=x", "up=1", "right=-1", "right=51", "right=1,right=2",
                    "right=nan", "right=inf"):
            with self.assertRaises(ValueError, msg=bad):
                parse_trim(bad)
