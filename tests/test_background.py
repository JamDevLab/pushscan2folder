"""Background instance (start, stop, status), uninstall, open after scan and the
icon writer. Everything is mocked: no real process, registry or explorer."""
import io
import os
import struct
import sys
import tempfile
import time
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from pushscan2folder import __main__ as cli
from pushscan2folder import autostart, background, desktop, uninstall, wizard, web
from pushscan2folder.config import ConfigError, dump_config, load_config_text
from pushscan2folder.escl import ScanSettings
from pushscan2folder.service import PushScanService, Target
from pushscan2folder.status import LogBuffer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
import make_ico  # noqa: E402


def clean_env():
    return mock.patch.dict(os.environ, {k: v for k, v in os.environ.items()
                                        if not k.startswith("PUSHSCAN_")}, clear=True)


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.insts = []

    def instance(self, name="state") -> background.Instance:
        inst = background.Instance(self.dir / name)
        self.insts.append(inst)
        self.addCleanup(inst.release)
        return inst


class InstanceTests(TempDirCase):
    def test_claim_and_release(self):
        a, b = self.instance(), self.instance()
        self.assertFalse(a.is_running())
        self.assertTrue(a.claim("x.log"))
        self.assertTrue(b.is_running())
        self.assertFalse(b.claim())              # a second instance is refused
        info = b.read_info()
        self.assertEqual((info.pid, info.log), (os.getpid(), "x.log"))
        a.release()
        self.assertFalse(b.is_running())
        self.assertFalse(a.info_path.exists())

    def test_stale_files_do_not_block(self):
        a = self.instance()
        a.dir.mkdir(parents=True)
        a.info_path.write_text('{"pid": 4242, "log": "old.log"}', encoding="utf-8")
        a.lock_path.write_text("", encoding="utf-8")
        a.stop_path.write_text("stop", encoding="utf-8")
        self.assertFalse(a.is_running())
        self.assertTrue(a.claim())
        self.assertFalse(a.stop_requested())     # an old request is dropped
        self.assertEqual(a.read_info().pid, os.getpid())

    def test_garbled_info_file(self):
        a = self.instance()
        a.dir.mkdir(parents=True)
        a.info_path.write_text("nonsense", encoding="utf-8")
        self.assertEqual(a.read_info(), background.Info())

    def test_status_does_not_create_the_state_dir(self):
        a = self.instance("missing")
        self.assertFalse(a.is_running())
        self.assertFalse(a.dir.exists())


class StopTests(TempDirCase):
    def test_not_running_cleans_stale_files(self):
        a = self.instance()
        a.dir.mkdir(parents=True)
        a.info_path.write_text("{}", encoding="utf-8")
        self.assertEqual(background.stop_instance(a), background.NOT_RUNNING)
        self.assertFalse(a.info_path.exists())

    def test_clean_stop_writes_the_request(self):
        runner, caller = self.instance(), self.instance()
        runner.claim()
        seen = []

        def sleep(_):
            seen.append(runner.stop_requested())
            runner.release()   # the poll loop saw the request and ended

        kill = mock.Mock()
        result = background.stop_instance(caller, timeout=5, sleep=sleep, kill=kill)
        self.assertEqual(result, background.STOPPED)
        self.assertEqual(seen, [True])
        kill.assert_not_called()
        self.assertFalse(caller.stop_path.exists())

    def test_terminated_after_the_timeout(self):
        runner, caller = self.instance(), self.instance()
        runner.claim()
        now = [0.0]

        def sleep(seconds):
            now[0] += seconds

        result = background.stop_instance(caller, timeout=3, poll=1, sleep=sleep,
                                          clock=lambda: now[0],
                                          kill=lambda pid: runner.release())
        self.assertEqual(result, background.TERMINATED)

    def test_failed_if_nothing_helps(self):
        runner, caller = self.instance(), self.instance()
        runner.claim()
        now = [0.0]
        kill = mock.Mock()
        result = background.stop_instance(caller, timeout=1, poll=1,
                                          sleep=lambda s: now.__setitem__(0, now[0] + s),
                                          clock=lambda: now[0], kill=kill)
        self.assertEqual(result, background.FAILED)
        kill.assert_called_once_with(os.getpid())

    def test_terminate_command(self):
        with mock.patch.object(background, "is_windows", return_value=True), \
                mock.patch("subprocess.run") as run:
            background.terminate(123)
        self.assertEqual(run.call_args[0][0], ["taskkill", "/PID", "123", "/T", "/F"])
        with mock.patch.object(background, "is_windows", return_value=False), \
                mock.patch("os.kill") as kill:
            background.terminate(123)
        kill.assert_called_once()
        self.assertEqual(kill.call_args[0][0], 123)


class ServiceStopTests(unittest.TestCase):
    def make(self, interval=30.0):
        chmp = mock.Mock()
        chmp.register.return_value = mock.Mock(session=7)
        chmp.poll.return_value = mock.Mock(status=0, scan_requested=False, raw=b"")
        service = PushScanService(chmp, None, [Target("Scan", Path("out"))], ScanSettings(),
                                  interval=interval)
        return service, chmp

    def test_stop_request_ends_the_loop_and_releases(self):
        service, chmp = self.make()
        service.stop_check = lambda: True
        started = time.monotonic()
        service.run()
        self.assertLess(time.monotonic() - started, 5)  # not the 30 s interval
        chmp.release.assert_called_once_with(7)

    def test_request_is_noticed_while_waiting(self):
        service, chmp = self.make()
        calls = []
        service.stop_check = lambda: calls.append(1) or len(calls) > 2
        with mock.patch("pushscan2folder.service.STOP_CHECK_INTERVAL", 0.01):
            service.run()
        chmp.release.assert_called_once_with(7)

    def test_without_check_stop_still_releases(self):
        service, chmp = self.make(0.01)
        threading_stop = mock.patch.object(service, "step", side_effect=service.stop)
        with threading_stop:
            service.run()
        chmp.release.assert_not_called()   # nothing was registered yet


class FakeProc:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


class LaunchTests(TempDirCase):
    def test_windows_flags_and_streams(self):
        popen = mock.Mock()
        with mock.patch.object(background, "is_windows", return_value=True), \
                mock.patch.object(sys, "frozen", False, create=True):
            background.launch(["py", "-m", "x"], popen)
        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["py", "-m", "x"])
        self.assertEqual(kwargs["creationflags"], 0x08000000 | 0x00000008 | 0x00000200)
        for stream in ("stdin", "stdout", "stderr"):
            self.assertEqual(kwargs[stream], background.subprocess.DEVNULL)
        self.assertNotIn("start_new_session", kwargs)
        self.assertNotIn("env", kwargs)
        self.assertFalse(kwargs.get("shell", False))

    def test_posix_new_session(self):
        popen = mock.Mock()
        with mock.patch.object(background, "is_windows", return_value=False):
            background.launch(["x"], popen)
        kwargs = popen.call_args[1]
        self.assertTrue(kwargs["start_new_session"])
        self.assertNotIn("creationflags", kwargs)

    def test_frozen_child_gets_its_own_environment(self):
        popen = mock.Mock()
        with mock.patch.object(sys, "frozen", True, create=True):
            background.launch(["x"], popen)
        self.assertEqual(popen.call_args[1]["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_start_refuses_a_second_instance(self):
        runner, caller = self.instance(), self.instance()
        runner.claim()
        popen = mock.Mock()
        ok, message = background.start_instance(["run"], caller, popen=popen)
        self.assertFalse(ok)
        self.assertIn("already running", message)
        self.assertIn(str(os.getpid()), message)
        popen.assert_not_called()

    def test_start_ignores_a_stale_pid_file(self):
        inst, child = self.instance(), self.instance()
        inst.dir.mkdir(parents=True)
        inst.info_path.write_text('{"pid": 1}', encoding="utf-8")
        popen = mock.Mock(side_effect=lambda *a, **k: child.claim() and FakeProc())
        ok, message = background.start_instance(["run"], inst, popen=popen, sleep=lambda s: None)
        self.assertTrue(ok, message)
        self.assertIn(str(os.getpid()), message)

    def test_start_command_is_program_plus_argv(self):
        inst, child = self.instance(), self.instance()
        popen = mock.Mock(side_effect=lambda *a, **k: child.claim() and FakeProc())
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", "ps.exe"):
            background.start_instance(["--background", "run"], inst, popen=popen,
                                      sleep=lambda s: None)
        self.assertEqual(popen.call_args[0][0], ["ps.exe", "--background", "run"])

    def test_child_that_dies_is_reported(self):
        inst = self.instance()
        ok, message = background.start_instance(["run"], inst, popen=lambda *a, **k: FakeProc(3),
                                                sleep=lambda s: None)
        self.assertFalse(ok)
        self.assertIn("exit code 3", message)

    def test_child_that_never_reports(self):
        inst = self.instance()
        now = [0.0]
        ok, message = background.start_instance(
            ["run"], inst, popen=lambda *a, **k: FakeProc(), timeout=1,
            sleep=lambda s: now.__setitem__(0, now[0] + 1), clock=lambda: now[0])
        self.assertFalse(ok)
        self.assertIn("in time", message)

    def test_cannot_start_the_program(self):
        inst = self.instance()
        ok, message = background.start_instance(
            ["run"], inst, popen=mock.Mock(side_effect=FileNotFoundError(2, "No such file")))
        self.assertFalse(ok)
        self.assertIn("No such file", message)

    def test_log_tail(self):
        path = self.dir / "a.log"
        path.write_text("\n".join(f"line {i}" for i in range(30)), encoding="utf-8")
        self.assertEqual(background.log_tail(path, 3), ["line 27", "line 28", "line 29"])
        self.assertEqual(background.log_tail(self.dir / "none.log"), [])
        self.assertEqual(background.log_tail(None), [])


class CliCommandTests(TempDirCase):
    def setUp(self):
        super().setUp()
        env = {"XDG_STATE_HOME": str(self.dir / "state"), "LOCALAPPDATA": str(self.dir / "state"),
               "XDG_CONFIG_HOME": str(self.dir / "cfg"), "APPDATA": str(self.dir / "cfg")}
        for patcher in (clean_env(), mock.patch.dict(os.environ, env)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_start(self, argv, instance=None, hints=True):
        inst = instance or self.instance(os.path.join("state", "pushscan2folder"))
        child = self.instance(os.path.join("state", "pushscan2folder"))
        popen = mock.Mock(side_effect=lambda *a, **k: child.claim("l") and FakeProc())
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
                mock.patch.object(background.time, "sleep"):
            code = cli.start_main(argv, hints=hints, popen=popen, instance=inst)
        return code, out.getvalue(), err.getvalue(), popen

    def test_command_line_of_the_background_process(self):
        code, out, err, popen = self.run_start(["--printer", "192.0.2.1", "--config",
                                                "rel.toml", "start", "--output", "scans"])
        # rel.toml does not exist: an explicit missing config is an error
        self.assertEqual(code, 2)
        popen.assert_not_called()
        cfg = self.dir / "c.toml"
        cfg.write_text('printer = "192.0.2.1"\n', encoding="utf-8")
        code, out, err, popen = self.run_start(["--config", str(cfg), "start", "--output", "scans"])
        self.assertEqual(code, 0, err)
        cmd = popen.call_args[0][0]
        self.assertEqual(cmd[-len(cmd) + len(autostart.program_command()):][:3],
                         ["--no-pause", "--background", "--log-file"])
        self.assertEqual(cmd[len(autostart.program_command()) + 3],
                         str(self.dir / "state" / "pushscan2folder" / "pushscan2folder.log"))
        self.assertIn("run", cmd)
        self.assertNotIn("start", cmd)
        self.assertEqual(cmd[cmd.index("--output") + 1], os.path.abspath("scans"))
        self.assertEqual(cmd[cmd.index("--config") + 1], str(cfg))
        self.assertIn("pushscan2folder stop", out)

    def test_own_log_file_is_kept(self):
        _, _, _, popen = self.run_start(["--printer", "192.0.2.1", "--log-file", "my.log",
                                         "start"])
        cmd = popen.call_args[0][0]
        self.assertEqual(cmd.count("--log-file"), 1)
        self.assertEqual(cmd[cmd.index("--log-file") + 1], os.path.abspath("my.log"))

    def test_start_without_printer(self):
        code, _, err, popen = self.run_start(["start"])
        self.assertEqual(code, 2)
        self.assertIn("--printer", err)
        popen.assert_not_called()

    def test_start_twice_is_refused(self):
        runner = self.instance(os.path.join("state", "pushscan2folder"))
        runner.claim()
        code, _, err, popen = self.run_start(["--printer", "192.0.2.1", "start"],
                                             instance=self.instance(os.path.join(
                                                 "state", "pushscan2folder")))
        self.assertEqual(code, 1)
        self.assertIn("already running", err)
        popen.assert_not_called()

    def test_wizard_start_is_quiet(self):
        _, out, _, _ = self.run_start(["--printer", "192.0.2.1"], hints=False)
        self.assertNotIn("pushscan2folder stop", out)

    def test_stop_and_status(self):
        inst = self.instance(os.path.join("state", "pushscan2folder"))
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.stop_main(instance=inst), 0)
            self.assertEqual(cli.status_main(instance=inst), 1)
        self.assertIn("not running", out.getvalue())
        runner = self.instance(os.path.join("state", "pushscan2folder"))
        runner.dir.mkdir(parents=True, exist_ok=True)
        log = self.dir / "r.log"
        log.write_text("hello\nworld\n", encoding="utf-8")
        runner.claim(str(log))
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.status_main(instance=inst), 0)
        text = out.getvalue()
        self.assertIn(f"PID {os.getpid()}", text)
        self.assertIn(str(log), text)
        self.assertIn("  world", text)
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.stop_main(instance=inst, timeout=0.01, poll=0.001,
                                 kill=lambda pid: runner.release())
        self.assertEqual(code, 0)
        self.assertIn("terminated", out.getvalue())

    def test_commands_work_with_a_broken_config(self):
        broken = self.dir / "bad.toml"
        broken.write_text("printer = 5\n", encoding="utf-8")
        for command in ("stop", "status"):
            args, _ = cli.parse_args(["--config", str(broken), command])
            self.assertEqual(args.cmd, command)
        with mock.patch("pushscan2folder.__main__.pause_before_exit"), \
                mock.patch("pushscan2folder.__main__.greeting", return_value=None), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--config", str(broken), "stop"]), 0)

    def test_new_commands_are_not_run_options(self):
        for command in ("start", "stop", "status", "uninstall"):
            self.assertEqual(cli.with_default_command([command]), [command])
        self.assertEqual(cli.with_default_command(["--background", "--web"]),
                         ["--background", "run", "--web"])

    def test_replace_command(self):
        self.assertEqual(cli.replace_command(["--config", "x", "start", "--web"],
                                             "run"), ["--config", "x", "run", "--web"])
        self.assertEqual(cli.replace_command(["--config", "x"], "run"),
                         ["--config", "x", "run"])

    def test_autostart_entry_runs_start(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", "ps.exe"):
            value = autostart.run_value(["--config", "c.toml", "--log-file", "l.log"])
        self.assertTrue(value.startswith('"ps.exe" "--no-pause" '))
        self.assertTrue(value.endswith(' "start"'))
        self.assertNotIn("cmd.exe", value)


class BackgroundRunTests(TempDirCase):
    """`run --background` holds the instance lock for the whole run."""

    def test_run_claims_and_releases(self):
        env = {"XDG_STATE_HOME": str(self.dir), "LOCALAPPDATA": str(self.dir)}
        seen = {}

        def fake_run(self_):
            inst = background.Instance()
            seen["running"] = inst.is_running()
            seen["check"] = self_.stop_check

        with clean_env(), mock.patch.dict(os.environ, env), \
                mock.patch.object(cli.PushScanService, "run", fake_run), \
                mock.patch("pushscan2folder.__main__.install_signal_handlers"), \
                mock.patch("pushscan2folder.__main__.pause_before_exit"), \
                mock.patch("pushscan2folder.__main__.greeting", return_value=None):
            code = cli.main(["--printer", "192.0.2.1", "--background", "--no-pause",
                             "--output", str(self.dir / "o")])
        self.assertEqual(code, 0)
        self.assertTrue(seen["running"])
        self.assertIsNotNone(seen["check"])
        self.assertFalse(background.Instance(self.dir / "pushscan2folder").is_running())

    def test_second_background_run_exits(self):
        env = {"XDG_STATE_HOME": str(self.dir), "LOCALAPPDATA": str(self.dir)}
        with clean_env(), mock.patch.dict(os.environ, env):
            runner = background.Instance()
            self.addCleanup(runner.release)
            self.assertTrue(runner.claim())
            with mock.patch.object(cli.PushScanService, "run") as run, \
                    mock.patch("pushscan2folder.__main__.install_signal_handlers"), \
                    mock.patch("pushscan2folder.__main__.pause_before_exit"), \
                    mock.patch("pushscan2folder.__main__.greeting", return_value=None):
                code = cli.main(["--printer", "192.0.2.1", "--background"])
        self.assertEqual(code, 2)
        run.assert_not_called()


class SummaryHintTests(unittest.TestCase):
    def test_foreground_hint(self):
        with clean_env():
            args, _ = cli.parse_args(["--printer", "192.0.2.1"])
        target = Target("Scan", Path("out"))
        text = "\n".join(cli.summary_lines(args, [target], None, None, foreground_hint=True))
        self.assertIn("Closing this window stops the program. Use `pushscan2folder start` "
                      "to run in the background.", text)
        self.assertNotIn("Closing this window",
                         "\n".join(cli.summary_lines(args, [target], None, None)))


class UninstallTests(TempDirCase):
    def setUp(self):
        super().setUp()
        self.config_dir = self.dir / "cfg" / "pushscan2folder"
        self.state_dir = self.dir / "state" / "pushscan2folder"
        for folder in (self.config_dir, self.state_dir):
            folder.mkdir(parents=True)
            (folder / "f.txt").write_text("x", encoding="utf-8")
        self.scans = self.dir / "scans"
        self.scans.mkdir()
        (self.scans / "scan.pdf").write_bytes(b"%PDF")
        self.lines = []
        self.inst = self.instance("state2")

    def run_uninstall(self, answer=None, **kwargs):
        kwargs.setdefault("stop", lambda inst: background.NOT_RUNNING)
        return uninstall.uninstall(
            self.inst, self.config_dir, self.state_dir, kwargs.pop("protected", [self.scans]),
            out=self.lines.append,
            input_fn=mock.Mock(return_value=answer or "") if answer is not None
            else mock.Mock(side_effect=AssertionError("must not ask")), **kwargs)

    def test_default_no_keeps_everything(self):
        self.assertEqual(self.run_uninstall(answer=""), 0)
        self.assertTrue(self.config_dir.is_dir() and self.state_dir.is_dir())
        text = "\n".join(self.lines)
        self.assertIn(str(self.config_dir), text)
        self.assertIn(str(self.state_dir), text)
        self.assertIn("scans were not touched", text)

    def test_yes_answer_deletes_both_but_never_scans(self):
        self.assertEqual(self.run_uninstall(answer="y"), 0)
        self.assertFalse(self.config_dir.exists() or self.state_dir.exists())
        self.assertTrue((self.scans / "scan.pdf").is_file())

    def test_non_interactive_keeps_without_purge(self):
        self.assertEqual(self.run_uninstall(yes=True), 0)
        self.assertTrue(self.config_dir.is_dir() and self.state_dir.is_dir())

    def test_purge_deletes_without_asking(self):
        self.assertEqual(self.run_uninstall(yes=True, purge=True), 0)
        self.assertFalse(self.config_dir.exists() or self.state_dir.exists())
        self.assertTrue((self.scans / "scan.pdf").is_file())

    def test_scan_folder_inside_a_folder_protects_it(self):
        inside = self.config_dir / "scans"
        inside.mkdir()
        (inside / "a.pdf").write_bytes(b"%PDF")
        self.assertEqual(self.run_uninstall(yes=True, purge=True, protected=[inside]), 0)
        self.assertTrue((inside / "a.pdf").is_file())
        self.assertFalse(self.state_dir.exists())
        self.assertIn("scan folder is inside", "\n".join(self.lines))

    def test_only_folders_named_pushscan2folder(self):
        other = self.dir / "important"
        other.mkdir()
        uninstall.uninstall(self.inst, other, self.state_dir, [], yes=True, purge=True,
                            out=self.lines.append,
                            stop=lambda i: background.NOT_RUNNING)
        self.assertTrue(other.is_dir())
        self.assertFalse(self.state_dir.exists())

    def test_stop_failure_aborts(self):
        code = self.run_uninstall(yes=True, purge=True, stop=lambda i: background.FAILED)
        self.assertEqual(code, 1)
        self.assertTrue(self.config_dir.is_dir())

    def test_autostart_and_exe_hint(self):
        removed = mock.Mock(return_value="Autostart entry removed.")
        self.run_uninstall(answer="", remove_autostart=removed, exe=Path("C:/x/ps.exe"))
        removed.assert_called_once()
        text = "\n".join(self.lines)
        self.assertIn("Autostart entry removed.", text)
        self.assertIn("delete the program folder itself", text)
        self.assertIn(str(Path("C:/x")), text)

    def test_stops_the_instance_first(self):
        order = []
        self.run_uninstall(answer="", stop=lambda i: order.append("stop") or background.STOPPED,
                           remove_autostart=lambda: order.append("autostart") or "ok")
        self.assertEqual(order, ["stop", "autostart"])

    def test_cli_uninstall_protects_configured_scan_folders(self):
        cfg = self.config_dir / "config.toml"
        cfg.write_text(f'printer = "192.0.2.1"\noutput = "{(self.config_dir / "s").as_posix()}"\n',
                       encoding="utf-8")
        (self.config_dir / "s").mkdir()
        env = {"XDG_CONFIG_HOME": str(self.dir / "cfg"), "APPDATA": str(self.dir / "cfg"),
               "XDG_STATE_HOME": str(self.dir / "state"),
               "LOCALAPPDATA": str(self.dir / "state")}
        with clean_env(), mock.patch.dict(os.environ, env), \
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as run, \
                mock.patch("pushscan2folder.__main__.pause_before_exit"), \
                mock.patch("pushscan2folder.__main__.greeting", return_value=None), \
                redirect_stdout(io.StringIO()) as out:
            code = cli.main(["uninstall", "--yes", "--purge"])
        self.assertEqual(code, 0)
        self.assertTrue((self.config_dir / "s").is_dir())    # scans inside: folder kept
        self.assertFalse(self.state_dir.exists())
        self.assertIn("scan folder is inside", out.getvalue())
        if sys.platform == "win32":   # only Windows touches the registry (mocked)
            self.assertEqual(run.call_args[0][0][:2], ["reg.exe", "delete"])
        else:
            run.assert_not_called()

    def test_remove_autostart_message(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as run:
            self.assertIn("removed", cli.remove_autostart_message())
        self.assertEqual(run.call_args[0][0][:2], ["reg.exe", "delete"])
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)):
            self.assertIn("No autostart", cli.remove_autostart_message())

    def test_uninstall_options_parse(self):
        args, _ = cli.parse_args(["uninstall", "--yes", "--purge"])
        self.assertTrue(args.yes and args.purge)
        args, _ = cli.parse_args(["uninstall"])
        self.assertFalse(args.yes or args.purge)


class DesktopTests(unittest.TestCase):
    def test_has_desktop(self):
        for platform, expected in (("win32", True), ("darwin", True)):
            with mock.patch.object(sys, "platform", platform):
                self.assertTrue(desktop.has_desktop({}))
        with mock.patch.object(sys, "platform", "linux"):
            self.assertFalse(desktop.has_desktop({}))
            self.assertFalse(desktop.has_desktop({"DISPLAY": ""}))
            self.assertTrue(desktop.has_desktop({"DISPLAY": ":0"}))
            self.assertTrue(desktop.has_desktop({"WAYLAND_DISPLAY": "wayland-0"}))

    def test_windows_folder_selects_the_file(self):
        popen = mock.Mock()
        with mock.patch.object(sys, "platform", "win32"):
            self.assertTrue(desktop.open_saved("folder", [Path("C:/s/a.pdf"), Path("C:/s/b.pdf")],
                                               popen=popen))
        popen.assert_called_once_with(f'explorer.exe /select,"{Path("C:/s/a.pdf")}"')

    def test_windows_file_uses_startfile_once(self):
        paths = [Path("C:/s/a.pdf"), Path("C:/s/b.pdf")]
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.object(os, "startfile", create=True) as startfile:
            self.assertTrue(desktop.open_saved("file", paths, popen=mock.Mock()))
        startfile.assert_called_once_with(paths[0])

    def test_linux_and_macos(self):
        path = Path("/home/u/Scans/a.pdf")
        for platform, opener in (("linux", "xdg-open"), ("darwin", "open")):
            for mode, target in (("folder", "/home/u/Scans"), ("file", str(path))):
                popen = mock.Mock()
                with mock.patch.object(sys, "platform", platform), \
                        mock.patch.dict(os.environ, {"DISPLAY": ":0"}):
                    self.assertTrue(desktop.open_saved(mode, [path], popen=popen))
                self.assertEqual(popen.call_args[0][0], [opener, str(Path(target))])

    def test_linux_without_desktop_does_nothing(self):
        popen = mock.Mock()
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.dict(os.environ, env, clear=True), \
                self.assertLogs("pushscan2folder.desktop", "WARNING"):
            self.assertFalse(desktop.open_saved("folder", [Path("/x/a.pdf")], popen=popen))
        popen.assert_not_called()

    def test_off_and_empty(self):
        popen = mock.Mock()
        self.assertFalse(desktop.open_saved("off", [Path("a.pdf")], popen=popen))
        self.assertFalse(desktop.open_saved("folder", [], popen=popen))
        popen.assert_not_called()

    def test_failure_is_only_a_warning(self):
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.dict(os.environ, {"DISPLAY": ":0"}), \
                self.assertLogs("pushscan2folder.desktop", "WARNING") as logs:
            result = desktop.open_saved("folder", [Path("/x/a.pdf")],
                                        popen=mock.Mock(side_effect=FileNotFoundError("xdg-open")))
        self.assertFalse(result)
        self.assertIn("could not open", logs.output[0])

    def test_service_opens_once_per_job(self):
        service = PushScanService(None, None, [], ScanSettings(), open_after_scan="folder")
        paths = [Path("a_01.pdf"), Path("a_02.pdf")]
        with mock.patch.object(service, "_scan_to", return_value=paths), \
                mock.patch("pushscan2folder.service.desktop.open_saved") as opener:
            service.scan_to(Target("Scan", Path("out")))
        opener.assert_called_once_with("folder", paths)

    def test_service_does_not_open_when_nothing_was_saved(self):
        service = PushScanService(None, None, [], ScanSettings(), open_after_scan="folder")
        with mock.patch.object(service, "_scan_to", return_value=[]), \
                mock.patch("pushscan2folder.service.desktop.open_saved") as opener:
            service.scan_to(Target("Scan", Path("out")))
        opener.assert_not_called()

    def test_a_failing_opener_never_fails_the_scan(self):
        service = PushScanService(None, None, [], ScanSettings(), open_after_scan="file")
        with mock.patch.object(service, "_scan_to", return_value=[Path("a.pdf")]), \
                mock.patch.object(desktop, "has_desktop", side_effect=RuntimeError("boom")), \
                self.assertLogs("pushscan2folder.desktop", "WARNING"):
            self.assertEqual(service.scan_to(Target("Scan", Path("out"))), [Path("a.pdf")])


class OpenAfterScanConfigTests(unittest.TestCase):
    def parse(self, argv, toml=None):
        cfg = load_config_text(toml) if toml else None
        with clean_env():
            return cli.build_parser(cfg).parse_args(cli.with_default_command(
                ["--printer", "192.0.2.1"] + argv))

    def test_builtin_is_off(self):
        self.assertEqual(self.parse([]).open_after_scan, "off")

    def test_config_file(self):
        args = self.parse([], '[defaults]\nopen_after_scan = "file"\n')
        self.assertEqual(args.open_after_scan, "file")

    def test_env_beats_config_and_cli_beats_env(self):
        toml = '[defaults]\nopen_after_scan = "file"\n'
        with mock.patch.dict(os.environ, {"PUSHSCAN_OPEN_AFTER_SCAN": "folder"}):
            cfg = load_config_text(toml)
            parser = cli.build_parser(cfg)
            self.assertEqual(parser.parse_args(["--printer", "x", "run"]).open_after_scan,
                             "folder")
            self.assertEqual(parser.parse_args(["--printer", "x", "run", "--open-after-scan",
                                                "off"]).open_after_scan, "off")

    def test_cli_rejects_unknown_value(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.parse(["--open-after-scan", "always"])

    def test_invalid_env_is_an_error(self):
        err = io.StringIO()
        with clean_env(), mock.patch.dict(os.environ, {"PUSHSCAN_OPEN_AFTER_SCAN": "bogus",
                                                       "PUSHSCAN_PRINTER": "192.0.2.1"}), \
                mock.patch("pushscan2folder.__main__.pause_before_exit"), \
                mock.patch("pushscan2folder.__main__.greeting", return_value=None), \
                redirect_stderr(err):
            self.assertEqual(cli.main(["run"]), 2)
        self.assertIn("PUSHSCAN_OPEN_AFTER_SCAN", err.getvalue())

    def test_env_value_is_case_insensitive(self):
        with clean_env(), mock.patch.dict(os.environ, {"PUSHSCAN_OPEN_AFTER_SCAN": "Folder"}), \
                mock.patch("pushscan2folder.__main__.pause_before_exit"), \
                mock.patch("pushscan2folder.__main__.greeting", return_value=None), \
                mock.patch.object(cli.PushScanService, "run") as run, \
                mock.patch("pushscan2folder.__main__.install_signal_handlers"):
            self.assertEqual(cli.main(["--printer", "192.0.2.1", "run"]), 0)
        run.assert_called_once()

    def test_config_validation_and_roundtrip(self):
        with self.assertRaises(ConfigError):
            load_config_text('[defaults]\nopen_after_scan = "always"\n')
        cfg = load_config_text('[defaults]\nopen_after_scan = "folder"\n')
        self.assertIn('open_after_scan = "folder"', dump_config(cfg))
        self.assertEqual(load_config_text(dump_config(cfg)).open_after_scan, "folder")

    def test_web_settings(self):
        self.assertIn("open_after_scan", web.SETTING_KEYS)
        new, errors = web.check_settings({"open_after_scan": "file"})
        self.assertEqual((errors, new.open_after_scan), ([], "file"))
        _, errors = web.check_settings({"open_after_scan": "sometimes"})
        self.assertTrue(errors)
        values = web.settings_values(load_config_text('[defaults]\nopen_after_scan = "file"\n'))
        self.assertEqual(values["open_after_scan"], "file")

    def test_web_page_shows_an_editable_select_with_hint(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = web.WebContext(object(), LogBuffer(), "192.0.2.1", Path(d),
                                 config_path=Path(d) / "c.toml")
            page = web.render_settings(ctx, "tok").decode()
        self.assertIn('<select name="open_after_scan"', page)
        for value in ("folder", "file", "off"):
            self.assertIn(f'value="{value}"', page)
        self.assertIn("desktop PC", page)

    def test_web_override_is_reported(self):
        with clean_env(), mock.patch.dict(os.environ, {"PUSHSCAN_OPEN_AFTER_SCAN": "file"}):
            args, cfg = cli.parse_args(["--printer", "x"])
            overrides, effective = cli.web_overrides(args, cfg, ["--printer", "x"])
        self.assertIn("PUSHSCAN_OPEN_AFTER_SCAN", overrides["open_after_scan"])
        self.assertEqual(effective["open_after_scan"], "file")


class WizardBackgroundTests(TempDirCase):
    def run_setup(self, answers, start_fn, platform="win32"):
        answers = list(answers)
        lines = []
        session = wizard.Setup(self.dir / "cfg" / "config.toml",
                               input_fn=lambda prompt: answers.pop(0) if answers
                               else self.fail(f"unexpected question {prompt}"),
                               getpass_fn=None, probe_fn=lambda h: (True, "ok"),
                               autostart_fn=lambda a: 0, start_fn=start_fn,
                               out=lambda *p: lines.append(" ".join(map(str, p))),
                               default_name="PC")
        with mock.patch.object(sys, "platform", platform), \
                mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.dir / "l")}):
            return session, session.run(), "\n".join(lines)

    BASE = ["192.0.2.7", "", "S", "n"]  # printer, name, folder, web no

    def test_open_folder_question_and_background_start(self):
        start = mock.Mock(return_value=0)
        # open folder yes, autostart yes, run in background yes
        session, foreground, text = self.run_setup(self.BASE + ["", "", ""], start)
        self.assertFalse(foreground)
        self.assertTrue(session.background_started)
        args = start.call_args[0][0]
        self.assertEqual(args[0], "--config")
        self.assertEqual(args[2], "--log-file")
        self.assertIn("keeps running after you close this window", text)
        self.assertIn("pushscan2folder stop", text)
        self.assertIn("pushscan2folder.log", text)
        cfg = load_config_text((self.dir / "cfg" / "config.toml").read_text(encoding="utf-8"))
        self.assertEqual(cfg.open_after_scan, "folder")

    def test_declining_both_gives_the_foreground_question(self):
        start = mock.Mock(return_value=0)
        # open folder no, autostart no, background no, start now yes
        session, foreground, _ = self.run_setup(self.BASE + ["n", "n", "n", ""], start)
        self.assertTrue(foreground)
        start.assert_not_called()
        cfg = load_config_text((self.dir / "cfg" / "config.toml").read_text(encoding="utf-8"))
        self.assertEqual(cfg.open_after_scan, "off")

    def test_failed_background_start_falls_back(self):
        _, foreground, text = self.run_setup(self.BASE + ["", "", "", ""],
                                             mock.Mock(return_value=1))
        self.assertTrue(foreground)
        self.assertIn("background start failed", text)

    def test_linux_asks_neither_question(self):
        start = mock.Mock()
        # printer, name, folder, web no, start now (no open-folder, no background question)
        _, foreground, _ = self.run_setup(self.BASE + [""], start, platform="linux")
        self.assertTrue(foreground)
        start.assert_not_called()


def fake_png(width, height):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(
            ">I", zlib.crc32(kind + data))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00\x00" * width for _ in range(height))
    return (make_ico.PNG_SIGNATURE + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class IcoTests(unittest.TestCase):
    def test_header_directory_and_offsets(self):
        sizes = (16, 32, 256)
        pngs = [fake_png(n, n) for n in sizes]
        ico = make_ico.build_ico(pngs)
        reserved, kind, count = struct.unpack("<HHH", ico[:6])
        self.assertEqual((reserved, kind, count), (0, 1, 3))
        for i, (n, data) in enumerate(zip(sizes, pngs)):
            w, h, colors, res, planes, bits, size, offset = struct.unpack(
                "<BBBBHHII", ico[6 + 16 * i:22 + 16 * i])
            self.assertEqual((w, h), (n % 256, n % 256))   # 256 is stored as 0
            self.assertEqual((colors, res, planes, bits), (0, 0, 1, 32))
            self.assertEqual(size, len(data))
            self.assertEqual(ico[offset:offset + size], data)
        self.assertEqual(len(ico), 6 + 48 + sum(map(len, pngs)))

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            make_ico.build_ico([])
        with self.assertRaises(ValueError):
            make_ico.build_ico([b"not a png at all, just text bytes"])
        with self.assertRaises(ValueError):
            make_ico.build_ico([fake_png(300, 300)])

    def test_command_line(self):
        with tempfile.TemporaryDirectory() as d:
            for n in (16, 32):
                (Path(d) / f"{n}.png").write_bytes(fake_png(n, n))
            out = Path(d) / "x.ico"
            self.assertEqual(make_ico.main(["m", str(out), str(Path(d) / "16.png"),
                                            str(Path(d) / "32.png")]), 0)
            self.assertEqual(struct.unpack("<HHH", out.read_bytes()[:6]), (0, 1, 2))
            with redirect_stderr(io.StringIO()):
                self.assertEqual(make_ico.main(["m"]), 2)

    def test_committed_icon_has_all_sizes(self):
        ico = (Path(__file__).resolve().parent.parent / "packaging"
               / "pushscan2folder.ico").read_bytes()
        count = struct.unpack("<HHH", ico[:6])[2]
        sizes = [struct.unpack("<BB", ico[6 + 16 * i:8 + 16 * i])[0] or 256
                 for i in range(count)]
        self.assertEqual(sizes, [16, 24, 32, 48, 64, 128, 256])
        size, offset = struct.unpack("<II", ico[6 + 8:6 + 16])
        self.assertTrue(ico[offset:offset + size].startswith(make_ico.PNG_SIGNATURE))


if __name__ == "__main__":
    unittest.main()
