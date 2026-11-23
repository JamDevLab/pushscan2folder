"""`pushscan2folder check`: validate the config file and show what it does."""
import contextlib
import io
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from pushscan2folder import __main__ as cli
from pushscan2folder.config import load_config_text


def run_check(text: str | None, env: dict | None = None) -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory() as d:
        argv = []
        if text is not None:
            path = Path(d) / "config.toml"
            path.write_text(text, encoding="utf-8")
            argv = ["--config", str(path)]
        out, err = io.StringIO(), io.StringIO()
        clean = {k: v for k, v in os.environ.items() if not k.startswith("PUSHSCAN_")}
        with mock.patch.dict(os.environ, {**clean, **(env or {})}, clear=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv + ["check"])
        return code, out.getvalue(), err.getvalue()


class CheckCommandTests(unittest.TestCase):
    def test_valid_file_shows_targets_and_folders(self):
        code, out, _ = run_check('printer = "10.0.0.2"\nfolder = "/s"\n'
                                 '[[target]]\nname = "Archive"\nfolder = "A/{now:%Y}"\n'
                                 'photo_folder = "Photos"\nnext_page = []\n')
        self.assertEqual(code, 0)
        self.assertIn("printer: 10.0.0.2", out)
        self.assertIn(f"folder: {Path('/s/A') / str(datetime.now().year)}", out)
        self.assertIn(f"photo scans: {Path('/s/Photos')}", out)
        self.assertIn("next page dialog: none", out)
        self.assertTrue(out.rstrip().endswith("OK"))

    def test_error_names_the_key_and_exits_2(self):
        code, out, err = run_check('printer = "x"\n[[target]]\nname = "a"\nauto = { size = "a5" }\n')
        self.assertEqual(code, 2)
        self.assertIn('target "a": auto: "size" must be one of', err)
        self.assertEqual(out, "")

    def test_missing_printer_is_reported(self):
        code, out, _ = run_check('folder = "/s"\n')
        self.assertEqual(code, 2)
        self.assertIn("printer: NOT SET", out)

    def test_environment_wins_like_in_run(self):
        code, out, _ = run_check('printer = "x"\nfolder = "/s"\n',
                                 {"PUSHSCAN_PRINTER": "10.9.9.9", "PUSHSCAN_FOLDER": "/env"})
        self.assertEqual(code, 0)
        self.assertIn("printer: 10.9.9.9", out)
        self.assertIn(f"base folder: {Path('/env')}", out)

    def test_check_lines_without_targets(self):
        cfg = load_config_text('auto = { resolution = 600 }\n')
        lines = cli.check_lines(cfg, None, "p", Path("/s"), now=datetime(2026, 1, 2))
        self.assertIn("document type Auto: 600 dpi, pdf, a4", lines)
        self.assertTrue(any(line.startswith("targets: none") for line in lines))


if __name__ == "__main__":
    unittest.main()
