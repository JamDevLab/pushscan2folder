"""The running service applies a changed config file (ConfigWatcher)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pushscan2folder import __main__ as cli
from pushscan2folder.escl import ScanSettings
from pushscan2folder.service import PushScanService, Target


class FakeService:
    def __init__(self):
        self.options = None
        self.printers = []
        self.targets = None

    def update_options(self, **options):
        self.options = options

    def change_printer(self, chmp, escl, native):
        self.printers.append((chmp, escl, native))

    def request_targets(self, targets):
        self.targets = targets


class WatcherTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in [k for k in os.environ if k.startswith("PUSHSCAN_")]:
            del os.environ[key]
        tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        os.environ["XDG_CONFIG_HOME"] = str(self.dir / "xdg")
        self.path = self.dir / "config.toml"
        self.write('printer = "10.0.0.5"\noutput = "%s"\n[defaults]\nresolution = 300\n'
                   '[[target]]\nname = "Scans"\n' % (self.dir / "out").as_posix())
        self.argv = ["--config", str(self.path), "run"]
        self.args, self.cfg = cli.parse_args(self.argv)
        cli.check_run_options(self.args)
        self.service = FakeService()
        self.clients = mock.Mock(return_value=("chmp", "escl", "native"))
        self.watcher = cli.ConfigWatcher(self.path, self.argv, self.args, self.cfg,
                                         self.service, clients=self.clients)

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")
        # make sure the stamp changes even on file systems with coarse times
        st = self.path.stat()
        os.utime(self.path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))

    def test_unchanged_file_does_nothing(self):
        self.assertFalse(self.watcher.check())
        self.assertIsNone(self.service.options)

    def test_changed_settings_and_targets_are_applied(self):
        self.write('printer = "10.0.0.5"\n[defaults]\nresolution = 600\n'
                   'filename = "{name}_{date}"\n'
                   '[[target]]\nname = "Scans"\n[[target]]\nname = "Paperless"\n')
        with self.assertLogs(level="INFO") as logs:
            self.assertTrue(self.watcher.check())
        self.assertEqual(self.service.options["settings"].resolution, 600)
        self.assertEqual(self.service.options["filename"], "{name}_{date}")
        self.assertFalse(self.service.options["adf_trim"])
        self.assertEqual([t.name for t in self.service.targets], ["Scans", "Paperless"])
        self.assertEqual(self.service.printers, [])
        self.assertTrue(any("new settings are in use" in line for line in logs.output))
        self.assertFalse(self.watcher.check())   # applied once

    def test_printer_change_switches_the_clients(self):
        self.write('printer = "10.0.0.9"\n[[target]]\nname = "Scans"\n')
        self.assertTrue(self.watcher.check())
        self.clients.assert_called_once_with("10.0.0.9")
        self.assertEqual(self.service.printers, [("chmp", "escl", "native")])

    def test_environment_still_wins(self):
        os.environ["PUSHSCAN_RESOLUTION"] = "150"
        self.write('printer = "10.0.0.5"\n[defaults]\nresolution = 600\n')
        self.assertTrue(self.watcher.check())
        self.assertEqual(self.service.options["settings"].resolution, 150)

    def test_invalid_file_keeps_the_running_settings(self):
        self.write('printer = "10.0.0.5"\n[defaults]\nresolution = "lots"\n')
        with self.assertLogs(level="ERROR") as logs:
            self.assertFalse(self.watcher.check())
        self.assertIsNone(self.service.options)
        self.assertIn("running settings stay", logs.output[0])
        self.assertFalse(self.watcher.check())   # logged once, not every cycle

    def test_bad_filename_template_is_refused(self):
        self.write('printer = "10.0.0.5"\n[defaults]\nfilename = "{secret}"\n')
        with self.assertLogs(level="ERROR"):
            self.assertFalse(self.watcher.check())
        self.assertIsNone(self.service.options)

    def test_deleted_file_changes_nothing(self):
        self.path.unlink()
        self.assertFalse(self.watcher.check())
        self.assertIsNone(self.service.options)

    def test_restart_only_options_are_named(self):
        self.write('printer = "10.0.0.5"\n[web]\nenabled = true\nport = 9090\n')
        with self.assertLogs(level="WARNING") as logs:
            self.assertTrue(self.watcher.check())
        warning = [line for line in logs.output if "restart" in line][0]
        self.assertIn("web page on or off", warning)
        self.assertIn("web port", warning)

    def test_web_context_is_updated(self):
        ctx = mock.Mock()
        self.watcher.ctx = ctx
        self.write('printer = "10.0.0.9"\n[defaults]\nresolution = 600\n')
        self.watcher.check()
        self.assertEqual(ctx.printer, "10.0.0.9")
        self.assertEqual(ctx.effective["resolution"], "600")


class ServiceHookTests(unittest.TestCase):
    def make(self):
        service = PushScanService(mock.Mock(), mock.Mock(), [Target("A", Path("."))],
                                  ScanSettings(), interval=0.01)
        service.step = mock.Mock(side_effect=lambda: service.stop())
        return service

    def test_before_step_runs_each_cycle(self):
        service = self.make()
        calls = []
        service.before_step = lambda: calls.append(1)
        service.run()
        self.assertEqual(calls, [1])

    def test_failing_hook_does_not_end_the_service(self):
        service = self.make()
        service.before_step = mock.Mock(side_effect=RuntimeError("boom"))
        with self.assertLogs(level="WARNING"):
            service.run()
        service.step.assert_called_once()

    def test_update_options_rejects_unknown_names(self):
        service = self.make()
        service.update_options(filename="x_{date}")
        self.assertEqual(service.filename, "x_{date}")
        with self.assertRaises(TypeError):
            service.update_options(chmp=None)

    def test_change_printer_releases_and_swaps(self):
        service = self.make()
        old = service.chmp
        service.targets[0].session = 7
        service.change_printer("new-chmp", "new-escl", None)
        old.release.assert_called_once_with(7)
        self.assertEqual(service.chmp, "new-chmp")
        self.assertIsNone(service.targets[0].session)


if __name__ == "__main__":
    unittest.main()
