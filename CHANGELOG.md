# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Clickable paths: setup and `start` print the config file, the scan folders and
  the log file as links (OSC 8) in Windows Terminal and in Linux terminals. The
  classic Windows console and the log file get the plain path.
- Config file reload: `run` checks the config file before each poll cycle
  (never during a scan) and applies a change without a restart. Scan defaults,
  `interval`, `ignore_panel`, `multipage`, `open_after_scan`, the targets,
  `output` and the printer are applied right away; names that stay keep their
  panel registration. The web page options, log file, debug log and heartbeat
  file still need a restart, and a warning names them. An invalid file is
  logged once and the running settings stay. The web Settings page and the raw
  config editor now take effect within a poll cycle. See
  [Configuration](docs/configuration.md#changing-the-file-while-running).
- Printer search on the web Settings page: "Search the network" runs the mDNS
  search and lists the scanners found with a "Use" button, which writes
  `printer` into the config file. Only an address from the last search can be
  used. There is no button if `PUSHSCAN_PRINTER` or `--printer` sets the
  printer. See [Web page](docs/web.md#pages).
- File name template: `[defaults] filename`, `filename` per `[[target]]` (the
  target's own wins), `--filename TEMPLATE`, `PUSHSCAN_FILENAME` and a "File
  name" field on the web Settings page. The default `scan_{now:%Y%m%d_%H%M%S}`
  gives the same names as before. Fields: `{name}`, `{date}`, `{time}` and
  `{now:FORMAT}` with `strftime` codes, for example
  `filename = "{name}_{date}_{time}"`. Characters not allowed in Windows file
  names become `_`, the name is cut to 120 characters and device names such as
  `CON` get a `_` in front. An existing file is never overwritten. The web
  target editor has no field for the template of a target and keeps the one
  from the file. See [Configuration](docs/configuration.md#file-names).
- Docker healthcheck: the image sets `PUSHSCAN_HEARTBEAT_FILE` and runs
  `pushscan2folder health` every 30 seconds. `run` touches the heartbeat file
  (`--heartbeat-file`, `PUSHSCAN_HEARTBEAT_FILE`) after every successful
  contact with the printer. `health [--heartbeat-file PATH] [--max-age SECONDS]`
  exits with 0 if the file is younger than `--max-age` (default 120 s), else
  with 1 and prints why. `docker ps` shows `healthy` or `unhealthy`. See
  [Docker](docs/docker.md#healthcheck).
- Printer search in setup: if no printer is configured yet, `pushscan2folder
  setup` (and the first double click on Windows) looks for eSCL scanners in the
  local network with mDNS (Bonjour, `_uscan._tcp`, about 5 seconds, standard
  library only) and lists them to pick by number; `s` searches again. The query is sent three
  times on every network adapter. If nothing answers, it asks for the IP
  address.
- Dependabot for GitHub Actions and the Docker base image (monthly).

### Fixed

- Windows, `open_after_scan = "folder"`: every scan opened one more Explorer
  window. If a window already shows the folder, the new file is now selected
  there.
- `pushscan2folder stop` during a scan used to terminate the program after 30
  seconds. It now waits up to 10 minutes while a scan runs, so the scan is
  finished and saved. A multi-page platen scan that waits for the next page ends
  right away with the pages scanned so far. The Windows installer and
  uninstaller run `stop` and wait in the same way.
- Setup's question "Start automatically when you log in to Windows?" removed
  the autostart entry instead of creating it (since 0.2.0).
- `--install-autostart` with run options but without a subcommand failed.
- A foreground `run` now refuses to start while the background instance runs,
  because both would register the same panel names, and points to
  `pushscan2folder stop`.
- Setup checks the bind address of the web page (an IP address or `localhost`,
  no port).
- A second "start over" in setup keeps the older backup (`config.toml.2.bak` and
  so on) instead of overwriting `config.toml.bak`.

## [0.2.0] - 2026-11-22

Windows support: an installer, background mode, a setup dialog and an
uninstall command, as an alternative to the Canon software on a Windows PC.

### Added

- Docker image on the GitHub Container Registry
  (`ghcr.io/jamdevlab/pushscan2folder`, amd64 and arm64, tags VERSION,
  MAJOR.MINOR and latest), built on each release. The compose file uses it, so
  no clone is needed.
- `pushscan2folder start` runs the program detached in the background (no
  console window on Windows, its own session elsewhere) with the same options
  as `run`; `stop` ends it cleanly so the panel names are released (stop request
  file checked by the poll loop, terminate after 30 s as a last resort);
  `status` shows PID, log file and the last log lines. One instance per user,
  guarded by a lock file in `%LOCALAPPDATA%\pushscan2folder` (Windows) or
  `$XDG_STATE_HOME/pushscan2folder`; stale files never block a start.
- `pushscan2folder uninstall`: stops the instance, removes the Windows autostart
  entry and optionally deletes the config and log/state folders (default no).
  `--yes` keeps them unless `--purge` is given. Scans are never deleted.
- `open_after_scan` (`off`, `folder`, `file`; `--open-after-scan`,
  `PUSHSCAN_OPEN_AFTER_SCAN`, `[defaults]`, web Settings page): opens the folder
  (Windows: Explorer with the file selected) or the file once per saved job on a
  desktop PC. Setup asks on Windows.
- Setup asks "Run in the background now?" on Windows; the foreground start
  summary points to `pushscan2folder start`.
- Icon for `pushscan2folder.exe` (`packaging/pushscan2folder.ico`, made with
  `packaging/make_ico.py` from `favicon.svg`).
- `run` is the default subcommand: `pushscan2folder --printer X` just runs.
- `run` logs a startup summary (version, printer, config file, panel names and
  folders, web page, log file) and "'NAME' is now on the printer panel under
  Scan to PC".
- `pushscan2folder setup`: interactive questions (printer with a reachability
  check, panel name, folder, web page, Windows autostart) that write the config
  file. It starts by itself on a double click without a config file.
- `[web]` config table (`enabled`, `bind`, `port`, `password_file`). The
  password stays out of `config.toml`; setup stores it in `web_password.txt`.
- Windows: a console opened only for the program waits for Enter before it
  closes. `--no-pause` / `PUSHSCAN_NO_PAUSE` turns it off; autostart sets it.
- Windows support (installer built with Inno Setup, per user, no administrator
  rights, Start menu entries, uninstall via Settings > Apps, around a folder
  build with a self-compiled bootloader to avoid virus scanner false alarms):
  default config in `%APPDATA%\pushscan2folder`, scans in `Documents\Scans`,
  built by GitHub Actions and attached to each release, `--install-autostart` /
  `--remove-autostart` (per-user Run key), see `docs/windows.md`.
- A double click (or the Start menu entry) with an existing config file shows
  the current settings and asks: use them (default), change them, or start over
  (the old file is kept as `config.toml.bak`). A broken config file offers to
  start over. If the program already runs in the background, it says so and
  points to `pushscan2folder stop`. With arguments in a command prompt, and on
  Linux and macOS, nothing changes.
- A target with `output = "."` saves into the output directory itself. Setup
  now writes its single target that way, so scans go straight into the chosen
  folder, without a subfolder per name. The web page accepts `.` too.
- `--log-file` / `PUSHSCAN_LOG_FILE`: rotating log file (1 MB x 3).
- Tests run on Linux, Windows and macOS. macOS is untested on real hardware.
- Issue forms for bug reports and printer reports.

### Changed

- The Windows autostart entry runs `pushscan2folder start` (background, no
  window that stays) instead of `cmd /c start /min`. Install it again to switch.
- The README is shorter; details moved to pages under `docs/`. It now has a
  complete compose example.
- Folder names typed on the web page must also be valid on Windows: no
  `: < > " | ? *`, no device names like `CON`, no trailing dot or space.
  Target names that are device names get a `_` prefix for their folder.

## [0.1.0] - 2026-11-22

First release, tested with a Canon PIXMA TR8550 (TR8500 series).

### Added

- Registration with the printer over CHMP push-scan notifications: the host
  shows up in the printer's "scan to PC" list. The printer is polled every
  4 s like the official software (`--interval` / `PUSHSCAN_INTERVAL`).
  Dropped registrations are renewed automatically, and registrations stay
  alive during long scans.
- Scanning over eSCL with PDF or JPEG output, including the ADF.
- Multi-page scans from the platen over Canon's native scanner protocol: with
  document type *Document* the panel asks for the next page (colour or black
  and white per page), and all pages are saved as one PDF. Stop during a page
  cancels the scan and keeps the pages scanned before.
  `--multipage` / `PUSHSCAN_MULTIPAGE` (`document`, `auto`, `both`, `off`)
  selects the document types that get the dialog.
- Panel settings (document type, colour, source, size, format, resolution)
  are decoded and used. TIFF is saved as JPEG. `--ignore-panel` /
  `PUSHSCAN_IGNORE_PANEL` always uses the command line values instead.
- Several targets, each with its own panel name and output folder, and an
  optional preset per target (`NAME[=DIR]@OPTION+OPTION`) for the auto
  document type, where the panel sends no settings. A preset has no colour,
  the colour always comes from the start button pressed on the panel.
- Panel names are checked: only characters the panel can show (A-Z, a-z, 0-9,
  space, `-`, `_`, `@`), at most 31 characters, a warning above 25, and no two
  targets in the same folder.
- Optional TOML configuration file (`--config` / `PUSHSCAN_CONFIG`, default
  `~/.config/pushscan2folder/config.toml`). Precedence: command line >
  environment > file > built-in. See `config.example.toml`.
- Optional web page (`--web` / `PUSHSCAN_WEB`, off by default) for local use:
  status, log, a target editor, a settings form (scan defaults, trim,
  multipage, interval; shows environment and command line overrides) and a
  raw config file editor (validated, no change of `output`, `printer` or of
  target folders outside the output directory, stale-file check). Password from
  `PUSHSCAN_WEB_PASSWORD` or `PUSHSCAN_WEB_PASSWORD_FILE`, login lockout,
  CSRF protection, strict headers. It works without JavaScript; one small
  script updates status and log in place and warns about unsaved changes
  on the edit pages. Targets can be reordered, the panel lists them in that
  order. Folders set on the web page
  stay inside the output directory. Opt-in `PUSHSCAN_WEB_SECURE_COOKIE=1`
  for use behind an HTTPS reverse proxy.
- Opt-in `PUSHSCAN_WEB_PASSWORD_CHECK=0` skips the web password rules (minimum
  length, example password; an empty password is still refused) and logs a
  warning. Opt-in `PUSHSCAN_WEB_AUTH=0` runs the web page without a login: a
  warning at startup, a "No password set" notice in the navigation, CSRF
  tokens, Origin checks and the folder restrictions stay in place. Only for a
  trusted network, never with a port forwarded to the internet.
- The `config.toml` page has its own tab in the navigation. The target editor
  has a new layout: grouped fields, move and remove buttons in the card
  header, and a sticky bar with Save, "Unsaved changes" and Add target.
- Size and count limits for all data received from the printer.
- Trim option: `--trim` / `PUSHSCAN_TRIM` (for example `right=3,bottom=2`) and
  the `trim_left`, `trim_top`, `trim_right`, `trim_bottom` keys in `[defaults]`
  cut off a border at the glass edge by requesting a smaller scan area from
  the printer. Platen scans only.
- Docker image and `docker-compose.yml`; `--version`.
