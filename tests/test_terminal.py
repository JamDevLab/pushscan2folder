"""Clickable paths in the terminal (OSC 8)."""
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

from pushscan2folder import terminal


class Tty(io.StringIO):
    def isatty(self):
        return True


class LinkTests(unittest.TestCase):
    def test_plain_text_when_not_a_terminal(self):
        self.assertEqual(terminal.link("/a/b.toml", io.StringIO(), {"TERM": "xterm"}),
                         "/a/b.toml")

    @unittest.skipIf(sys.platform == "win32", "a Linux path")
    def test_linux_terminal_gets_a_link(self):
        with mock.patch.object(sys, "platform", "linux"):
            text = terminal.link(Path("/home/u/my config.toml"), Tty(), {"TERM": "xterm"})
        self.assertEqual(text, "\033]8;;file:///home/u/my%20config.toml\033\\"
                               "/home/u/my config.toml\033]8;;\033\\")

    @unittest.skipUnless(sys.platform == "win32", "a Windows path")
    def test_windows_path_gets_a_link(self):
        text = terminal.link(Path(r"C:\Users\u\my config.toml"), Tty(), {"WT_SESSION": "x"})
        self.assertEqual(text, "\033]8;;file:///C:/Users/u/my%20config.toml\033\\"
                               "C:\\Users\\u\\my config.toml\033]8;;\033\\")

    def test_dumb_terminal_gets_text(self):
        with mock.patch.object(sys, "platform", "linux"):
            self.assertEqual(terminal.link("/a", Tty(), {"TERM": "dumb"}), "/a")
            self.assertEqual(terminal.link("/a", Tty(), {}), "/a")

    def test_windows_only_in_windows_terminal(self):
        with mock.patch.object(sys, "platform", "win32"):
            self.assertFalse(terminal.supports_links(Tty(), {}))
            self.assertTrue(terminal.supports_links(Tty(), {"WT_SESSION": "x"}))

    def test_wsl_path_goes_through_wsl_localhost(self):
        with mock.patch.object(sys, "platform", "linux"):
            uri = terminal.file_uri(Path("/home/u/a b.toml"), {"WSL_DISTRO_NAME": "Ubuntu 24"})
        self.assertEqual(uri, "file://wsl.localhost/Ubuntu%2024/home/u/a%20b.toml")

    def test_broken_stream(self):
        class Broken:
            def isatty(self):
                raise ValueError("closed")
        self.assertFalse(terminal.supports_links(Broken(), {"TERM": "xterm"}))


if __name__ == "__main__":
    unittest.main()
