"""Config file parsing, validation, dumping and building targets (no network)."""
import os
import stat
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from pushscan2folder import panel
from pushscan2folder.config import (AUTO_KEYS, DEFAULT_AUTO, SAME_FOLDER, Config, ConfigError,
                                    TargetSpec, auto_preset, dump_config, load_config,
                                    load_config_text, parse_config, size_name, write_config)
from pushscan2folder.service import DEFAULT_NEXT_PAGE, Trim

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.toml"

RICH = """
printer = "192.168.1.50"
folder = "/scans"
filename = "scan_{now:%Y-%m-%d_%H-%M-%S}"
next_page = ["document", "photo"]
auto = { resolution = 600, format = "jpeg", size = "letter" }
open_after_scan = true

[advanced]
interval = 2.5
verbose = true
trim = { right = 1, bottom = 2.5 }
adf_trim = { left = 3 }

[web]
enabled = true
bind = "0.0.0.0"
port = 9000
password_file = "web_password.txt"

[[target]]
name = "Paperless"
folder = "Paperless/{now:%Y}"
document_folder = "Docs"
auto_folder = "/abs/auto"
photo_folder = "Bilder"
filename = "{name}_{date}"
next_page = ["document", "auto"]
auto = { format = "pdf" }
open_after_scan = false

[[target]]
name = "Plain"
next_page = []
"""


class ConfigTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

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
    def test_empty_file_and_defaults(self):
        cfg = load_config(self.write(""))
        self.assertEqual(cfg, Config())
        self.assertEqual(cfg.targets, [])
        self.assertEqual(cfg.next_page_types(), DEFAULT_NEXT_PAGE)
        self.assertEqual(cfg.auto_values(), DEFAULT_AUTO)
        self.assertEqual(load_config_text(""), Config())

    def test_every_key(self):
        cfg = load_config(self.write(RICH))
        self.assertEqual((cfg.printer, cfg.folder, cfg.filename),
                         ("192.168.1.50", Path("/scans"), "scan_{now:%Y-%m-%d_%H-%M-%S}"))
        self.assertEqual(cfg.next_page, frozenset({"document", "photo"}))
        self.assertEqual(cfg.next_page_types(), frozenset({"document", "photo"}))
        self.assertEqual(cfg.auto, {"resolution": 600, "format": "jpeg", "size": "letter"})
        self.assertIs(cfg.open_after_scan, True)
        self.assertEqual((cfg.interval, cfg.verbose), (2.5, True))
        self.assertEqual(cfg.trim, Trim(right=1, bottom=2.5))
        self.assertEqual(cfg.adf_trim, Trim(left=3))
        self.assertEqual((cfg.web_enabled, cfg.web_bind, cfg.web_port, cfg.web_password_file),
                         (True, "0.0.0.0", 9000, "web_password.txt"))
        paperless, plain = cfg.targets
        self.assertEqual(paperless, TargetSpec(
            "Paperless", folder="Paperless/{now:%Y}",
            type_folders={"document": "Docs", "auto": "/abs/auto", "photo": "Bilder"},
            filename="{name}_{date}", next_page=frozenset({"document", "auto"}),
            auto={"format": "pdf"}, open_after_scan=False))
        self.assertEqual(plain, TargetSpec("Plain", next_page=frozenset()))

    def test_unset_keys_are_none(self):
        cfg = load_config_text('[[target]]\nname = "A"\n')
        spec = cfg.targets[0]
        self.assertEqual((spec.folder, spec.type_folders, spec.filename, spec.next_page,
                          spec.auto, spec.open_after_scan), (None, {}, None, None, {}, None))
        self.assertEqual((cfg.interval, cfg.verbose, cfg.trim, cfg.adf_trim, cfg.web_port),
                         (None,) * 5)

    def test_auto_table_keys(self):
        for key, value in (("resolution", 75), ("resolution", 600), ("format", "pdf"),
                           ("format", "jpeg"), ("size", "10x15"), ("size", "legal")):
            literal = f'"{value}"' if isinstance(value, str) else value
            cfg = load_config_text(f"auto = {{ {key} = {literal} }}\n")
            self.assertEqual(cfg.auto, {key: value})
        for size in panel.REGIONS:
            self.assertEqual(load_config_text(f'auto = {{ size = "{size}" }}').auto,
                             {"size": size})

    def test_auto_table_invalid(self):
        for bad in ('{ resolution = 200 }', '{ resolution = "300" }', '{ resolution = true }',
                    '{ format = "tiff" }', '{ format = 1 }', '{ size = "a3" }',
                    '{ size = "auto" }', '{ color = "gray" }'):
            self.assertError(f"auto = {bad}\n", "auto")
            self.assertError(f'[[target]]\nname = "A"\nauto = {bad}\n', "auto")
        self.assertError('auto = { color = "gray" }', "known keys",
                         "resolution, format, size")
        self.assertError('auto = "pdf"', "must be a table")

    def test_trim_tables(self):
        cfg = load_config_text("[advanced]\ntrim = { left = 0, top = 50, right = 1.5 }\n")
        self.assertEqual(cfg.trim, Trim(left=0, top=50, right=1.5))
        self.assertEqual(load_config_text("[advanced]\ntrim = { }\n").trim, None)
        for bad in ("{ left = -1 }", "{ left = 51 }", "{ left = true }", '{ left = "1" }',
                    "{ up = 1 }", "{ left = nan }", "{ left = inf }"):
            self.assertError(f"[advanced]\ntrim = {bad}\n", "trim")
            self.assertError(f"[advanced]\nadf_trim = {bad}\n", "adf_trim")
        self.assertError("[advanced]\ntrim = { up = 1 }", "known keys: left, top, right, bottom")
        self.assertError("[advanced]\ntrim = 3", "must be a table")

    def test_open_after_scan(self):
        self.assertIs(load_config_text("open_after_scan = false").open_after_scan, False)
        self.assertError('open_after_scan = "yes"', "true or false")
        self.assertError('open_after_scan = 1', "true or false")
        self.assertError('[[target]]\nname = "A"\nopen_after_scan = "always"', "true or false")

    def test_scalar_types(self):
        self.assertError("printer = 5", "printer")
        self.assertError('printer = ""', "printer")
        self.assertError("folder = 1", "folder")
        self.assertError("[advanced]\ninterval = 0", "greater than 0")
        self.assertError("[advanced]\ninterval = -1", "greater than 0")
        self.assertError('[advanced]\ninterval = "4"', "interval")
        self.assertError("[advanced]\ninterval = true", "interval")
        self.assertError("[advanced]\ninterval = nan", "interval")
        self.assertError("[advanced]\ninterval = inf", "interval")
        self.assertError("[advanced]\nverbose = 1", "verbose")
        self.assertError("[web]\nenabled = 1", "enabled")
        self.assertError("[web]\nbind = 5", "bind")
        self.assertError("[web]\nport = 0", "port")
        self.assertError("[web]\nport = 65536", "port")
        self.assertError('[web]\nport = "80"', "port")
        self.assertError("[web]\nport = true", "port")
        self.assertError("[web]\npassword_file = 1", "password_file")
        self.assertEqual(load_config_text("[advanced]\ninterval = 3").interval, 3.0)
        self.assertEqual(load_config_text("[web]\nport = 65535").web_port, 65535)

    def test_section_must_be_a_table(self):
        self.assertError("advanced = 1", "advanced")
        self.assertError("web = 1", "web")

    def test_unknown_keys_list_the_known_ones(self):
        self.assertError("output = '/x'", 'unknown key "output"', "known keys:", "folder")
        self.assertError("[defaults]\nresolution = 1", 'unknown key "defaults"')
        self.assertError("[advanced]\nignore_panel = true", 'unknown key "ignore_panel"',
                         "known keys: interval, verbose, trim, adf_trim", "[advanced]")
        self.assertError("[web]\nhost = 'x'", 'unknown key "host"',
                         "known keys: enabled, bind, port, password_file", "[web]")
        self.assertError('[[target]]\nname = "A"\nsize = "a4"', 'unknown key "size"',
                         "known keys: name, folder, document_folder", 'target "A"')

    def test_next_page_lists(self):
        for text, expected in (('["document"]', {"document"}), ("[]", set()),
                               ('["photo", "auto", "document"]', {"document", "auto", "photo"}),
                               ('["document", "document"]', {"document"})):
            self.assertEqual(load_config_text(f"next_page = {text}").next_page,
                             frozenset(expected))
        self.assertEqual(load_config_text("next_page = []").next_page_types(), frozenset())
        for bad in ('["scan"]', '"document"', "[1]", 'true', '["document", 2]',
                    '["Document"]', '[["document"]]'):
            self.assertError(f"next_page = {bad}", "next_page", "document, auto, photo")
            self.assertError(f'[[target]]\nname = "A"\nnext_page = {bad}', "next_page")

    def test_targets_basics(self):
        self.assertError('[[target]]\nfolder = "x"', 'missing required key "name"',
                         "target #1")
        self.assertError('[[target]]\nname = "A"\n[[target]]\nfolder = "x"', "target #2")
        self.assertError('[[target]]\nname = "A"\n[[target]]\nname = "A"',
                         'two targets are called "A"')
        self.assertError('target = "x"', "[[target]]")
        self.assertError('[target]\nname = "A"', "[[target]]")
        self.assertError('target = [1]', "must be a table")
        self.assertError('[[target]]\nname = ""', "name")
        self.assertError('[[target]]\nname = 3', "name")
        for bad in ("a.b", "Müller", "x&y", "x" * 32):
            self.assertError(f'[[target]]\nname = "{bad}"', "target")
        cfg = load_config_text('[[target]]\nname = "  Padded  "\n')
        self.assertEqual(cfg.targets[0].name, "Padded")
        self.assertEqual(len(load_config_text(
            '[[target]]\nname = "a"\n[[target]]\nname = "b"\n').targets), 2)

    def test_folder_templates(self):
        cfg = load_config_text('folder = "/s/{now:%Y}"\n'
                               '[[target]]\nname = "A"\nfolder = "x/{date}/{name}"\n'
                               'photo_folder = "p/{time}"\n')
        self.assertEqual(cfg.targets[0].folder, "x/{date}/{name}")
        self.assertEqual(cfg.targets[0].type_folders, {"photo": "p/{time}"})
        for key in ("folder", "document_folder", "auto_folder", "photo_folder"):
            for bad in ("{foo}", "{0}", "{}", "{now.__class__}", "{now:{x}}", "{", "}", "a/{name[0]}"):
                self.assertError(f'[[target]]\nname = "A"\n{key} = \'{bad}\'', key, "folder")
            self.assertError(f'[[target]]\nname = "A"\n{key} = ""', key)
            self.assertError(f'[[target]]\nname = "A"\n{key} = 3', key)

    def test_filename_templates(self):
        self.assertEqual(load_config_text('filename = "{name}-{now:%H}"').filename, "{name}-{now:%H}")
        for bad in ("{foo}", "{", "{now.year}", "  "):
            self.assertError(f"filename = '{bad}'", "filename")
            self.assertError(f'[[target]]\nname = "A"\nfilename = \'{bad}\'', "filename")

    def test_syntax_and_missing_file(self):
        self.assertError("printer = ", "invalid TOML")
        with self.assertRaises(ConfigError) as cm:
            load_config(self.dir / "nope.toml")
        self.assertIn("nope.toml", str(cm.exception))
        self.assertIn("cannot read", str(cm.exception))
        bad = self.dir / "bin.toml"
        bad.write_bytes(b"\xff\xfe\x00")
        with self.assertRaisesRegex(ConfigError, "UTF-8"):
            load_config(bad)

    def test_multi_line_inline_table_gets_a_hint(self):
        # TOML 1.1 (tomllib from Python 3.15 on) allows multi-line inline tables.
        try:
            tomllib.loads("a = {\n b = 1\n}\n")
            multi_line_ok = True
        except tomllib.TOMLDecodeError:
            multi_line_ok = False
        for text in ('auto = {\n  resolution = 300\n}\n',
                     '[advanced]\ntrim = { right = 1,\n bottom = 2 }\n'):
            if multi_line_ok:
                load_config_text(text, "c.toml")
                continue
            with self.assertRaises(ConfigError) as cm:
                load_config_text(text, "c.toml")
            self.assertIn("invalid TOML", str(cm.exception))
            self.assertIn("must stay on one line", str(cm.exception))
            self.assertIn("c.toml", str(cm.exception))
        with self.assertRaises(ConfigError) as cm:
            load_config_text('printer = "x\n')
        self.assertNotIn("one line", str(cm.exception))
        # a brace inside a comment gives no hint
        with self.assertRaises(ConfigError) as cm:
            load_config_text('# { a\nprinter = \n')
        self.assertNotIn("one line", str(cm.exception))

    def test_text_loader_names_and_parse_config(self):
        with self.assertRaises(ConfigError) as cm:
            load_config_text("folder = 3", "web.toml")
        self.assertIn("web.toml", str(cm.exception))
        self.assertEqual(parse_config({"printer": "x"}).printer, "x")
        with self.assertRaises(ConfigError):
            parse_config({"nope": 1})

    def test_repo_example_file(self):
        cfg = load_config(EXAMPLE)
        self.assertIsInstance(cfg, Config)
        self.assertEqual(load_config_text(dump_config(cfg)), cfg)


class DumpTests(ConfigTestBase):
    def test_round_trip_rich(self):
        cfg = load_config_text(RICH)
        self.assertEqual(load_config_text(dump_config(cfg)), cfg)

    def test_round_trip_of_dump_is_stable(self):
        cfg = load_config_text(RICH)
        once = dump_config(cfg)
        self.assertEqual(dump_config(load_config_text(once)), once)

    def test_empty_config(self):
        text = dump_config(Config())
        self.assertEqual(load_config_text(text), Config())
        self.assertTrue(text.startswith("# pushscan2folder configuration."))
        self.assertIn("need a restart", text)

    def test_hand_built_config(self):
        cfg = Config(printer="x", folder=Path("/a b/ü"), next_page=frozenset(),
                     auto={"size": "a4", "resolution": 75}, interval=4.0, web_port=1,
                     trim=Trim(top=0.5), adf_trim=Trim(),
                     targets=[TargetSpec("PC", folder=SAME_FOLDER),
                              TargetSpec("Old", open_after_scan=False,
                                         type_folders={"photo": 'we"ird\\path'},
                                         filename='x_"{name}"')])
        again = load_config_text(dump_config(cfg))
        self.assertEqual(again.targets, cfg.targets)
        self.assertEqual((again.folder, again.next_page, again.auto, again.trim),
                         (cfg.folder, frozenset(), cfg.auto, Trim(top=0.5)))

    def test_inline_tables_stay_on_one_line(self):
        text = dump_config(load_config_text(RICH))
        for line in text.splitlines():
            if "{" in line.split("#")[0] and "{now" not in line and "{name" not in line:
                self.assertIn("}", line)

    def test_empty_values_are_left_out(self):
        text = dump_config(Config(printer="x", auto={}, trim=Trim()))
        body = [l.split("  #")[0].rstrip() for l in text.splitlines()
                if not l.startswith("#") and l.strip()]
        self.assertEqual(body, ['printer = "x"'])

    def test_examples_in_the_dump_work_when_uncommented(self):
        text = dump_config(Config(printer="x", targets=[TargetSpec("PC")]))
        self.assertNotIn("{name}", text.split("[[target]]")[0].replace("{name} {date}", ""))
        body, example = text.rsplit("\n\n", 1)
        self.assertEqual(len(load_config_text(body).targets), 1)
        uncommented = [l[2:] for l in example.splitlines()[1:]]
        cfg = load_config_text(body + "\n\n" + "\n".join(uncommented))
        self.assertEqual(len(cfg.targets), 2)
        self.assertEqual(cfg.targets[1].next_page, frozenset())
        self.assertEqual(cfg.targets[1].auto, {"resolution": 600, "format": "jpeg"})

    def test_commented_global_examples_work_when_uncommented(self):
        body = dump_config(Config(printer="x")).rsplit("\n\n", 1)[0]
        lines = body.splitlines()
        hits = 0
        for i, line in enumerate(lines):
            if line.startswith("# ") and " = " in line and not line.startswith("# Changes"):
                try:
                    load_config_text("\n".join(lines[:i] + [line[2:]] + lines[i + 1:]))
                except ConfigError:
                    continue
                hits += 1
        self.assertGreaterEqual(hits, 3)

    def test_next_page_is_written_in_a_fixed_order(self):
        text = dump_config(Config(next_page=frozenset({"photo", "document"})))
        self.assertIn('next_page = ["document", "photo"]', text)

    def test_floats_without_noise(self):
        text = dump_config(Config(interval=3.0, trim=Trim(right=1.0)))
        self.assertIn("interval = 3 ", text)
        self.assertIn("{ right = 1 }", text)


class BuildTargetsTests(ConfigTestBase):
    def test_relative_and_absolute_folders(self):
        cfg = load_config_text(
            '[[target]]\nname = "Mein Ordner"\n'
            '[[target]]\nname = "B"\nfolder = "sub/dir"\n'
            '[[target]]\nname = "C"\nfolder = "/abs/c"\n'
            '[[target]]\nname = "D"\nfolder = "."\n')
        base = Path("/scans")
        t = cfg.build_targets(base)
        self.assertEqual([x.name for x in t], ["Mein Ordner", "B", "C", "D"])
        self.assertEqual([x.outdir for x in t],
                         [base / "Mein_Ordner", base / "sub/dir", Path("/abs/c"), base])

    def test_type_folders(self):
        cfg = load_config_text('[[target]]\nname = "A"\nphoto_folder = "Bilder"\n'
                               'document_folder = "/abs/d"\nauto_folder = "x/{now:%Y}"\n')
        (t,) = cfg.build_targets(Path("/scans"))
        self.assertEqual(t.outdir, Path("/scans/A"))
        self.assertEqual(t.type_dirs, {"document": Path("/abs/d"), "auto": Path("/scans/x/{now:%Y}"),
                                       "photo": Path("/scans/Bilder")})
        (t,) = load_config_text('[[target]]\nname = "A"\n').build_targets(Path("/s"))
        self.assertEqual(t.type_dirs, {})

    def test_next_page_none_versus_set(self):
        cfg = load_config_text('next_page = ["photo"]\n[[target]]\nname = "A"\n'
                               '[[target]]\nname = "B"\nnext_page = []\n'
                               '[[target]]\nname = "C"\nnext_page = ["auto"]\n')
        a, b, c = cfg.build_targets(Path("/s"))
        self.assertIsNone(a.multipage)            # keeps the global list
        self.assertEqual(b.multipage, frozenset())  # explicitly none
        self.assertEqual(c.multipage, frozenset({"auto"}))

    def test_auto_preset_only_what_the_target_sets(self):
        cfg = load_config_text('auto = { resolution = 600, format = "jpeg" }\n'
                               '[[target]]\nname = "A"\n'
                               '[[target]]\nname = "B"\nauto = { resolution = 150, size = "10x15" }\n')
        a, b = cfg.build_targets(Path("/s"))
        self.assertEqual(a.preset, {})   # global auto is applied by the caller
        self.assertEqual(b.preset, {"resolution": 150, "width": 1181, "height": 1772})

    def test_filename_and_open_after_scan_carried_over(self):
        cfg = load_config_text('[[target]]\nname = "A"\nfilename = "{name}"\n'
                               'open_after_scan = true\n[[target]]\nname = "B"\n')
        a, b = cfg.build_targets(Path("/s"))
        self.assertEqual((a.filename, a.open_after_scan), ("{name}", True))
        self.assertEqual((b.filename, b.open_after_scan), (None, None))

    def test_auto_values_merge_over_builtins(self):
        cfg = load_config_text('auto = { format = "jpeg" }')
        self.assertEqual(cfg.auto_values(), {"resolution": 300, "format": "jpeg", "size": "a4"})
        self.assertEqual(Config().auto, {})   # the field itself stays unset

    def test_auto_preset(self):
        self.assertEqual(auto_preset({}), {})
        self.assertEqual(auto_preset({"resolution": 75, "format": "pdf", "size": "a4"}),
                         {"resolution": 75, "fmt": "pdf", "width": 2480, "height": 3508})
        merged = auto_preset(load_config_text('auto = { size = "legal" }').auto_values())
        self.assertEqual(merged, {"resolution": 300, "fmt": "pdf", "width": 2550, "height": 4200})
        self.assertEqual(set(AUTO_KEYS), set(DEFAULT_AUTO))

    def test_size_name(self):
        for name, (w, h) in panel.REGIONS.items():
            self.assertEqual(size_name({"width": w, "height": h}), name)
        self.assertIsNone(size_name({"width": 1, "height": 2}))
        self.assertIsNone(size_name({}))

    def test_target_spec_folders(self):
        spec = TargetSpec("Mein Ordner", type_folders={"photo": "P", "document": "D"})
        self.assertEqual(spec.folders(), ["Mein_Ordner", "D", "P"])
        self.assertEqual(TargetSpec("A", folder="x").folders(), ["x"])


class WriteConfigTests(ConfigTestBase):
    def test_writes_and_creates_parent(self):
        path = self.dir / "new" / "sub" / "config.toml"
        write_config(path, "printer = 'x'\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "printer = 'x'\n")
        self.assertEqual([p.name for p in path.parent.iterdir()], ["config.toml"])

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_new_file_is_private_and_existing_mode_is_kept(self):
        path = self.dir / "c.toml"
        write_config(path, "a = 1")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        os.chmod(path, 0o640)
        write_config(path, "a = 2")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        self.assertEqual(path.read_text(), "a = 2")

    def test_round_trip_with_dump(self):
        path = self.dir / "c.toml"
        cfg = load_config_text(RICH)
        write_config(path, dump_config(cfg))
        self.assertEqual(load_config(path), cfg)

    def test_falls_back_to_in_place_write_when_rename_is_refused(self):
        import errno
        path = self.dir / "c.toml"
        path.write_text("old")
        with mock.patch("pushscan2folder.config.replace_file",
                        side_effect=OSError(errno.EBUSY, "busy")):
            write_config(path, "new")
        self.assertEqual(path.read_text(), "new")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["c.toml"])  # temp file removed

    def test_other_errors_are_raised_and_leave_no_temp_file(self):
        import errno
        path = self.dir / "c.toml"
        path.write_text("old")
        with mock.patch("pushscan2folder.config.replace_file",
                        side_effect=OSError(errno.ENOSPC, "full")):
            with self.assertRaises(OSError):
                write_config(path, "new")
        self.assertEqual(path.read_text(), "old")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["c.toml"])

    def test_new_file_does_not_fall_back(self):
        import errno
        path = self.dir / "c.toml"
        with mock.patch("pushscan2folder.config.replace_file",
                        side_effect=OSError(errno.EBUSY, "busy")):
            with self.assertRaises(OSError):
                write_config(path, "new")
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
