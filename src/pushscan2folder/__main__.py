"""Command line entry point: python -m pushscan2folder"""
from __future__ import annotations

import argparse
import getpass
import logging
import logging.handlers
import os
import signal
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path

from . import (__version__, autostart, background, desktop, discovery, panel, protocol,
               terminal, uninstall, web, wizard)
from .client import ChmpClient
from .config import Config, ConfigError, load_config
from .escl import EsclClient, ScanSettings
from .native import NativeScanner
from .platform_support import (default_config_path, default_log_path, default_output,
                               default_state_dir, is_windows)
from .service import (DEFAULT_FILENAME, MULTIPAGE_MODES, PushScanService, Target, Trim,
                      check_filename, check_targets,
                      parse_targets, parse_trim)
from .status import LogBuffer


def env(name: str, default=None):
    """PUSHSCAN_<name>; an unset or empty variable counts as not set."""
    return os.environ.get(f"PUSHSCAN_{name}") or default


def env_bool(name: str, fallback: bool | None) -> bool:
    value = env(name)
    if value is None:
        return bool(fallback)
    return value.lower() in ("1", "true", "yes")


def env_switch(name: str) -> bool:
    """Opt-out switch that is on by default: unset or empty = on. Only clear
    words are accepted, so a typo can never turn a protection off by accident.
    Raises ValueError."""
    value = env(name)
    if value is None:
        return True
    word = value.strip().lower()
    if word in ("1", "true", "yes", "on"):
        return True
    if word in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"invalid PUSHSCAN_{name} {value!r}: use 1 or 0")


def multipage_env(fallback: str | None = None) -> str:
    value = env("MULTIPAGE", fallback or "document").strip().lower()
    aliases = {"1": "document", "true": "document", "yes": "document",
               "0": "off", "false": "off", "no": "off"}
    return aliases.get(value, value)


def find_config(argv=None) -> Config:
    """Load the config file: --config, else PUSHSCAN_CONFIG, else the default
    location if it exists, else an empty Config. A missing explicit file is an
    error, except with the web page enabled (its first save creates the file).
    Raises ConfigError."""
    pre = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre.add_argument("--config", default=None)
    pre.add_argument("--web", action="store_true")
    known = pre.parse_known_args(argv)[0]
    explicit = known.config or env("CONFIG")
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            if known.web or env_bool("WEB", False):
                return Config()  # the web page creates the file on the first save
            raise ConfigError(f"config file not found: {path}")
        return load_config(path)
    path = default_config_path()
    return load_config(path) if path.is_file() else Config()


COMMANDS = ("run", "probe", "scan", "setup", "start", "stop", "status", "uninstall", "health")
# Global options (before the subcommand): name -> takes a value.
GLOBAL_OPTIONS = {"--config": True, "--printer": True, "--name": True, "--log-file": True,
                  "--verbose": False, "-v": False, "--install-autostart": False,
                  "--remove-autostart": False, "--no-pause": False, "--background": False}


def _global_option(token: str) -> bool | None:
    """None if token is no global option, else whether it takes a separate value
    (False for "--x=value" and for flags). Unambiguous abbreviations count."""
    if token in GLOBAL_OPTIONS:
        return GLOBAL_OPTIONS[token]
    name = token.split("=", 1)[0]
    if name.startswith("--") and len(name) > 2:
        matches = [o for o in GLOBAL_OPTIONS if o.startswith(name)]
        if len(matches) == 1:
            return GLOBAL_OPTIONS[matches[0]] and "=" not in token
    return None


def command_index(argv: list[str]) -> int | None:
    """Index of the subcommand in argv (global options in front), or None."""
    i = 0
    while i < len(argv):
        takes_value = _global_option(argv[i])
        if takes_value is None:
            return i if argv[i] in COMMANDS else None
        i += 2 if takes_value else 1
    return None


def command_of(argv: list[str]) -> str | None:
    """The subcommand in argv (global options in front), or None."""
    index = command_index(argv)
    return None if index is None else argv[index]


def with_default_command(argv: list[str]) -> list[str]:
    """Without a subcommand the command is `run`: "--printer X --web" becomes
    "--printer X run --web". Global options stay in front, everything else
    goes behind `run`. argv with a subcommand (or --help/--version) is unchanged."""
    front: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in ("-h", "--help", "--version", "--"):
            return list(argv)
        if not rest and token in COMMANDS:
            return list(argv)  # explicit subcommand
        takes_value = _global_option(token)
        if takes_value is None:
            rest.append(token)
        else:
            front.append(token)
            if takes_value and i + 1 < len(argv):
                i += 1
                front.append(argv[i])
        i += 1
    return front + ["run"] + rest


def _trim_arg(text: str) -> Trim:
    try:
        return parse_trim(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _trim_default(cfg: Config) -> Trim:
    """PUSHSCAN_TRIM (replaces the file values as a whole) or the config file.
    An invalid env value is reported by argparse when it is applied as a default."""
    value = env("TRIM")
    return cfg.trim() if value is None else value


def build_parser(cfg: Config | None = None) -> argparse.ArgumentParser:
    """Precedence of each default: environment variable > config file > built-in.
    (Command line options override all of these via argparse.)"""
    cfg = cfg or Config()
    p = argparse.ArgumentParser(prog="pushscan2folder",
                                description="Scan-to-PC target for Canon IJ printers (Linux, Windows, macOS)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--config", default=env("CONFIG"), metavar="PATH",
                   help="TOML configuration file (default if present: Windows "
                        "%%APPDATA%%\\pushscan2folder\\config.toml, otherwise "
                        "$XDG_CONFIG_HOME/pushscan2folder/config.toml)")
    p.add_argument("--printer", default=env("PRINTER", cfg.printer), help="printer IP or host name")
    p.add_argument("--name", default=env("NAME"),
                   help="name shown on the printer panel (max 31 chars)")
    p.add_argument("-v", "--verbose", action="store_true", default=env_bool("VERBOSE", cfg.verbose))
    p.add_argument("--log-file", default=env("LOG_FILE"), metavar="PATH",
                   help="also write the log to this file (rotating, 1 MB x 3 files)")
    p.add_argument("--no-pause", action="store_true", default=env_bool("NO_PAUSE", False),
                   help="Windows: never wait for Enter before the console window closes")
    p.add_argument("--background", action="store_true", help=argparse.SUPPRESS)  # set by `start`
    p.add_argument("--install-autostart", action="store_true",
                   help="Windows only: start at logon with the other options given "
                        "(e.g. --config PATH --log-file PATH), then exit")
    p.add_argument("--remove-autostart", action="store_true",
                   help="Windows only: remove the logon entry, then exit")
    sub = p.add_subparsers(dest="cmd", required=True,
                           metavar="{run,start,stop,status,probe,scan,setup,uninstall,health}",
                           description="without a subcommand, run is used")
    output_default = env("OUTPUT") or cfg.output or default_output()

    def add_run_options(opts: argparse.ArgumentParser) -> None:
        opts.add_argument("--output", default=output_default, type=Path,
                         help="base folder for scans (default: ./scans; on Windows and "
                              "macOS Documents/Scans in your home folder)")
        opts.add_argument("--interval", type=float, default=float(env("INTERVAL", cfg.interval or 4)))
        opts.add_argument("--format", choices=["pdf", "jpeg"], default=env("FORMAT", cfg.format or "pdf"))
        opts.add_argument("--color", choices=["color", "gray"], default=env("COLOR", cfg.color or "color"))
        opts.add_argument("--resolution", type=int, default=int(env("RESOLUTION", cfg.resolution or 300)))
        opts.add_argument("--source", choices=["auto", "platen", "adf"],
                         default=env("SOURCE", cfg.source or "auto"))
        opts.add_argument("--trim", type=_trim_arg, default=_trim_default(cfg), metavar="SIDES",
                         help="cut off a border by scanning a smaller area (platen only), "
                              "e.g. right=3,bottom=2 (keys left/top/right/bottom, mm, 0 to 50); "
                              "replaces the four trim_* values of the config file")
        opts.add_argument("--targets", default=env("TARGETS"),
                         help='several panel entries, e.g. "scan1,paperless=consume@300dpi,archiv@600dpi"; '
                              "each scans into its own folder below --output, optional preset after @. "
                              "Replaces the targets of the config file")
        opts.add_argument("--ignore-panel", action="store_true",
                         default=env_bool("IGNORE_PANEL", cfg.ignore_panel),
                         help="ignore the settings chosen on the printer panel and always "
                              "use --format/--color/--resolution/--source")
        opts.add_argument("--multipage", choices=sorted(MULTIPAGE_MODES),
                         default=multipage_env(cfg.multipage),
                         help="document types for which platen scans offer further pages "
                              "on the panel (default: document)")
        opts.add_argument("--heartbeat-file", default=env("HEARTBEAT_FILE"), metavar="PATH",
                          help="touch this file after every successful contact with the "
                               "printer, for `pushscan2folder health` (the Docker image sets it)")
        opts.add_argument("--filename", default=env("FILENAME", cfg.filename or DEFAULT_FILENAME),
                          metavar="TEMPLATE",
                          help="file name of a scan without extension, with the fields "
                               "{name}, {date}, {time} and {now:STRFTIME} (default: "
                               "scan_{now:%%Y%%m%%d_%%H%%M%%S}); a target can set its own")
        opts.add_argument("--open-after-scan", choices=list(desktop.OPEN_MODES),
                          default=env("OPEN_AFTER_SCAN", cfg.open_after_scan or "off"),
                          help="desktop PC only: open the folder (Windows: with the new file "
                               "selected) or the file after each scan (default: off)")

        opts.add_argument("--web", action="store_true", default=env_bool("WEB", cfg.web_enabled),
                         help="serve the optional web page (status, log, target editor); "
                              "the password comes from PUSHSCAN_WEB_PASSWORD, "
                              "PUSHSCAN_WEB_PASSWORD_FILE or [web] password_file")
        opts.add_argument("--web-port", type=int, default=int(env("WEB_PORT", cfg.web_port or 8080)),
                         help="port of the web page (default: 8080)")
        opts.add_argument("--web-bind", default=env("WEB_BIND", cfg.web_bind or "0.0.0.0"),
                         help="address of the web page (default: 0.0.0.0)")

    run = sub.add_parser("run", help="register and wait for scan requests")
    add_run_options(run)
    start = sub.add_parser("start", help="run in the background (no window), then return")
    add_run_options(start)
    sub.add_parser("stop", help="stop the background instance (it releases its panel names)")
    sub.add_parser("status", help="show whether the background instance runs, and its log")
    uninstall_p = sub.add_parser("uninstall", help="stop, remove autostart and optionally "
                                                   "the settings and log folders")
    uninstall_p.add_argument("--yes", action="store_true",
                             help="do not ask; keeps the settings unless --purge is given")
    uninstall_p.add_argument("--purge", action="store_true",
                             help="with --yes: also delete the settings and log folders")
    sub.add_parser("setup", help="ask a few questions and write the config file")
    health = sub.add_parser("health", help="exit 0 if a running instance reached the printer "
                                           "recently (Docker healthcheck)")
    health.add_argument("--heartbeat-file", default=env("HEARTBEAT_FILE"), metavar="PATH",
                        help="the file given to run (default: PUSHSCAN_HEARTBEAT_FILE)")
    health.add_argument("--max-age", type=float, default=HEALTH_MAX_AGE, metavar="SECONDS",
                        help=f"older than this is unhealthy (default: {HEALTH_MAX_AGE:g})")

    probe = sub.add_parser("probe", help="register, poll once and release (debug)")
    probe.add_argument("--keep", action="store_true", help="do not release the session")

    scan = sub.add_parser("scan", help="scan once via eSCL without the panel")
    scan.add_argument("--output", default=output_default, type=Path)
    scan.add_argument("--format", choices=["pdf", "jpeg"], default="pdf")
    scan.add_argument("--source", choices=["auto", "platen", "adf"], default="auto")
    return p


NO_CONFIG_COMMANDS = ("setup", "stop", "status", "uninstall", "health")


def parse_args(argv=None) -> tuple[argparse.Namespace, Config]:
    """Load the config file, then parse the command line on top of it."""
    argv = with_default_command(list(sys.argv[1:] if argv is None else argv))
    # setup reads its own config; stop, status and uninstall must work with a broken one
    cfg = Config() if command_of(argv) in NO_CONFIG_COMMANDS else find_config(argv)
    return build_parser(cfg).parse_args(argv), cfg


def fallback_settings(args: argparse.Namespace, cfg: Config) -> ScanSettings:
    kwargs = dict(fmt=args.format)
    if args.cmd == "run":
        kwargs.update(color=args.color, resolution=args.resolution)
    if cfg.size:
        kwargs["width"], kwargs["height"] = panel.REGIONS[cfg.size]
    return ScanSettings(source="platen" if args.source == "auto" else args.source, **kwargs)


def resolve_targets(args: argparse.Namespace, cfg: Config, name: str) -> list[Target]:
    """--targets/PUSHSCAN_TARGETS replace the config targets; without either,
    a single target called `name`. Raises ValueError."""
    spec = getattr(args, "targets", None)
    if spec:
        return parse_targets(spec, args.output)
    if cfg.targets:
        return cfg.build_targets(args.output, getattr(args, "multipage", "off"))
    return [Target(name, args.output)]


# Settings the web form shows: config key -> (environment variable, option).
# A key set by either of them wins over the config file.
OVERRIDABLE = {
    "printer": ("PRINTER", "--printer"), "output": ("OUTPUT", "--output"),
    "interval": ("INTERVAL", "--interval"),
    "ignore_panel": ("IGNORE_PANEL", "--ignore-panel"),
    "multipage": ("MULTIPAGE", "--multipage"),
    "resolution": ("RESOLUTION", "--resolution"), "color": ("COLOR", "--color"),
    "format": ("FORMAT", "--format"), "source": ("SOURCE", "--source"),
    "open_after_scan": ("OPEN_AFTER_SCAN", "--open-after-scan"),
    "filename": ("FILENAME", "--filename"),
    "trim_left": ("TRIM", "--trim"), "trim_top": ("TRIM", "--trim"),
    "trim_right": ("TRIM", "--trim"), "trim_bottom": ("TRIM", "--trim"),
}


def _option_given(argv: list[str], option: str) -> bool:
    """True if `option` (or an unambiguous abbreviation, which argparse
    accepts) is on the command line, as "--x v" or "--x=v"."""
    for token in argv:
        if token == "--":
            break
        name = token.split("=", 1)[0]
        if name.startswith("--") and len(name) > 2 and option.startswith(name):
            return True
    return False


def web_overrides(args: argparse.Namespace, cfg: Config,
                  argv: list[str] | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """For the web settings page: (overrides, effective). overrides maps a
    config key to what overrides the file value ("environment variable X" or
    "command line option --x"); effective maps keys to the value in use."""
    argv = list(sys.argv[1:] if argv is None else argv)
    overrides = {}
    for key, (var, option) in OVERRIDABLE.items():
        if _option_given(argv, option):
            overrides[key] = f"command line option {option}"
        elif env(var) is not None:
            overrides[key] = f"environment variable PUSHSCAN_{var}"
    trim = getattr(args, "trim", None) or Trim()
    effective = {
        "printer": args.printer, "output": str(args.output), "interval": f"{args.interval:g}",
        "ignore_panel": "yes" if args.ignore_panel else "no", "multipage": args.multipage,
        "resolution": str(args.resolution), "color": args.color, "format": args.format,
        "source": args.source, "size": cfg.size or "a4",
        "open_after_scan": args.open_after_scan, "filename": args.filename,
        "trim_left": f"{trim.left:g}", "trim_top": f"{trim.top:g}",
        "trim_right": f"{trim.right:g}", "trim_bottom": f"{trim.bottom:g}",
    }
    return overrides, effective


def check_run_options(args: argparse.Namespace) -> None:
    """Check the option values the parser does not check itself. Normalizes
    open_after_scan. Raises ValueError with the message for the user."""
    if getattr(args, "multipage", "off") not in MULTIPAGE_MODES:
        raise ValueError(f"invalid PUSHSCAN_MULTIPAGE {args.multipage!r}")
    open_mode = str(getattr(args, "open_after_scan", "off")).strip().lower()
    if open_mode not in desktop.OPEN_MODES:
        raise ValueError(f"invalid PUSHSCAN_OPEN_AFTER_SCAN {args.open_after_scan!r}: use "
                         f"{', '.join(desktop.OPEN_MODES)}")
    args.open_after_scan = open_mode
    try:
        check_filename(getattr(args, "filename", DEFAULT_FILENAME))
    except ValueError as exc:
        raise ValueError(f"--filename/PUSHSCAN_FILENAME: {exc}") from None


def service_options(args: argparse.Namespace, cfg: Config) -> dict:
    """The PushScanService options from the parsed command line and config
    (at startup and when the config file changes)."""
    return dict(settings=fallback_settings(args, cfg),
                interval=getattr(args, "interval", 4.0),
                auto_source=(args.source == "auto"),
                use_panel=not getattr(args, "ignore_panel", True),
                multipage=MULTIPAGE_MODES.get(getattr(args, "multipage", "off"), frozenset()),
                trim=getattr(args, "trim", None) or Trim(),
                open_after_scan=getattr(args, "open_after_scan", "off"),
                filename=getattr(args, "filename", DEFAULT_FILENAME))


# Options that a changed config file cannot change in a running service.
NOT_RELOADED = (("web", "web page on or off"), ("web_bind", "web bind address"),
                ("web_port", "web port"), ("log_file", "log file"),
                ("verbose", "debug log"), ("heartbeat_file", "heartbeat file"))


def printer_clients(printer: str):
    return ChmpClient(printer), EsclClient(printer), NativeScanner(printer)


class ConfigWatcher:
    """Apply a changed config file to the running service, without a restart.

    check() runs in the poll loop before each cycle (never during a scan). It
    compares the modification time and size of the file. A changed file is
    read like at startup (command line and environment still win). If it is
    not valid, the running settings stay and the error is logged once. Scan
    options, targets and the printer change right away; the web page options,
    the log file and the heartbeat file need a restart."""

    def __init__(self, path: Path, argv: list[str], args: argparse.Namespace, cfg: Config,
                 service: PushScanService, ctx=None, clients=printer_clients):
        self.path = Path(path)
        self.argv = list(argv)
        self.started = args           # what the restart-only options are compared with
        self.started_cfg = cfg
        self.args = args
        self.service = service
        self.ctx = ctx
        self.clients = clients
        self.last = self._stamp()

    def _stamp(self):
        try:
            st = self.path.stat()
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    def check(self) -> bool:
        """True if a changed file was applied."""
        stamp = self._stamp()
        if stamp is None or stamp == self.last:   # a deleted file changes nothing
            return False
        self.last = stamp
        try:
            args, cfg = parse_args(self.argv)
            check_run_options(args)
            if not args.printer:
                raise ValueError("no printer is set")
            name = args.name or default_name()
            protocol.check_name(name)
            targets = resolve_targets(args, cfg, name)
        except (ConfigError, ValueError) as exc:
            logging.error("%s changed but cannot be used, the running settings stay: %s",
                          self.path, exc)
            return False
        except SystemExit:   # argparse rejected a value (it printed why)
            logging.error("%s changed but cannot be used, the running settings stay",
                          self.path)
            return False
        for warning in check_targets(targets):
            logging.warning(warning)
        service = self.service
        service.update_options(**service_options(args, cfg))
        if args.printer != self.args.printer:
            logging.info("printer changed to %s", args.printer)
            service.change_printer(*self.clients(args.printer))
        service.request_targets(targets)
        if self.ctx is not None:
            ctx = self.ctx
            ctx.printer, ctx.output, ctx.multipage_mode = args.printer, args.output, args.multipage
            ctx.targets_from_env = bool(args.targets)
            ctx.overrides, ctx.effective = web_overrides(args, cfg, self.argv)
            ctx.printer_pending = None
        self.args = args
        logging.info("%s changed, the new settings are in use", self.path)
        restart = [label for key, label in NOT_RELOADED
                   if getattr(args, key, None) != getattr(self.started, key, None)]
        if cfg.web_password_file != self.started_cfg.web_password_file:
            restart.append("web password file")
        if restart:
            logging.warning("restart pushscan2folder to apply: %s", ", ".join(restart))
        return True


EXAMPLE_PASSWORD = wizard.EXAMPLE_PASSWORD


def read_web_password(check: bool = True, config_file: str | None = None) -> str:
    """Password from PUSHSCAN_WEB_PASSWORD, else the file PUSHSCAN_WEB_PASSWORD_FILE
    (e.g. a Docker secret), else the file named by [web] password_file of the
    config (config_file). Never the password itself from the config file or
    the command line.
    check=False (PUSHSCAN_WEB_PASSWORD_CHECK=0) skips the length and example
    password rules; an empty password is always an error. Raises ValueError."""
    password = env("WEB_PASSWORD")
    path = env("WEB_PASSWORD_FILE") or config_file
    if password is None and path:
        try:
            password = Path(path).read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"cannot read the web password file {path}: "
                             f"{getattr(exc, 'strerror', None) or exc}") from exc
    if not password:
        raise ValueError("the web page needs a password: set PUSHSCAN_WEB_PASSWORD, "
                         "PUSHSCAN_WEB_PASSWORD_FILE or password_file in [web] of the "
                         "config file (run 'pushscan2folder setup')")
    if not check:
        return password
    problem = wizard.password_problem(password)
    if problem:
        raise ValueError(problem)
    return password


def web_password_setup(config_file: str | None = None) -> str | None:
    """Password for the web page, or None for PUSHSCAN_WEB_AUTH=0 (no login).
    Logs a warning for each of the two opt-outs. Raises ValueError."""
    if not env_switch("WEB_AUTH"):
        if env("WEB_PASSWORD") or env("WEB_PASSWORD_FILE"):
            logging.warning("PUSHSCAN_WEB_AUTH=0: the web password is ignored")
        return None
    check = env_switch("WEB_PASSWORD_CHECK")
    password = read_web_password(check, config_file)
    if not check:
        logging.warning("PUSHSCAN_WEB_PASSWORD_CHECK=0: the web password rules are "
                        "off, a short or example password is accepted")
    return password


def default_name() -> str:
    """USER  HOST like the Windows tool. In a container the uid often has no
    passwd entry (e.g. user: "1030:100" on a NAS), so fall back to "scan"."""
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = "scan"
    return protocol.panel_safe(protocol.default_name(user, socket.gethostname()))


def setup_console() -> None:
    """Never fail on a character the console cannot show (a Windows console
    often uses a legacy code page): print a replacement character instead."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass  # no console (windowed exe) or not a text stream


def setup_logging(verbose: bool, log_file: str | None = None) -> None:
    """Log to the console and, with log_file, to a rotating file.
    Raises OSError if the file cannot be opened."""
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format=fmt)
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter(fmt))
        logging.getLogger().addHandler(handler)


def install_signal_handlers(service: PushScanService) -> None:
    """Ctrl+C and SIGTERM stop the service cleanly (the targets are released).
    Windows has no real SIGTERM, but Ctrl+Break (SIGBREAK) and closing the
    console are the equivalent there."""
    names = ["SIGINT", "SIGTERM"] + (["SIGBREAK"] if is_windows() else [])
    for name in names:
        number = getattr(signal, name, None)
        if number is not None:
            signal.signal(number, lambda *_: service.stop())


def autostart_main(argv: list[str]) -> int:
    """--install-autostart / --remove-autostart. The other options on the
    command line are what the logon entry will run."""
    install, remove = "--install-autostart" in argv, "--remove-autostart" in argv
    if install and remove:
        print("error: use either --install-autostart or --remove-autostart", file=sys.stderr)
        return 2
    if not is_windows():
        print("error: autostart is only implemented for Windows. On Linux use a "
              "systemd user service or Docker, see the README.", file=sys.stderr)
        return 2
    rest = [a for a in argv if a not in ("--install-autostart", "--remove-autostart")]
    if install:
        try:
            parse_args(rest)  # adds `run` in the right place when no subcommand is given
            command = autostart.install_command(rest)
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    else:
        command = autostart.remove_command()
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        print(f"error: reg.exe failed: {(done.stderr or done.stdout).strip()}", file=sys.stderr)
        return 1
    if install:
        print("Autostart installed: pushscan2folder starts minimised when you log in.")
        if not any(a == "--log-file" or a.startswith("--log-file=") for a in rest):
            print("Tip: add --log-file PATH to keep a log of the autostart runs.")
    else:
        print("Autostart removed.")
    return 0


def should_pause(platform: str, process_count: int | None, stdin_isatty: bool,
                 no_pause: bool = False) -> bool:
    """True if the console window may close before the user can read the output:
    Windows, a console that belongs to this program alone (opened by a double
    click), an interactive stdin to wait on, and no opt-out. The exe is built
    as a folder (one process, no separate bootloader process)."""
    if no_pause or platform != "win32" or not stdin_isatty or process_count is None:
        return False
    return process_count <= 1


def console_process_count() -> int | None:
    """Number of processes attached to this console (Windows), None if unknown."""
    if not is_windows():
        return None
    try:
        import ctypes
        buffer = (ctypes.c_uint * 4)()
        count = ctypes.windll.kernel32.GetConsoleProcessList(buffer, len(buffer))
        return int(count) or None
    except Exception:
        return None


def pause_before_exit(raw: list[str]) -> None:
    """Keep a console window opened just for this program readable."""
    try:
        no_pause = autostart.NO_PAUSE in raw or env_bool("NO_PAUSE", False)
        if not is_windows() or no_pause:
            return
        if not should_pause(sys.platform, console_process_count(), sys.stdin.isatty()):
            return
        print("\nPress Enter to close this window.", flush=True)
        input()
    except (Exception, KeyboardInterrupt):
        pass


def summary_lines(args: argparse.Namespace, targets: list[Target], config_path: Path | None,
                  web_url: str | None, foreground_hint: bool = False) -> list[str]:
    """What the program does, shown at the start of `run`."""
    lines = [f"pushscan2folder {__version__}", f"printer: {args.printer}",
             f"config file: {config_path if config_path else 'none'}"]
    lines += [f"panel name {t.name!r} -> {t.outdir}" for t in targets]
    lines.append(f"web page: {web_url}" if web_url else "web page off")
    if args.log_file:
        lines.append(f"log file: {args.log_file}")
    if foreground_hint:
        lines.append("Closing this window stops the program. Use `pushscan2folder start` "
                     "to run in the background.")
    lines.append("Press Ctrl+C to stop.")
    return lines


def install_autostart(args: list[str]) -> int:
    """Install the logon entry that runs the given options (used by setup)."""
    return autostart_main(["--install-autostart"] + args)


def setup_main(args: argparse.Namespace | None) -> int:
    """`setup`: ask, write the config file, then optionally start."""
    path = Path(args.config) if args and args.config else default_config_path()
    session = wizard.Setup(path, autostart_fn=install_autostart, default_name=default_name(),
                           start_fn=lambda a: start_main(a, hints=False),
                           discover_fn=discovery.discover)
    try:
        start = session.run()
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        return 1
    except (ConfigError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not start:
        if not session.background_started:
            print("Run pushscan2folder again to start.")
        return 0
    rest = ["--config", str(path)]
    if args is not None:
        rest += (["--verbose"] if args.verbose else []) + \
                (["--log-file", args.log_file] if args.log_file else []) + \
                ([autostart.NO_PAUSE] if args.no_pause else [])
    return _main(rest)


def replace_command(argv: list[str], new: str) -> list[str]:
    """argv with its subcommand replaced by `new` (appended if there is none)."""
    index = command_index(argv)
    if index is None:
        return list(argv) + [new]
    return argv[:index] + [new] + argv[index + 1:]


def background_argv(argv: list[str], args: argparse.Namespace) -> list[str]:
    """Command line of the background process: the given options with absolute
    paths, `run` instead of `start`, plus --no-pause, --background and a log
    file (the default one unless --log-file/PUSHSCAN_LOG_FILE is set)."""
    front = ["--no-pause", "--background"]
    if not args.log_file:
        front += ["--log-file", str(default_log_path())]
    return front + autostart.absolute_args(replace_command(argv, "run"))


def start_main(raw: list[str], hints: bool = True, popen=subprocess.Popen,
               instance: background.Instance | None = None) -> int:
    """`start`: launch the background instance with the given options, return."""
    try:
        args, _ = parse_args(replace_command(raw, "run"))
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not args.printer:
        print("error: --printer or PUSHSCAN_PRINTER is required (run 'pushscan2folder setup')",
              file=sys.stderr)
        return 2
    inst = instance or background.Instance()
    log_path = args.log_file or str(default_log_path())
    ok, message = background.start_instance(background_argv(raw, args), inst, popen=popen)
    if not ok:
        print(f"error: {message}", file=sys.stderr)
        if not message.startswith(background.ALREADY_RUNNING):
            for line in background.log_tail(log_path, 5):
                print(f"  {line}", file=sys.stderr)
        return 1
    print(f"pushscan2folder {message} in the background.")
    if hints:
        print(f"It keeps running after you close this window. Log file: {terminal.link(log_path)}")
        print("Stop it with: pushscan2folder stop")
    return 0


def stop_main(instance: background.Instance | None = None, **kwargs) -> int:
    inst = instance or background.Instance()
    kwargs.setdefault("on_wait_for_scan", lambda: print(
        "A scan is running; it is finished and saved first ...", flush=True))
    result = background.stop_instance(inst, **kwargs)
    if result == background.NOT_RUNNING:
        print("pushscan2folder is not running in the background.")
        return 0
    if result == background.FAILED:
        print("error: the background instance did not stop", file=sys.stderr)
        return 1
    print("Stopped." if result == background.STOPPED
          else "Did not stop in time and was terminated.")
    return 0


def status_main(instance: background.Instance | None = None) -> int:
    inst = instance or background.Instance()
    info = background.Info()
    running = inst.is_running()
    if running:
        info = inst.read_info()
        print("running in the background" + (f", PID {info.pid}" if info.pid else ""))
    else:
        print("not running in the background")
    log = info.log or str(default_log_path())
    print(f"log file: {log}")
    tail = background.log_tail(log)
    if tail:
        print("last log lines:")
        for line in tail:
            print(f"  {line}")
    return 0 if running else 1


def remove_autostart_message() -> str:
    """Remove the Windows logon entry; a message for the user."""
    done = subprocess.run(autostart.remove_command(), capture_output=True, text=True,
                          check=False)
    if done.returncode == 0:
        return "Autostart entry removed."
    return "No autostart entry removed (there was none, or reg.exe failed)."


def uninstall_main(args: argparse.Namespace, argv: list[str],
                   instance: background.Instance | None = None, **kwargs) -> int:
    """Folders of scans (output and target folders) stay protected."""
    protected: list[Path] = []
    try:
        cfg = find_config(argv)
        base = Path(env("OUTPUT") or cfg.output or default_output())
        protected = [base] + [t.outdir for t in cfg.build_targets(base, "off")]
    except ConfigError:
        protected = [Path(env("OUTPUT") or default_output())]
    config_dir = default_config_path().parent
    windows = is_windows()
    exe = Path(sys.executable) if getattr(sys, "frozen", False) else None
    return uninstall.uninstall(
        instance or background.Instance(), config_dir, default_state_dir(), protected,
        yes=args.yes, purge=args.purge, exe=exe,
        remove_autostart=remove_autostart_message if windows else None, **kwargs)


HEALTH_MAX_AGE = 120.0  # seconds; the printer drops a name after about 60 s


def health_main(args: argparse.Namespace, now: float | None = None) -> int:
    """`health`: 0 if the heartbeat file is fresh, 1 otherwise (with a reason)."""
    if not args.heartbeat_file:
        print("unhealthy: no heartbeat file (set PUSHSCAN_HEARTBEAT_FILE or --heartbeat-file)")
        return 1
    try:
        age = (time.time() if now is None else now) - os.path.getmtime(args.heartbeat_file)
    except OSError:
        print("unhealthy: no contact with the printer yet")
        return 1
    if age > args.max_age:
        print(f"unhealthy: last contact with the printer {age:.0f} s ago")
        return 1
    print(f"healthy: last contact with the printer {max(age, 0):.0f} s ago")
    return 0


def manual_start(raw: list[str]) -> bool:
    """Started without any argument by hand, with a console to talk to and
    no settings from the environment."""
    try:
        interactive = sys.stdin.isatty()
    except (AttributeError, ValueError):
        interactive = False
    return not raw and interactive and not env("CONFIG") and not env("PRINTER")


def double_click() -> bool:
    """Windows: the console window belongs to this program alone (opened by
    a double click or a shortcut, not typed in a command prompt)."""
    count = console_process_count()
    return is_windows() and count is not None and count <= 1


def greeting(raw: list[str], instance: background.Instance | None = None) -> int | None:
    """Without arguments: the setup questions if nothing is configured yet;
    on a Windows double click with a config file, the choice to use it,
    change it or start over. None: go on with a normal run."""
    if not manual_start(raw):
        return None
    if not default_config_path().is_file():
        print(f"Welcome to pushscan2folder {__version__}.\n"
              "No configuration found, so a few questions follow (Ctrl+C to cancel).\n")
        return setup_main(None)
    if not double_click():
        return None
    instance = instance or background.Instance()
    if instance.is_running():
        pid = instance.read_info().pid
        print(f"pushscan2folder {__version__} is already running in the background"
              + (f" (PID {pid})." if pid else ".")
              + "\nTo change the settings, stop it first: pushscan2folder stop")
        return 0
    print(f"pushscan2folder {__version__}\n")
    return setup_main(None)


def main(argv=None) -> int:
    """Entry point. In a console window opened just for this program (Windows,
    double click) it waits for Enter before returning, so the text stays readable."""
    raw = list(sys.argv[1:] if argv is None else argv)
    exit_exc = None
    try:
        result = _main(argv)
    except SystemExit as exc:  # argparse errors, --help
        result, exit_exc = exc.code, exc
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        result = 130
    except Exception:
        traceback.print_exc()
        result = 1
    pause_before_exit(raw)
    if exit_exc is not None:
        raise exit_exc
    return result


def _main(argv=None) -> int:
    setup_console()
    raw = list(sys.argv[1:] if argv is None else argv)
    if "--install-autostart" in raw or "--remove-autostart" in raw:
        return autostart_main(raw)
    greeted = greeting(raw)
    if greeted is not None:
        return greeted
    try:
        args, cfg = parse_args(argv)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.cmd == "setup":
        return setup_main(args)
    if args.cmd == "start":
        return start_main(raw)
    if args.cmd == "stop":
        return stop_main()
    if args.cmd == "status":
        return status_main()
    if args.cmd == "uninstall":
        return uninstall_main(args, raw)
    if args.cmd == "health":
        return health_main(args)
    try:
        check_run_options(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        setup_logging(args.verbose, args.log_file)
    except OSError as exc:
        print(f"error: --log-file {args.log_file}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    if not args.printer:
        print("error: --printer or PUSHSCAN_PRINTER is required", file=sys.stderr)
        return 2
    web_enabled = args.cmd == "run" and args.web
    web_password = None
    config_path = Path(args.config) if args.config else default_config_path()
    web_file = cfg.web_password_file
    if web_file and not Path(web_file).is_absolute():
        web_file = str(config_path.parent / web_file)  # relative to the config file
    if web_enabled:
        try:
            web_password = web_password_setup(web_file)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    name = args.name or default_name()
    try:
        protocol.check_name(name)
    except ValueError as exc:
        print(f"error: --name/PUSHSCAN_NAME: {exc}", file=sys.stderr)
        return 2
    chmp = ChmpClient(args.printer)
    escl = EsclClient(args.printer)

    if args.cmd == "probe":
        r = chmp.register(name)
        print(f"register: status=0x{r.status:x} session=0x{r.session:x} raw={r.raw.hex()}")
        p = chmp.poll(r.session)
        print(f"poll:     status=0x{p.status:x} event=0x{p.event:x} raw={p.raw.hex()}")
        if not args.keep:
            x = chmp.release(r.session)
            print(f"release:  status=0x{x.status:x}")
        return 0

    try:
        targets = resolve_targets(args, cfg, name)
        for warning in check_targets(targets):
            logging.warning(warning)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    service = PushScanService(chmp, escl, targets, native=NativeScanner(args.printer),
                              **service_options(args, cfg))
    if args.cmd == "scan":
        for path in service.scan_to(targets[0]):
            print(path)
        return 0

    install_signal_handlers(service)
    used_config = config_path if args.config or config_path.is_file() else None
    if getattr(args, "heartbeat_file", None):
        service.heartbeat = Path(args.heartbeat_file)
    inst = background.Instance()
    if args.background:
        service.stop_check = inst.stop_requested  # `pushscan2folder stop`
        service.busy_hook = inst.set_busy          # `stop` waits for a running scan
    watcher = ConfigWatcher(config_path, raw, args, cfg, service)
    service.before_step = watcher.check            # apply a changed config file
    try:
        interactive = sys.stdin.isatty()
    except (AttributeError, ValueError):
        interactive = False

    def claim() -> bool:
        """Background mode: become the one instance (False: another runs).
        In the foreground: refuse while the background instance runs, as both
        would register the same names."""
        if not args.background:
            if inst.is_running():
                logging.error("pushscan2folder already runs in the background; stop it "
                              "first with: pushscan2folder stop")
                return False
            return True
        try:
            if inst.claim(args.log_file):
                return True
            logging.error("another background instance is already running")
        except OSError as exc:
            logging.error("cannot write the instance files in %s: %s", inst.dir,
                          exc.strerror or exc)
        return False

    def announce(web_url=None):
        for line in summary_lines(args, targets, used_config, web_url,
                                  foreground_hint=interactive and not args.background):
            logging.info("%s", line)

    if not web_enabled:
        if not claim():
            return 2
        try:
            announce()
            service.run()
        finally:
            inst.release()
        return 0

    # Web page: records the log, runs in a daemon thread next to the poll loop.
    log_buffer = LogBuffer()
    logging.getLogger().addHandler(log_buffer)
    overrides, effective = web_overrides(args, cfg, argv)
    ctx = web.WebContext(service, log_buffer, args.printer, args.output,
                         multipage_mode=args.multipage,
                         config_path=config_path,
                         targets_from_env=bool(args.targets),
                         overrides=overrides, effective=effective,
                         discover_fn=discovery.discover)
    watcher.ctx = ctx
    try:
        server, thread = web.start_server(ctx, web_password, args.web_bind, args.web_port,
                                          secure_cookie=env_bool("WEB_SECURE_COOKIE", False))
    except OSError as exc:
        logging.getLogger().removeHandler(log_buffer)
        print(f"error: web page on {args.web_bind}:{args.web_port}: {exc.strerror or exc}",
              file=sys.stderr)
        return 2
    if web_password is None:
        logging.warning("web page without password: anyone who can reach port %d can "
                        "change targets and settings", server.server_address[1])
    local = args.web_bind in ("127.0.0.1", "localhost", "::1")
    announce(f"http://{args.web_bind}:{server.server_address[1]} "
             + ("(this PC only)" if local else "(reachable from the network)")
             + (" (Secure cookie: use it through an HTTPS reverse proxy)"
                if server.secure_cookie else ""))
    try:
        if not claim():
            return 2
        service.run()
    finally:
        inst.release()
        web.stop_server(server, thread)
        logging.getLogger().removeHandler(log_buffer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
