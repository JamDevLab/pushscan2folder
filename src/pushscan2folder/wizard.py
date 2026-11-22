"""Interactive setup (`pushscan2folder setup`): asks a few questions in the
console and writes the config file.

All input and output goes through arguments (input_fn, getpass_fn, probe_fn,
out), so the flow can be tested without a console or a network."""
from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Callable

from . import platform_support, protocol
from .config import Config, ConfigError, TargetSpec, dump_config, load_config, write_config
from .escl import EsclClient
from .web import MIN_PASSWORD_LENGTH

EXAMPLE_PASSWORD = "change-me-please"  # placeholder in docker-compose.yml
DEFAULT_PORT = 8080
DEFAULT_BIND = "127.0.0.1"
PASSWORD_FILE_NAME = "web_password.txt"


def password_problem(password: str) -> str | None:
    """Why `password` is not accepted for the web page, or None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"the web password must have at least {MIN_PASSWORD_LENGTH} characters"
    if password == EXAMPLE_PASSWORD:
        return "replace the example web password with your own"
    return None


def probe_printer(host: str, timeout: float = 5.0) -> tuple[bool, str]:
    """Ask the printer for its eSCL status with a short timeout.
    Returns (reachable, text for the user)."""
    try:
        status = EsclClient(host, timeout=timeout).status()
    except Exception as exc:  # any network or protocol error means "not reachable"
        return False, f"no answer from {host}: {exc}"
    state = status.get("state") or "unknown"
    return True, f"printer answered, state: {state}"


def write_password_file(path: Path, password: str) -> None:
    """Store the web password in its own file, private (0600) where the
    platform supports it. Raises OSError."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(password + "\n")
    try:
        os.chmod(path, 0o600)  # also for a file that existed before
    except OSError:
        pass


class Setup:
    def __init__(self, config_path: Path, *, input_fn: Callable[[str], str] | None = None,
                 getpass_fn: Callable[[str], str] | None = None,
                 probe_fn: Callable[[str], tuple[bool, str]] | None = None,
                 autostart_fn: Callable[[list[str]], int] | None = None,
                 out: Callable[..., None] = print, default_name: str = "scan"):
        self.path = Path(config_path)
        # looked up here, not as default values, so tests can replace them
        self.input = input_fn or input
        self.getpass = getpass_fn or getpass.getpass
        self.probe = probe_fn or probe_printer
        self.autostart_fn, self.out, self.default_name = autostart_fn, out, default_name

    # --- small prompts ---------------------------------------------------------

    def ask(self, question: str, default: str | None = None) -> str:
        suffix = f" [{default}]" if default else ""
        answer = self.input(f"{question}{suffix}: ").strip()
        return answer or (default or "")

    def yes_no(self, question: str, default: bool) -> bool:
        hint = "Y/n" if default else "y/N"
        while True:
            answer = self.input(f"{question} [{hint}]: ").strip().lower()
            if not answer:
                return default
            if answer in ("y", "yes", "j", "ja"):
                return True
            if answer in ("n", "no", "nein"):
                return False
            self.out("Please answer y or n.")

    # --- questions -------------------------------------------------------------

    def ask_printer(self, current: str | None) -> str:
        while True:
            host = self.ask("Printer IP address or host name", current)
            if not host:
                self.out("The printer is required.")
                continue
            self.out(f"Checking {host} ...")
            ok, text = self.probe(host)
            self.out(("OK: " if ok else "Problem: ") + text)
            if ok:
                return host
            if self.yes_no("Use this address anyway?", False):
                return host

    def ask_name(self, current: str) -> str:
        self.out("The panel name is what you pick on the printer under Scan to PC.")
        while True:
            name = self.ask("Panel name", current)
            try:
                protocol.check_name(name)
                return name
            except ValueError as exc:
                self.out(f"Invalid name: {exc}")

    def ask_password(self) -> str:
        self.out(f"The web password needs at least {MIN_PASSWORD_LENGTH} characters. "
                 "It is stored in a separate file, not in config.toml.")
        while True:
            first = self.getpass("Web password: ")
            problem = password_problem(first)
            if problem:
                self.out(f"Error: {problem}")
                continue
            if self.getpass("Repeat the password: ") != first:
                self.out("The two entries differ, try again.")
                continue
            return first

    def ask_web(self, cfg: Config) -> None:
        if not self.yes_no("Enable the web page (status, log, target editor)?",
                           bool(cfg.web_enabled)):
            cfg.web_enabled = False
            return
        cfg.web_enabled = True
        while True:
            port = self.ask("Web port", str(cfg.web_port or DEFAULT_PORT))
            if port.isdigit() and 1 <= int(port) <= 65535:
                cfg.web_port = int(port)
                break
            self.out("Enter a port number from 1 to 65535.")
        self.out("Bind address: 127.0.0.1 means only this PC can open the page. "
                 "0.0.0.0 makes it reachable from your whole network.")
        cfg.web_bind = self.ask("Bind address", cfg.web_bind or DEFAULT_BIND)
        existing = Path(cfg.web_password_file) if cfg.web_password_file else None
        if existing is not None and existing.is_file() \
                and self.yes_no("Keep the existing web password?", True):
            return
        password_file = self.path.with_name(PASSWORD_FILE_NAME)
        write_password_file(password_file, self.ask_password())
        cfg.web_password_file = str(password_file)
        if platform_support.is_windows():
            self.out(f"The password file is in your user profile ({password_file}), "
                     "which other standard users cannot read.")

    # --- the flow --------------------------------------------------------------

    def run(self) -> bool:
        """Ask, write the config file and return True if the user wants to
        start now. Raises ConfigError (existing file invalid) and OSError."""
        cfg = Config()
        existing = self.path.is_file()
        if existing:
            cfg = load_config(self.path)  # a broken file is reported, never overwritten
            self.out(f"Found the config file {self.path}")
            self.out(f"  printer: {cfg.printer or 'not set'}")
            self.out(f"  output:  {cfg.output or platform_support.default_output()}")
            for spec in cfg.targets:
                self.out(f"  target:  {spec.name}")
            self.out(f"  web:     {'on' if cfg.web_enabled else 'off'}")
            if not self.yes_no("Change these settings?", False):
                return self.yes_no("Start now?", True)
            self.out("Comments in the file are not kept when it is saved again.")
        else:
            self.out(f"The config file will be {self.path}")

        cfg.printer = self.ask_printer(cfg.printer)
        if cfg.targets:
            self.out("Your panel names and folders (the [[target]] entries) stay as they are. "
                     "Edit the config file to change them.")
        else:
            name = self.ask_name(self.default_name)
            output = self.ask("Folder for scans",
                              str(cfg.output or platform_support.default_output()))
            cfg.output = Path(output)
            cfg.targets = [TargetSpec(name)]
        self.ask_web(cfg)
        log_path = platform_support.default_log_path()
        want_autostart = (platform_support.is_windows() and self.autostart_fn is not None
                          and self.yes_no("Start automatically when you log in to Windows?",
                                          True))
        write_config(self.path, dump_config(cfg))  # before autostart, which reads it
        autostart_done = False
        if want_autostart:
            code = self.autostart_fn(["--config", str(self.path), "--log-file", str(log_path)])
            autostart_done = code == 0
            if not autostart_done:
                self.out("Autostart could not be installed, see the message above.")
        self.summary(cfg, autostart_done, log_path)
        return self.yes_no("Start now?", True)

    def summary(self, cfg: Config, autostart: bool, log_path: Path) -> None:
        out = self.out
        out("")
        out("Setup done.")
        out(f"  Config file: {self.path}")
        out(f"  Printer:     {cfg.printer}")
        for spec in cfg.targets:
            folder = Path(cfg.output or platform_support.default_output())
            folder = folder / spec.output if spec.output else folder / spec.name
            out(f"  Scans of '{spec.name}' go to: {folder}")
        if cfg.web_enabled:
            host = "127.0.0.1" if cfg.web_bind in (None, "0.0.0.0") else cfg.web_bind
            out(f"  Web page:    http://{host}:{cfg.web_port or DEFAULT_PORT}")
        else:
            out("  Web page:    off")
        if autostart:
            out(f"  Autostart:   on, log file {log_path}")
        out("To change something later, edit the config file or run "
            "'pushscan2folder setup' again.")
