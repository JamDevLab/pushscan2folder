"""Config file parsing, validation and precedence (no network)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pushscan2folder import __main__ as cli
from pushscan2folder import panel
from pushscan2folder.config import (Config, ConfigError, dump_config, load_config,
                                    load_config_text)
from pushscan2folder.platform_support import default_config_path, default_output
from pushscan2folder.service import Trim

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.toml"

FULL = """
printer = "192.168.1.50"
output = "/scans"
interval = 3
verbose = true
multipage = "auto"

[defaults]
resolution = 150
color = "gray"
format = "jpeg"
source = "adf"
size = "letter"

[[target]]
name = "scan1"

[[target]]
name = "paperless"
output = "/consume"
document_multipage = true

[target.auto]
resolution = 300
format = "pdf"
size = "a4"
multipage = true

[[target]]
name = "archiv"
output = "archiv"
document_multipage = false

[target.auto]
resolution = 600
format = "jpeg"
"""


class ConfigTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        # Isolate from the real environment and the real home directory.
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in [k for k in os.environ if k.startswith("PUSHSCAN_")]:
            del os.environ[key]
        os.environ["XDG_CONFIG_HOME"] = str(self.dir / "xdg")
        os.environ["APPDATA"] = str(self.dir / "appdata")   # Windows equivalent

    def write(self, text, name="config.toml"):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def assertError(self, text, *fragments):
        with self.assertRaises(ConfigError) as cm:
            load_config(self.write(text))
        for fragment in fragments:
            self.assertIn(fragment, str(cm.exception))
        self.assertIn("config.toml", str(cm.exception))


class ParseTests(ConfigTestBase):
    def test_full_example(self):
        cfg = load_config(self.write(FULL))
        self.assertEqual((cfg.printer, cfg.output, cfg.interval), ("192.168.1.50", Path("/scans"), 3.0))
        self.assertTrue(cfg.verbose)
        self.assertEqual((cfg.resolution, cfg.color, cfg.format, cfg.source, cfg.size),
                         (150, "gray", "jpeg", "adf", "letter"))
        scan1, paperless, archiv = cfg.build_targets(Path("/scans"), "auto")
        self.assertEqual((scan1.name, scan1.outdir, scan1.preset, scan1.multipage),
                         ("scan1", Path("/scans/scan1"), {}, None))
        self.assertEqual(paperless.outdir, Path("/consume"))
        self.assertEqual(paperless.preset, {"resolution": 300, "fmt": "pdf",
                                            "width": panel.REGIONS["a4"][0],
                                            "height": panel.REGIONS["a4"][1]})
        self.assertEqual(paperless.multipage, frozenset({"document", "auto"}))
        self.assertEqual(archiv.outdir, Path("/scans/archiv"))
        self.assertEqual(archiv.preset, {"resolution": 600, "fmt": "jpeg"})
        # global "auto", document_multipage = false: nothing left
        self.assertEqual(archiv.multipage, frozenset({"auto"}))

    def test_multipage_relative_to_global_mode(self):
        cfg = load_config(self.write(FULL))
        _, paperless, archiv = cfg.build_targets(Path("x"), "off")
        self.assertEqual(paperless.multipage, frozenset({"document", "auto"}))
        self.assertEqual(archiv.multipage, frozenset())
        _, _, archiv = cfg.build_targets(Path("x"), "both")
        self.assertEqual(archiv.multipage, frozenset({"auto"}))

    def test_repo_example_file(self):
        cfg = load_config(EXAMPLE)
        self.assertEqual([t.name for t in cfg.targets], ["Scans", "Paperless", "Archive"])
        self.assertEqual(cfg.printer, "192.168.1.50")

    def test_empty_file_and_no_targets(self):
        cfg = load_config(self.write(""))
        self.assertEqual(cfg.targets, [])
        self.assertIsNone(cfg.printer)


class ValidationTests(ConfigTestBase):
    def test_unknown_keys(self):
        self.assertError("colour = 1", 'unknown key "colour"')
        self.assertError('[defaults]\nsized = "a4"', "[defaults]", 'unknown key "sized"')
        self.assertError('[[target]]\nname = "archiv"\nresolutoin = 1',
                         'target "archiv"', 'unknown key "resolutoin"')
        self.assertError('[[target]]\nname = "a"\n[target.auto]\nresolutoin = 1',
                         'target "a".auto', 'unknown key "resolutoin"')

    def test_name_with_characters_the_panel_cannot_show(self):
        self.assertError('[[target]]\nname = "Müller"', 'target "Müller"', "cannot show")

    def test_wrong_types_and_values(self):
        self.assertError("verbose = 1", '"verbose"', "true or false")
        self.assertError('interval = "fast"', '"interval"')
        self.assertError("interval = 0", '"interval"')
        self.assertError("printer = 5", '"printer"')
        self.assertError('multipage = "all"', "document, auto, both, off")
        self.assertError("[defaults]\nresolution = 200", "75, 150, 300, 600")
        self.assertError("[defaults]\nresolution = true", "75, 150, 300, 600")
        self.assertError('[defaults]\ncolor = "mono"', "color, gray")
        self.assertError('[defaults]\nformat = "tiff"', "pdf, jpeg")
        self.assertError('[defaults]\nsource = "x"', "auto, platen, adf")
        self.assertError('[defaults]\nsize = "a3"', "a4, letter, legal, 10x15, 13x18")
        self.assertError('defaults = 3', '"defaults"')
        self.assertError('target = "x"', "array of tables")
        self.assertError('[[target]]\nname = "a"\ndocument_multipage = "yes"', "true or false")
        self.assertError('[[target]]\nname = "a"\nauto = 1', '"auto"')
        self.assertError('[[target]]\nname = "a"\n[target.auto]\nmultipage = 1', "true or false")
        self.assertError('[[target]]\nname = "a"\n[target.auto]\ncolor = "gray"', 'target "a"',
                         'unknown key "color"')

    def test_names(self):
        self.assertError('[[target]]\noutput = "x"', 'missing required key "name"')
        self.assertError('[[target]]\nname = ""', '"name"')
        self.assertError('[[target]]\nname = 3', '"name"')
        self.assertError(f'[[target]]\nname = "{"x" * 32}"', "31")
        self.assertError('[[target]]\nname = "a"\n[[target]]\nname = "a"', 'duplicate target name "a"')

    def test_syntax_and_missing_file(self):
        self.assertError("printer = ", "invalid TOML")
        with self.assertRaises(ConfigError):
            load_config(self.dir / "missing.toml")


class TextLoaderTests(ConfigTestBase):
    def test_same_result_as_the_file_loader(self):
        text = EXAMPLE.read_text(encoding="utf-8")
        self.assertEqual(dump_config(load_config_text(text)),
                         dump_config(load_config(EXAMPLE)))

    def test_errors_carry_the_name_and_line(self):
        with self.assertRaises(ConfigError) as cm:
            load_config_text('printer = "x"\ninterval = \n', "my.toml")
        self.assertIn("my.toml", str(cm.exception))
        self.assertIn("line 2", str(cm.exception))

    def test_same_validation(self):
        for text in ('resolution = 1', '[defaults]\nresolution = 100',
                     '[defaults]\ntrim_left = 51', 'interval = 0', 'interval = nan',
                     '[[target]]\nname = "a"\n[[target]]\nname = "a"'):
            with self.assertRaises(ConfigError, msg=text):
                load_config_text(text)

    def test_empty_text_is_an_empty_config(self):
        self.assertEqual(load_config_text(""), Config())


class FilenameConfigTests(ConfigTestBase):
    def test_defaults_and_target(self):
        cfg = load_config(self.write('[defaults]\nfilename = "{date}_{time}"\n\n'
                                     '[[target]]\nname = "Bills"\nfilename = "bill_{date}"\n'
                                     '\n[[target]]\nname = "Other"\n'))
        self.assertEqual(cfg.filename, "{date}_{time}")
        targets = cfg.build_targets(self.dir, "off")
        self.assertEqual([t.filename for t in targets], ["bill_{date}", None])
        again = load_config(self.write(dump_config(cfg), "again.toml"))
        self.assertEqual((again.filename, again.targets[0].filename),
                         ("{date}_{time}", "bill_{date}"))

    def test_invalid_template(self):
        self.assertError('[defaults]\nfilename = "{now.__class__}"', "filename", "[defaults]")
        self.assertError('[[target]]\nname = "a"\nfilename = "{x}"', "filename", "target")
        self.assertError('[defaults]\nfilename = ""', "filename")


class TrimConfigTests(ConfigTestBase):
    def test_parse_and_defaults(self):
        cfg = load_config(self.write("[defaults]\ntrim_right = 3\ntrim_bottom = 2.5\n"))
        self.assertEqual(cfg.trim(), Trim(right=3.0, bottom=2.5))
        self.assertIsNone(cfg.trim_left)
        self.assertFalse(Config().trim())

    def test_validation(self):
        for value in ("true", '"3"', "-1", "50.5", "[1]"):
            self.assertError(f"[defaults]\ntrim_left = {value}", "trim_left", "[defaults]")
        self.assertError("trim_left = 1", 'unknown key "trim_left"')
        self.assertError("[defaults]\ntrim_up = 1", 'unknown key "trim_up"')
        load_config(self.write("[defaults]\ntrim_left = 0\ntrim_top = 50\n"))

    def test_dump_round_trip(self):
        cfg = load_config(self.write("[defaults]\ntrim_left = 1\ntrim_top = 0\n"
                                     "trim_right = 3\ntrim_bottom = 2.5\n"))
        again = load_config(self.write(dump_config(cfg), "again.toml"))
        self.assertEqual(again.trim(), Trim(1, 0, 3, 2.5))
        self.assertNotIn("trim", dump_config(Config(resolution=300)))

    def test_precedence(self):
        path = self.write("[defaults]\ntrim_left = 1\ntrim_bottom = 2\n")
        args, _ = cli.parse_args(["--config", str(path), "run"])
        self.assertEqual(args.trim, Trim(left=1, bottom=2))
        os.environ["PUSHSCAN_TRIM"] = "right=3"
        args, _ = cli.parse_args(["--config", str(path), "run"])
        self.assertEqual(args.trim, Trim(right=3))  # replaces the file values as a whole
        args, _ = cli.parse_args(["--config", str(path), "run", "--trim", "top=4,right=5"])
        self.assertEqual(args.trim, Trim(top=4, right=5))
        args, _ = cli.parse_args(["--config", str(path), "run", "--trim", ""])
        self.assertFalse(args.trim)

    def test_builtin_default_is_no_trim(self):
        args, _ = cli.parse_args(["run"])
        self.assertFalse(args.trim)

    def test_bad_input_exits_2(self):
        for argv, env in ((["run", "--trim", "right=99"], {}), (["run", "--trim", "x"], {}),
                          (["run"], {"PUSHSCAN_TRIM": "right=abc"})):
            with mock.patch.dict(os.environ, env), \
                    mock.patch("sys.stderr"), self.assertRaises(SystemExit) as cm:
                cli.parse_args(argv)
            self.assertEqual(cm.exception.code, 2)

    def test_example_has_trim_keys_at_zero(self):
        cfg = load_config(EXAMPLE)
        self.assertEqual((cfg.trim_left, cfg.trim_top, cfg.trim_right, cfg.trim_bottom),
                         (0.0, 0.0, 0.0, 0.0))


class PrecedenceTests(ConfigTestBase):
    def parse(self, argv, config=FULL):
        path = self.write(config)
        return cli.parse_args(["--config", str(path), *argv])

    def test_config_values_become_defaults(self):
        args, cfg = self.parse(["run"])
        self.assertEqual(args.printer, "192.168.1.50")
        self.assertEqual(args.output, Path("/scans"))
        self.assertEqual((args.interval, args.resolution, args.color, args.format, args.source),
                         (3.0, 150, "gray", "jpeg", "adf"))
        self.assertEqual(args.multipage, "auto")
        self.assertTrue(args.verbose)

    def test_env_over_config_and_cli_over_env(self):
        os.environ.update(PUSHSCAN_PRINTER="env-printer", PUSHSCAN_RESOLUTION="600",
                          PUSHSCAN_MULTIPAGE="off", PUSHSCAN_VERBOSE="0")
        args, _ = self.parse(["run"])
        self.assertEqual((args.printer, args.resolution, args.multipage), ("env-printer", 600, "off"))
        args, _ = self.parse(["--printer", "cli-printer", "run", "--resolution", "75"])
        self.assertEqual((args.printer, args.resolution), ("cli-printer", 75))

    def test_web_overrides(self):
        os.environ.update(PUSHSCAN_INTERVAL="9", PUSHSCAN_TRIM="left=2", PUSHSCAN_PRINTER="p")
        argv = ["--config", str(self.write(FULL)), "run", "--format=jpeg", "--res", "75"]
        args, cfg = cli.parse_args(argv)
        overrides, effective = cli.web_overrides(args, cfg, argv)
        self.assertEqual(overrides["interval"], "environment variable PUSHSCAN_INTERVAL")
        self.assertEqual(overrides["trim_left"], "environment variable PUSHSCAN_TRIM")
        self.assertEqual(overrides["trim_bottom"], "environment variable PUSHSCAN_TRIM")
        self.assertEqual(overrides["format"], "command line option --format")
        self.assertEqual(overrides["resolution"], "command line option --resolution")
        self.assertEqual(overrides["printer"], "environment variable PUSHSCAN_PRINTER")
        for key in ("color", "source", "multipage", "ignore_panel", "output"):
            self.assertNotIn(key, overrides)
        self.assertEqual((effective["interval"], effective["format"], effective["resolution"],
                          effective["color"], effective["size"], effective["trim_left"]),
                         ("9", "jpeg", "75", "gray", "letter", "2"))

    def test_web_overrides_none(self):
        argv = ["--config", str(self.write(FULL)), "run"]
        args, cfg = cli.parse_args(argv)
        overrides, effective = cli.web_overrides(args, cfg, argv)
        self.assertEqual(overrides, {})
        self.assertEqual(effective["size"], "letter")

    def test_builtin_defaults_without_config(self):
        args, cfg = cli.parse_args(["run"])
        self.assertEqual((args.output, args.interval, args.resolution, args.multipage),
                         (default_output(), 4.0, 300, "document"))
        self.assertEqual(cfg.targets, [])

    def test_default_location_and_missing_explicit(self):
        xdg = default_config_path().parent   # under xdg/ or appdata/ (Windows)
        self.assertTrue(xdg.is_relative_to(self.dir))
        xdg.mkdir(parents=True)
        (xdg / "config.toml").write_text('printer = "10.0.0.9"', encoding="utf-8")
        args, _ = cli.parse_args(["run"])
        self.assertEqual(args.printer, "10.0.0.9")
        with self.assertRaises(ConfigError):
            cli.parse_args(["--config", str(self.dir / "nope.toml"), "run"])
        os.environ["PUSHSCAN_CONFIG"] = str(self.dir / "nope.toml")
        with self.assertRaises(ConfigError):
            cli.parse_args(["run"])

    def test_default_name_without_passwd_entry(self):
        # Docker on a NAS: the uid from "user:" has no passwd entry.
        with mock.patch.object(cli.getpass, "getuser", side_effect=KeyError("uid not found")), \
                mock.patch.object(cli.socket, "gethostname", return_value="nas"):
            self.assertEqual(cli.default_name(), "scan  nas")

    def test_example_web_password_is_rejected(self):
        os.environ["PUSHSCAN_WEB_PASSWORD"] = cli.EXAMPLE_PASSWORD
        with self.assertRaises(ValueError):
            cli.read_web_password()
        compose = (EXAMPLE.parent / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn(cli.EXAMPLE_PASSWORD, compose)

    def test_main_reports_missing_config(self):
        self.assertEqual(cli.main(["--config", str(self.dir / "nope.toml"), "run"]), 2)

    def test_targets(self):
        args, cfg = self.parse(["run"])
        names = [t.name for t in cli.resolve_targets(args, cfg, "me")]
        self.assertEqual(names, ["scan1", "paperless", "archiv"])
        os.environ["PUSHSCAN_TARGETS"] = "only"
        args, cfg = self.parse(["run"])
        self.assertEqual([t.name for t in cli.resolve_targets(args, cfg, "me")], ["only"])
        args, cfg = self.parse(["run", "--targets", "cli1,cli2"])
        self.assertEqual([t.name for t in cli.resolve_targets(args, cfg, "me")], ["cli1", "cli2"])
        # no targets anywhere -> single --name target
        del os.environ["PUSHSCAN_TARGETS"]
        args, cfg = self.parse(["run"], config='printer = "x"')
        self.assertEqual([t.name for t in cli.resolve_targets(args, cfg, "me")], ["me"])

    def test_config_targets_use_effective_multipage_mode(self):
        args, cfg = self.parse(["run", "--multipage", "both"])
        archiv = cli.resolve_targets(args, cfg, "me")[2]
        self.assertEqual(archiv.multipage, frozenset({"auto"}))

    def test_fallback_size(self):
        args, cfg = self.parse(["run"])
        s = cli.fallback_settings(args, cfg)
        self.assertEqual((s.width, s.height), panel.REGIONS["letter"])
        self.assertEqual((s.fmt, s.color, s.resolution, s.source), ("jpeg", "gray", 150, "adf"))
        args, cfg = self.parse(["probe"], config='printer = "x"')
        self.assertEqual(cfg.size, None)


if __name__ == "__main__":
    unittest.main()
