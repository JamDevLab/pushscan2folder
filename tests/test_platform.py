"""Platform helpers, Windows name rules, logging and autostart commands."""
import errno
import logging
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pushscan2folder import __main__ as cli
from pushscan2folder import autostart, platform_support as ps


class DefaultPathTests(unittest.TestCase):
    def test_config_path_linux_and_macos(self):
        for plat in ("linux", "darwin"):
            with mock.patch.object(sys, "platform", plat), \
                    mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/xdg"}):
                self.assertEqual(ps.default_config_path(),
                                 Path("/xdg") / "pushscan2folder" / "config.toml")
            with mock.patch.object(sys, "platform", plat), \
                    mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(Path, "home", return_value=Path("/home/u")):
                self.assertEqual(ps.default_config_path(),
                                 Path("/home/u/.config/pushscan2folder/config.toml"))

    def test_config_path_windows(self):
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.dict(os.environ, {"APPDATA": "/appdata", "XDG_CONFIG_HOME": "/x"}):
            self.assertEqual(ps.default_config_path(),
                             Path("/appdata") / "pushscan2folder" / "config.toml")
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(Path, "home", return_value=Path("/home/u")):
            self.assertEqual(ps.default_config_path(),
                             Path("/home/u") / "AppData" / "Roaming" / "pushscan2folder"
                             / "config.toml")

    def test_default_output(self):
        with mock.patch.object(sys, "platform", "linux"):
            self.assertEqual(ps.default_output(), Path("./scans"))
        for plat in ("win32", "darwin"):
            with mock.patch.object(sys, "platform", plat), \
                    mock.patch.object(Path, "home", return_value=Path("/home/u")):
                self.assertEqual(ps.default_output(), Path("/home/u/Documents/Scans"))


class ReplaceFileTests(unittest.TestCase):
    def test_plain_replace(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a", Path(d) / "b"
            a.write_text("new")
            b.write_text("old")
            ps.replace_file(a, b)
            self.assertEqual(b.read_text(), "new")
            self.assertFalse(a.exists())

    def test_windows_retries_then_succeeds(self):
        calls = []

        def flaky(src, dst):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(errno.EACCES, "in use")

        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch("os.replace", side_effect=flaky), mock.patch("time.sleep"):
            ps.replace_file("a", "b")
        self.assertEqual(len(calls), 3)

    def test_windows_gives_up_after_the_attempts(self):
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch("os.replace", side_effect=PermissionError(errno.EACCES, "x")) as rep, \
                mock.patch("time.sleep"):
            with self.assertRaises(PermissionError):
                ps.replace_file("a", "b", attempts=4)
        self.assertEqual(rep.call_count, 4)

    def test_posix_does_not_retry(self):
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch("os.replace", side_effect=PermissionError(errno.EACCES, "x")) as rep:
            with self.assertRaises(PermissionError):
                ps.replace_file("a", "b")
        self.assertEqual(rep.call_count, 1)


class NameTests(unittest.TestCase):
    def test_reserved(self):
        for name in ("con", "PRN", "Aux", "nul", "COM1", "com9", "LPT1", "lpt0", "CON.txt",
                     "nul.tar.gz", "con .txt", "CONIN$"):
            self.assertTrue(ps.is_reserved_name(name), name)
        for name in ("console", "com10", "lpt", "xcon", "a.con", "", "scan_1.pdf"):
            self.assertFalse(ps.is_reserved_name(name), name)

    def test_component_problem(self):
        for bad in ('a<b', 'a>b', 'a:b', 'a"b', "a/b", "a\\b", "a|b", "a?b", "a*b", "a\x01",
                    "x.", "x ", "con", "NUL.log"):
            self.assertIsNotNone(ps.component_problem(bad), bad)
        for good in ("scan", "Paperless Inbox", "ü", "a.b", ".hidden", "a-b_c"):
            self.assertIsNone(ps.component_problem(good), good)


class LoggingTests(unittest.TestCase):
    def test_log_file_rotates_and_is_utf8(self):
        root = logging.getLogger()
        before = list(root.handlers)
        self.addCleanup(lambda: [root.removeHandler(h) or h.close()
                                 for h in list(root.handlers) if h not in before])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "p.log"
            cli.setup_logging(False, str(path))
            added = [h for h in root.handlers if h not in before]
            rotating = [h for h in added if isinstance(h, logging.handlers.RotatingFileHandler)]
            self.assertEqual(len(rotating), 1)
            self.assertEqual((rotating[0].maxBytes, rotating[0].backupCount), (1_000_000, 3))
            logging.getLogger("t").warning("hello \u00fc")
            rotating[0].flush()
            self.assertIn("hello \u00fc", path.read_text(encoding="utf-8"))
            for h in rotating:
                root.removeHandler(h)
                h.close()

    def test_unwritable_log_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            blocker = Path(d) / "file"
            blocker.write_text("x")
            with self.assertRaises(OSError):
                cli.setup_logging(False, str(blocker / "p.log"))

    def test_console_never_fails_on_unencodable_text(self):
        import io
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="ascii", errors="strict",
                                  newline="\n")
        with mock.patch.object(sys, "stdout", stream), mock.patch.object(sys, "stderr", stream):
            cli.setup_console()
            print("caf\u00e9")
            stream.flush()
        self.assertEqual(raw.getvalue(), b"caf?\n")


class SignalTests(unittest.TestCase):
    def test_handlers_stop_the_service(self):
        service = mock.Mock()
        seen = {}
        with mock.patch.object(signal, "signal",
                               side_effect=lambda n, h: seen.__setitem__(n, h)):
            cli.install_signal_handlers(service)
        self.assertIn(signal.SIGINT, seen)
        self.assertIn(signal.SIGTERM, seen)
        seen[signal.SIGINT](signal.SIGINT, None)
        service.stop.assert_called_once()

    def test_windows_adds_sigbreak(self):
        fake = mock.Mock(SIGINT=2, SIGTERM=15, SIGBREAK=21)
        seen = []
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(cli, "signal", fake):
            fake.signal.side_effect = lambda n, h: seen.append(n)
            cli.install_signal_handlers(mock.Mock())
        self.assertEqual(seen, [2, 15, 21])


class AutostartTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(sys, "executable", r"C:\Program Files\ps\pushscan2folder.exe")
        p.start()
        self.addCleanup(p.stop)

    def frozen(self, value=True):
        return mock.patch.object(sys, "frozen", value, create=True)

    def test_frozen_command(self):
        with self.frozen():
            cmd = autostart.install_command(["--config", "/abs/c.toml", "--log-file=/abs/p.log"])
        self.assertEqual(cmd[:2], ["reg.exe", "add"])
        self.assertIn(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run", cmd)
        self.assertEqual(cmd[cmd.index("/v") + 1], "pushscan2folder")
        self.assertEqual(cmd[-1], "/f")
        value = cmd[cmd.index("/d") + 1]
        self.assertTrue(value.startswith(r'"C:\Program Files\ps\pushscan2folder.exe" '))
        self.assertNotIn("cmd.exe", value)          # no console window of its own
        self.assertTrue(value.endswith(' "start"'))  # background mode is the default command
        self.assertNotIn("-m", value)

    def test_source_command_uses_module(self):
        with self.frozen(False):
            value = autostart.run_value(["run", "--printer", "1.2.3.4"])
        self.assertIn('"-m" "pushscan2folder" "--no-pause" "run" "--printer" "1.2.3.4"', value)
        self.assertEqual(value.count('"run"'), 1)

    def test_paths_become_absolute(self):
        args = autostart.absolute_args(["--config", "c.toml", "--log-file=p.log", "-v",
                                        "run", "--output", "out"])
        self.assertEqual(args[1], os.path.abspath("c.toml"))
        self.assertEqual(args[2], "--log-file=" + os.path.abspath("p.log"))
        self.assertEqual(args[-1], os.path.abspath("out"))
        self.assertEqual(args[3:5], ["-v", "run"])

    def test_dangerous_characters_are_refused(self):
        for bad in ('a"b', "%PATH%", "a\nb"):
            with self.frozen(), self.assertRaises(ValueError):
                autostart.run_value(["run", "--name", bad])

    def test_metacharacters_stay_inside_quotes(self):
        with self.frozen():
            value = autostart.run_value(["run", "--name", "a&b c|d"])
        self.assertIn('"a&b c|d"', value)

    def test_remove_command(self):
        self.assertEqual(autostart.remove_command(),
                         ["reg.exe", "delete", autostart.RUN_KEY, "/v", "pushscan2folder", "/f"])


class AutostartMainTests(unittest.TestCase):
    def run_main(self, argv, platform):
        err = __import__("io").StringIO()
        with mock.patch.object(sys, "platform", platform), \
                mock.patch.object(sys, "stderr", err), \
                mock.patch.object(sys, "stdout", __import__("io").StringIO()), \
                mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            code = cli.main(argv)
        return code, err.getvalue(), run

    def test_not_windows_exits_2_without_running_anything(self):
        for plat in ("linux", "darwin"):
            for flag in ("--install-autostart", "--remove-autostart"):
                code, err, run = self.run_main([flag], plat)
                self.assertEqual(code, 2)
                self.assertIn("only implemented for Windows", err)
                run.assert_not_called()

    def test_both_flags_is_an_error(self):
        code, err, run = self.run_main(["--install-autostart", "--remove-autostart"], "win32")
        self.assertEqual(code, 2)
        run.assert_not_called()

    def test_install_runs_reg_without_shell(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "c.toml"
            cfg.write_text('printer = "192.0.2.1"\n')
            code, err, run = self.run_main(["--config", str(cfg), "--install-autostart"],
                                           "win32")
        self.assertEqual(code, 0, err)
        args, kwargs = run.call_args
        self.assertEqual(args[0][:2], ["reg.exe", "add"])
        self.assertFalse(kwargs.get("shell", False))
        self.assertIn(str(cfg), args[0][args[0].index("/d") + 1])

    def test_install_with_run_options_and_no_subcommand(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "c.toml"
            cfg.write_text('printer = "192.0.2.1"\n')
            code, err, run = self.run_main(["--install-autostart", "--config", str(cfg),
                                            "--output", str(Path(d) / "s")], "win32")
        self.assertEqual(code, 0, err)
        self.assertEqual(run.call_args[0][0][:2], ["reg.exe", "add"])

    def test_setup_callback_installs(self):
        # the setup questions use this callback; it must add the entry, not delete it
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "c.toml"
            cfg.write_text('printer = "192.0.2.1"\n')
            with mock.patch.object(sys, "platform", "win32"), \
                    mock.patch.object(sys, "stdout", __import__("io").StringIO()), \
                    mock.patch("subprocess.run") as run:
                run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
                code = cli.install_autostart(["--config", str(cfg), "--log-file",
                                              str(Path(d) / "l.log")])
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args[0][0][:2], ["reg.exe", "add"])

    def test_remove(self):
        code, _, run = self.run_main(["--remove-autostart"], "win32")
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args[0][0][:2], ["reg.exe", "delete"])

    def test_reg_failure_is_reported(self):
        err = __import__("io").StringIO()
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(sys, "stderr", err), \
                mock.patch("subprocess.run",
                           return_value=mock.Mock(returncode=1, stdout="", stderr="denied")):
            self.assertEqual(cli.main(["--remove-autostart"]), 1)
        self.assertIn("denied", err.getvalue())


if __name__ == "__main__":
    unittest.main()
