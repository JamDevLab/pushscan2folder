"""Command line entry point: python -m pushscan2folder"""
from __future__ import annotations

import argparse
import getpass
import logging
import os
import signal
import socket
import sys
from pathlib import Path

from . import __version__, panel, protocol, web
from .client import ChmpClient
from .config import Config, ConfigError, load_config
from .escl import EsclClient, ScanSettings
from .native import NativeScanner
from .service import (MULTIPAGE_MODES, PushScanService, Target, Trim, check_targets,
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


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "pushscan2folder" / "config.toml"


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
                                description="Scan-to-PC target for Canon IJ printers on Linux")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--config", default=env("CONFIG"), metavar="PATH",
                   help="TOML configuration file (default: "
                        "$XDG_CONFIG_HOME/pushscan2folder/config.toml if present)")
    p.add_argument("--printer", default=env("PRINTER", cfg.printer), help="printer IP or host name")
    p.add_argument("--name", default=env("NAME"),
                   help="name shown on the printer panel (max 31 chars)")
    p.add_argument("-v", "--verbose", action="store_true", default=env_bool("VERBOSE", cfg.verbose))
    sub = p.add_subparsers(dest="cmd", required=True)
    output_default = env("OUTPUT") or cfg.output or "./scans"

    run = sub.add_parser("run", help="register and wait for scan requests")
    run.add_argument("--output", default=output_default, type=Path)
    run.add_argument("--interval", type=float, default=float(env("INTERVAL", cfg.interval or 4)))
    run.add_argument("--format", choices=["pdf", "jpeg"], default=env("FORMAT", cfg.format or "pdf"))
    run.add_argument("--color", choices=["color", "gray"], default=env("COLOR", cfg.color or "color"))
    run.add_argument("--resolution", type=int, default=int(env("RESOLUTION", cfg.resolution or 300)))
    run.add_argument("--source", choices=["auto", "platen", "adf"],
                     default=env("SOURCE", cfg.source or "auto"))
    run.add_argument("--trim", type=_trim_arg, default=_trim_default(cfg), metavar="SIDES",
                     help="cut off a border by scanning a smaller area (platen only), "
                          "e.g. right=3,bottom=2 (keys left/top/right/bottom, mm, 0 to 50); "
                          "replaces the four trim_* values of the config file")
    run.add_argument("--targets", default=env("TARGETS"),
                     help='several panel entries, e.g. "scan1,paperless=consume@300dpi,archiv@600dpi"; '
                          "each scans into its own folder below --output, optional preset after @. "
                          "Replaces the targets of the config file")
    run.add_argument("--ignore-panel", action="store_true",
                     default=env_bool("IGNORE_PANEL", cfg.ignore_panel),
                     help="ignore the settings chosen on the printer panel and always "
                          "use --format/--color/--resolution/--source")
    run.add_argument("--multipage", choices=sorted(MULTIPAGE_MODES),
                     default=multipage_env(cfg.multipage),
                     help="document types for which platen scans offer further pages "
                          "on the panel (default: document)")

    run.add_argument("--web", action="store_true", default=env_bool("WEB", False),
                     help="serve the optional web page (status, log, target editor); "
                          "the password comes from PUSHSCAN_WEB_PASSWORD or "
                          "PUSHSCAN_WEB_PASSWORD_FILE only")
    run.add_argument("--web-port", type=int, default=int(env("WEB_PORT", 8080)),
                     help="port of the web page (default: 8080)")
    run.add_argument("--web-bind", default=env("WEB_BIND", "0.0.0.0"),
                     help="address of the web page (default: 0.0.0.0)")

    probe = sub.add_parser("probe", help="register, poll once and release (debug)")
    probe.add_argument("--keep", action="store_true", help="do not release the session")

    scan = sub.add_parser("scan", help="scan once via eSCL without the panel")
    scan.add_argument("--output", default=output_default, type=Path)
    scan.add_argument("--format", choices=["pdf", "jpeg"], default="pdf")
    scan.add_argument("--source", choices=["auto", "platen", "adf"], default="auto")
    return p


def parse_args(argv=None) -> tuple[argparse.Namespace, Config]:
    """Load the config file, then parse the command line on top of it."""
    cfg = find_config(argv)
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
        "trim_left": f"{trim.left:g}", "trim_top": f"{trim.top:g}",
        "trim_right": f"{trim.right:g}", "trim_bottom": f"{trim.bottom:g}",
    }
    return overrides, effective


EXAMPLE_PASSWORD = "change-me-please"  # placeholder in docker-compose.yml


def read_web_password(check: bool = True) -> str:
    """Password from PUSHSCAN_WEB_PASSWORD or the file PUSHSCAN_WEB_PASSWORD_FILE
    (e.g. a Docker secret). Never from the config file or the command line.
    check=False (PUSHSCAN_WEB_PASSWORD_CHECK=0) skips the length and example
    password rules; an empty password is always an error. Raises ValueError."""
    password = env("WEB_PASSWORD")
    if password is None and env("WEB_PASSWORD_FILE"):
        path = env("WEB_PASSWORD_FILE")
        try:
            password = Path(path).read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"cannot read PUSHSCAN_WEB_PASSWORD_FILE {path}: "
                             f"{getattr(exc, 'strerror', None) or exc}") from exc
    if not password:
        raise ValueError("the web page needs a password: set PUSHSCAN_WEB_PASSWORD "
                         "or PUSHSCAN_WEB_PASSWORD_FILE")
    if not check:
        return password
    if len(password) < web.MIN_PASSWORD_LENGTH:
        raise ValueError(f"the web password must have at least "
                         f"{web.MIN_PASSWORD_LENGTH} characters")
    if password == EXAMPLE_PASSWORD:
        raise ValueError("replace the example web password from docker-compose.yml "
                         "with your own")
    return password


def web_password_setup() -> str | None:
    """Password for the web page, or None for PUSHSCAN_WEB_AUTH=0 (no login).
    Logs a warning for each of the two opt-outs. Raises ValueError."""
    if not env_switch("WEB_AUTH"):
        if env("WEB_PASSWORD") or env("WEB_PASSWORD_FILE"):
            logging.warning("PUSHSCAN_WEB_AUTH=0: the web password is ignored")
        return None
    check = env_switch("WEB_PASSWORD_CHECK")
    password = read_web_password(check)
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


def main(argv=None) -> int:
    try:
        args, cfg = parse_args(argv)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if getattr(args, "multipage", "off") not in MULTIPAGE_MODES:
        print(f"error: invalid PUSHSCAN_MULTIPAGE {args.multipage!r}", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if not args.printer:
        print("error: --printer or PUSHSCAN_PRINTER is required", file=sys.stderr)
        return 2
    web_enabled = args.cmd == "run" and args.web
    web_password = None
    if web_enabled:
        try:
            web_password = web_password_setup()
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

    settings = fallback_settings(args, cfg)
    source = args.source
    try:
        targets = resolve_targets(args, cfg, name)
        for warning in check_targets(targets):
            logging.warning(warning)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    service = PushScanService(chmp, escl, targets, settings,
                              interval=getattr(args, "interval", 4.0),
                              auto_source=(source == "auto"),
                              use_panel=not getattr(args, "ignore_panel", True),
                              native=NativeScanner(args.printer),
                              multipage=MULTIPAGE_MODES.get(getattr(args, "multipage", "off"),
                                                            frozenset()),
                              trim=getattr(args, "trim", None))
    if args.cmd == "scan":
        for path in service.scan_to(targets[0]):
            print(path)
        return 0

    signal.signal(signal.SIGTERM, lambda *_: service.stop())
    signal.signal(signal.SIGINT, lambda *_: service.stop())
    for t in targets:
        logging.info("target %r -> %s", t.name, t.outdir)
    logging.info("waiting for scan requests from %s", args.printer)
    if not web_enabled:
        service.run()
        return 0

    # Web page: records the log, runs in a daemon thread next to the poll loop.
    log_buffer = LogBuffer()
    logging.getLogger().addHandler(log_buffer)
    overrides, effective = web_overrides(args, cfg, argv)
    ctx = web.WebContext(service, log_buffer, args.printer, args.output,
                         multipage_mode=args.multipage,
                         config_path=Path(args.config) if args.config else default_config_path(),
                         targets_from_env=bool(args.targets),
                         overrides=overrides, effective=effective)
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
    logging.info("web page on http://%s:%d%s", args.web_bind, server.server_address[1],
                 " (Secure cookie: use it through an HTTPS reverse proxy)"
                 if server.secure_cookie else "")
    try:
        service.run()
    finally:
        web.stop_server(server, thread)
        logging.getLogger().removeHandler(log_buffer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
