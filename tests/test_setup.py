"""Default subcommand, [web] config table, setup flow, pause decision (no network)."""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from pushscan2folder import __main__ as cli
from pushscan2folder import autostart, wizard
from pushscan2folder.config import Config, ConfigError, dump_config, load_config_text

from support import assert_mode


class DefaultCommandTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {k: v for k, v in os.environ.items()
                                               if not k.startswith("PUSHSCAN_")}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_subcommand_means_run(self):
        args, _ = cli.parse_args(["--printer", "192.0.2.1", "--verbose"])
        self.assertEqual((args.cmd, args.printer, args.verbose), ("run", "192.0.2.1", True))

    def test_run_options_without_subcommand(self):
        args, _ = cli.parse_args(["--output", "x", "--printer", "192.0.2.1", "--web"])
        self.assertEqual(args.cmd, "run")
        self.assertEqual(args.output, Path("x"))
        self.assertTrue(args.web)
        self.assertEqual(args.printer, "192.0.2.1")

    def test_explicit_subcommands_are_kept(self):
        for command in ("run", "probe", "scan", "setup"):
            args, _ = cli.parse_args(["--printer", "192.0.2.1", command])
            self.assertEqual(args.cmd, command)

    def test_option_value_that_looks_like_a_command(self):
        args, _ = cli.parse_args(["--name", "scan", "--printer", "192.0.2.1"])
        self.assertEqual((args.cmd, args.name), ("run", "scan"))
        args, _ = cli.parse_args(["--printer", "192.0.2.1", "--output", "scan"])
        self.assertEqual((args.cmd, args.output), ("run", Path("scan")))

    def test_no_arguments_is_run(self):
        args, _ = cli.parse_args([])
        self.assertEqual(args.cmd, "run")

    def test_help_and_version_still_exit(self):
        for flag in ("--help", "--version"):
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as cm:
                cli.parse_args([flag])
            self.assertEqual(cm.exception.code, 0)

    def test_missing_printer_is_still_the_clear_error(self):
        with mock.patch("sys.stderr", io.StringIO()) as err, \
                mock.patch("pushscan2folder.__main__.greeting", return_value=None), \
                mock.patch("pushscan2folder.__main__.pause_before_exit"):
            self.assertEqual(cli.main([]), 2)
        self.assertIn("--printer", err.getvalue())

    def test_summary_lines(self):
        args, _ = cli.parse_args(["--printer", "192.0.2.1", "--log-file", "x.log"])
        target = cli.Target("Scan", Path("out"))
        lines = cli.summary_lines(args, [target], None, None)
        text = "\n".join(lines)
        self.assertIn("printer: 192.0.2.1", text)
        self.assertIn("config file: none", text)
        self.assertIn("'Scan' ->", text)
        self.assertIn("web page off", text)
        self.assertIn("log file: x.log", text)
        self.assertEqual(lines[-1], "Press Ctrl+C to stop.")
        self.assertIn("web page: http://h", "\n".join(
            cli.summary_lines(args, [target], Path("c.toml"), "http://h")))


WEB_TOML = """
printer = "192.0.2.1"

[web]
enabled = true
bind = "127.0.0.1"
port = 9090
password_file = "pw.txt"
"""


class WebTableTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {k: v for k, v in os.environ.items()
                                               if not k.startswith("PUSHSCAN_")}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def config_file(self, text=WEB_TOML):
        path = self.dir / "config.toml"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_parse(self):
        cfg = load_config_text(WEB_TOML)
        self.assertEqual((cfg.web_enabled, cfg.web_bind, cfg.web_port, cfg.web_password_file),
                         (True, "127.0.0.1", 9090, "pw.txt"))

    def test_validation(self):
        for text in ('[web]\nenabled = "yes"', "[web]\nport = 0", "[web]\nport = 70000",
                     '[web]\nport = "80"', "[web]\nport = true", "[web]\nbind = 1",
                     '[web]\nbind = ""', "[web]\npassword = \"x\"", "web = 1"):
            with self.assertRaises(ConfigError, msg=text):
                load_config_text(text)

    def test_precedence_file_env_cli(self):
        path = self.config_file()
        args, _ = cli.parse_args(["--config", path, "run"])
        self.assertEqual((args.web, args.web_port, args.web_bind), (True, 9090, "127.0.0.1"))
        os.environ["PUSHSCAN_WEB_PORT"] = "7000"
        os.environ["PUSHSCAN_WEB_BIND"] = "0.0.0.0"
        args, _ = cli.parse_args(["--config", path, "run"])
        self.assertEqual((args.web_port, args.web_bind), (7000, "0.0.0.0"))
        args, _ = cli.parse_args(["--config", path, "run", "--web-port", "6000",
                                  "--web-bind", "::1"])
        self.assertEqual((args.web_port, args.web_bind), (6000, "::1"))

    def test_builtin_when_not_in_file(self):
        args, _ = cli.parse_args(["--config", self.config_file('printer = "192.0.2.1"\n'), "run"])
        self.assertEqual((args.web, args.web_port, args.web_bind), (False, 8080, "0.0.0.0"))

    def test_dump_keeps_web_table(self):
        cfg = load_config_text(WEB_TOML)
        text = dump_config(cfg)
        self.assertIn("[web]", text)
        again = load_config_text(text)
        self.assertEqual((again.web_enabled, again.web_bind, again.web_port,
                          again.web_password_file), (True, "127.0.0.1", 9090, "pw.txt"))
        self.assertNotIn("[web]", dump_config(Config(printer="x")))

    def test_password_from_config_file(self):
        pw = self.dir / "pw.txt"
        pw.write_text("a-long-password\n")
        self.assertEqual(cli.read_web_password(True, str(pw)), "a-long-password")
        with mock.patch.dict(os.environ, {"PUSHSCAN_WEB_PASSWORD": "environment-wins"}):
            self.assertEqual(cli.read_web_password(True, str(pw)), "environment-wins")
        with self.assertRaises(ValueError):
            cli.read_web_password(True, str(self.dir / "missing.txt"))


class ScriptedIO:
    """Answers input() and getpass() from lists and records the output."""

    def __init__(self, answers, passwords=()):
        self.answers, self.passwords, self.lines, self.questions = list(answers), list(passwords), [], []

    def input(self, prompt):
        self.questions.append(prompt)
        return self.answers.pop(0)

    def getpass(self, prompt):
        self.questions.append(prompt)
        return self.passwords.pop(0)

    def out(self, *parts):
        self.lines.append(" ".join(str(p) for p in parts))

    @property
    def text(self):
        return "\n".join(self.lines)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "cfg" / "config.toml"
        # Windows asks more questions; tests that want them patch "win32" themselves.
        patcher = mock.patch.object(sys, "platform", "linux")
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_setup(self, answers, passwords=(), probe=None, autostart_fn=None):
        io_ = ScriptedIO(answers, passwords)
        probe = probe or mock.Mock(return_value=(True, "printer answered, state: Idle"))
        session = wizard.Setup(self.path, input_fn=io_.input, getpass_fn=io_.getpass,
                               probe_fn=probe, autostart_fn=autostart_fn, out=io_.out,
                               default_name="USER  PC")
        return session.run(), io_, probe

    def test_new_config_without_web(self):
        out_dir = self.dir / "scans"
        # printer, name (default), folder, web no, start now (default)
        start, io_, probe = self.run_setup(["192.0.2.7", "", str(out_dir), "", ""])
        self.assertTrue(start)
        probe.assert_called_once_with("192.0.2.7")
        self.assertIn("state: Idle", io_.text)
        self.assertIn("USER  PC", "".join(io_.questions))
        cfg = load_config_text(self.path.read_text(encoding="utf-8"))
        self.assertEqual(cfg.printer, "192.0.2.7")
        self.assertEqual(cfg.output, out_dir)
        self.assertEqual([t.name for t in cfg.targets], ["USER  PC"])
        self.assertEqual(cfg.targets[0].output, ".")  # one target: no subfolder
        self.assertEqual(cfg.build_targets(out_dir, "off")[0].outdir, out_dir)
        self.assertIn(f"go to: {out_dir}", io_.text)
        self.assertFalse(cfg.web_enabled)
        assert_mode(self, self.path, 0o600)
        self.assertIn("pushscan2folder setup", io_.text)

    def test_unreachable_printer_can_be_entered_again(self):
        probe = mock.Mock(side_effect=[(False, "no answer"), (True, "ok")])
        start, io_, _ = self.run_setup(["192.0.2.9", "", "192.0.2.8", "", "", "n", "n"],
                                       probe=probe)
        self.assertFalse(start)
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(load_config_text(self.path.read_text()).printer, "192.0.2.8")

    def test_unreachable_printer_continue_anyway(self):
        probe = mock.Mock(return_value=(False, "no answer"))
        # printer, "use anyway" yes, name, folder, web no, start no
        self.run_setup(["192.0.2.9", "y", "", "", "", "n"], probe=probe)
        self.assertEqual(load_config_text(self.path.read_text()).printer, "192.0.2.9")

    def test_web_password_goes_to_its_own_file(self):
        secret = "correct horse battery"
        start, io_, _ = self.run_setup(
            ["192.0.2.7", "Scan", str(self.dir / "s"), "y", "", "", ""],
            passwords=["short", secret, "other-password", secret, secret])
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn(secret, text)
        self.assertNotIn("short", text)
        cfg = load_config_text(text)
        self.assertTrue(cfg.web_enabled)
        self.assertEqual((cfg.web_port, cfg.web_bind), (8080, "127.0.0.1"))
        pw_file = self.path.with_name("web_password.txt")
        self.assertEqual(cfg.web_password_file, str(pw_file))
        self.assertEqual(pw_file.read_text(encoding="utf-8").strip(), secret)
        assert_mode(self, pw_file, 0o600)
        self.assertIn("at least 8", io_.text)   # "short" refused
        self.assertIn("differ", io_.text)       # mismatch refused
        self.assertIn("0.0.0.0", io_.text)      # LAN explanation
        self.assertNotIn(secret, io_.text)

    def test_example_password_refused(self):
        self.assertIsNotNone(wizard.password_problem(wizard.EXAMPLE_PASSWORD))
        self.assertIsNotNone(wizard.password_problem("1234567"))
        self.assertIsNone(wizard.password_problem("12345678"))

    def test_invalid_port_and_name_are_asked_again(self):
        bad_name = "x" * 40
        start, io_, _ = self.run_setup(
            ["192.0.2.7", bad_name, "Scan", str(self.dir / "s"), "y", "99999", "9000", "",
             "", ""], passwords=["long-enough-pw", "long-enough-pw"])
        cfg = load_config_text(self.path.read_text())
        self.assertEqual(cfg.web_port, 9000)
        self.assertEqual(cfg.targets[0].name, "Scan")

    def test_existing_targets_are_left_alone(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('printer = "192.0.2.1"\n\n[[target]]\nname = "Mine"\n'
                             'output = "mine"\n', encoding="utf-8")
        # 2 = change, printer, web no, start no
        start, io_, _ = self.run_setup(["2", "192.0.2.2", "n", "n"])
        self.assertFalse(start)
        cfg = load_config_text(self.path.read_text())
        self.assertEqual(cfg.printer, "192.0.2.2")
        self.assertEqual([(t.name, t.output) for t in cfg.targets], [("Mine", "mine")])
        self.assertIn("stay as they are", io_.text)
        self.assertNotIn("Panel name", "".join(io_.questions))

    def test_existing_config_unchanged_when_declined(self):
        self.path.parent.mkdir(parents=True)
        original = 'printer = "192.0.2.1"\n'
        self.path.write_text(original, encoding="utf-8")
        start, io_, probe = self.run_setup(["", ""])  # use them (default 1), start now? yes
        self.assertTrue(start)
        probe.assert_not_called()
        self.assertEqual(self.path.read_text(), original)
        self.assertIn("start over", io_.text)
        self.assertFalse(self.path.with_name("config.toml.bak").exists())

    def test_existing_config_choice_is_asked_again(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('printer = "192.0.2.1"\n', encoding="utf-8")
        start, io_, _ = self.run_setup(["4", "1", "n"])
        self.assertFalse(start)
        self.assertIn("Please answer 1, 2 or 3.", io_.text)

    def test_start_over_keeps_a_backup(self):
        self.path.parent.mkdir(parents=True)
        original = 'printer = "192.0.2.1"\n\n[[target]]\nname = "Old"\noutput = "old"\n'
        self.path.write_text(original, encoding="utf-8")
        out_dir = self.dir / "new"
        # 3 = start over, printer, name, folder, web no, start no
        self.run_setup(["3", "192.0.2.5", "New", str(out_dir), "n", "n"])
        cfg = load_config_text(self.path.read_text())
        self.assertEqual([(t.name, t.output) for t in cfg.targets], [("New", ".")])
        self.assertEqual(cfg.output, out_dir)
        self.assertEqual(self.path.with_name("config.toml.bak").read_text(), original)

    def test_invalid_existing_config_is_not_overwritten(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("printer = 5\n", encoding="utf-8")
        with self.assertRaises(ConfigError):
            self.run_setup(["n"])  # start over? no
        self.assertEqual(self.path.read_text(), "printer = 5\n")

    def test_invalid_existing_config_start_over(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("printer = 5\n", encoding="utf-8")
        self.run_setup(["y", "192.0.2.5", "", str(self.dir / "s"), "n", "n"])
        self.assertEqual(load_config_text(self.path.read_text()).printer, "192.0.2.5")
        self.assertEqual(self.path.with_name("config.toml.bak").read_text(), "printer = 5\n")

    def test_autostart_only_on_windows(self):
        calls = []
        answers = ["192.0.2.7", "", str(self.dir / "s"), "", "", "", ""]
        with mock.patch.object(sys, "platform", "linux"):
            self.run_setup(answers, autostart_fn=lambda a: calls.append(a) or 0)
        self.assertEqual(calls, [])
        self.path.unlink()
        # windows: printer, name, folder, web no, open folder, autostart yes (default), start now
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.dir / "local")}):
            _, io_, _ = self.run_setup(answers, autostart_fn=lambda a: calls.append(a) or 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ["--config", str(self.path)])
        self.assertEqual(calls[0][2], "--log-file")
        self.assertTrue(calls[0][3].endswith("pushscan2folder.log"))
        self.assertIn("Autostart:", io_.text)

    def test_main_setup_command_starts_run(self):
        answers = iter(["192.0.2.7", "", str(self.dir / "s"), "", "n"])
        # linux: no autostart question (Windows asks one more)
        with mock.patch("builtins.input", lambda prompt="": next(answers)), \
                mock.patch.object(sys, "platform", "linux"), \
                mock.patch("pushscan2folder.wizard.probe_printer",
                           return_value=(True, "ok")), \
                mock.patch.dict(os.environ, {k: v for k, v in os.environ.items()
                                             if not k.startswith("PUSHSCAN_")}, clear=True), \
                redirect_stdout(io.StringIO()):
            code = cli.main(["--config", str(self.path), "setup"])
        self.assertEqual(code, 0)
        self.assertTrue(self.path.is_file())

    def test_cancel_with_ctrl_d(self):
        with mock.patch("builtins.input", side_effect=EOFError), \
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.dir),
                                             "APPDATA": str(self.dir)}), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["setup"]), 1)


class GreetingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        env = {k: v for k, v in os.environ.items() if not k.startswith("PUSHSCAN_")}
        env.update(XDG_CONFIG_HOME=tmp.name, APPDATA=tmp.name)
        for patcher in (mock.patch.dict(os.environ, env, clear=True), mock.patch("sys.stdin")):
            started = patcher.start()
            self.addCleanup(patcher.stop)
        started.isatty.return_value = True
        self.stdin = started
        self.cfg = self.dir / "pushscan2folder" / "config.toml"
        self.instance = mock.Mock()
        self.instance.is_running.return_value = False

    def greet(self, raw=(), clicked=True):
        with mock.patch.object(cli, "setup_main", return_value=7) as setup, \
                mock.patch.object(cli, "double_click", return_value=clicked), \
                redirect_stdout(io.StringIO()) as out:
            result = cli.greeting(list(raw), self.instance)
        return result, setup.called, out.getvalue()

    def test_manual_start(self):
        self.assertTrue(cli.manual_start([]))
        self.assertFalse(cli.manual_start(["--printer", "x"]))
        self.stdin.isatty.return_value = False  # Docker, service
        self.assertFalse(cli.manual_start([]))
        self.stdin.isatty.return_value = True
        with mock.patch.dict(os.environ, {"PUSHSCAN_PRINTER": "x"}):
            self.assertFalse(cli.manual_start([]))

    def test_no_config_asks_the_setup_questions(self):
        result, setup, out = self.greet(clicked=False)
        self.assertEqual((result, setup), (7, True))
        self.assertIn("Welcome", out)
        self.assertEqual(self.greet(["run"])[:2], (None, False))

    def test_existing_config(self):
        self.cfg.parent.mkdir()
        self.cfg.write_text('printer = "x"\n')
        # typed in a shell (or not Windows): just run
        self.assertEqual(self.greet(clicked=False)[:2], (None, False))
        # double click: use, change or start over
        self.assertEqual(self.greet()[:2], (7, True))
        # already running in the background: say so instead
        self.instance.is_running.return_value = True
        self.instance.read_info.return_value = mock.Mock(pid=42)
        result, setup, out = self.greet()
        self.assertEqual((result, setup), (0, False))
        self.assertIn("PID 42", out)
        self.assertIn("pushscan2folder stop", out)

    def test_double_click_only_on_windows(self):
        with mock.patch.object(cli, "console_process_count", return_value=1), \
                mock.patch.object(cli, "is_windows", return_value=True):
            self.assertTrue(cli.double_click())
        with mock.patch.object(cli, "console_process_count", return_value=2), \
                mock.patch.object(cli, "is_windows", return_value=True):
            self.assertFalse(cli.double_click())
        with mock.patch.object(cli, "console_process_count", return_value=None):
            self.assertFalse(cli.double_click())


class PauseTests(unittest.TestCase):
    def test_decision(self):
        should = cli.should_pause
        self.assertTrue(should("win32", 1, True))
        self.assertFalse(should("win32", 2, True))          # started from a shell
        self.assertFalse(should("win32", 1, False))         # stdin is not interactive
        self.assertFalse(should("win32", 1, True, no_pause=True))
        self.assertFalse(should("win32", None, True))       # count unknown
        self.assertFalse(should("linux", 1, True))
        self.assertFalse(should("darwin", 1, True))

    def test_no_console_off_windows(self):
        with mock.patch.object(sys, "platform", "linux"):
            self.assertIsNone(cli.console_process_count())

    def test_main_pauses_only_when_decided(self):
        with mock.patch("pushscan2folder.__main__._main", return_value=2), \
                mock.patch("pushscan2folder.__main__.pause_before_exit") as pause:
            self.assertEqual(cli.main(["x"]), 2)
        pause.assert_called_once_with(["x"])

    def test_systemexit_is_passed_on_after_the_pause(self):
        with mock.patch("pushscan2folder.__main__._main", side_effect=SystemExit(2)), \
                mock.patch("pushscan2folder.__main__.pause_before_exit") as pause:
            with self.assertRaises(SystemExit) as cm:
                cli.main([])
        self.assertEqual(cm.exception.code, 2)
        pause.assert_called_once()

    def test_pause_waits_for_enter(self):
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch("pushscan2folder.__main__.console_process_count", return_value=1), \
                mock.patch("sys.stdin") as stdin, \
                mock.patch("builtins.input") as ask, \
                mock.patch.dict(os.environ, {}, clear=False), \
                redirect_stdout(io.StringIO()) as out:
            os.environ.pop("PUSHSCAN_NO_PAUSE", None)
            stdin.isatty.return_value = True
            cli.pause_before_exit([])
            ask.assert_called_once()
            self.assertIn("Press Enter to close this window.", out.getvalue())
            ask.reset_mock()
            cli.pause_before_exit([autostart.NO_PAUSE])
            ask.assert_not_called()


class AutostartMarkerTests(unittest.TestCase):
    def test_entry_has_no_pause_marker(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", "pushscan2folder.exe"):
            value = autostart.run_value(["--config", "c.toml"])
            again = autostart.run_value(["--no-pause", "run"])
        self.assertIn('"--no-pause"', value)
        self.assertEqual(again.count("--no-pause"), 1)


if __name__ == "__main__":
    unittest.main()
