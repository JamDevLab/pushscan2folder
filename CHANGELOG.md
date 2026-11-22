# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

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
- Windows support: default config in `%APPDATA%\pushscan2folder`, scans in
  `Documents\Scans`, a single-file `pushscan2folder.exe` built by GitHub
  Actions and attached to each release, `--install-autostart` /
  `--remove-autostart` (per-user Run key), see `docs/windows.md`.
- `--log-file` / `PUSHSCAN_LOG_FILE`: rotating log file (1 MB x 3).
- Tests run on Linux, Windows and macOS. macOS is untested on real hardware.
- Issue forms for bug reports and printer reports.

### Changed

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
