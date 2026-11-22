# Configuration

English | [Deutsch](configuration.de.md)

Back to the [README](../README.md).

- [Subcommands](#subcommands)
- [Options](#options)
- [Configuration file](#configuration-file)
- [Precedence](#precedence)
- [Changing the file while running](#changing-the-file-while-running)
- [Panel settings](#panel-settings)
- [Trimming a border](#trimming-a-border)
- [Multi-page scans from the platen](#multi-page-scans-from-the-platen)
- [ADF](#adf)
- [Multiple targets](#multiple-targets)
- [Panel names](#panel-names)
- [Presets per target](#presets-per-target)
- [File names](#file-names)

## Subcommands

Without a subcommand, `run` is used, so `pushscan2folder --printer 192.168.1.50`
works like `pushscan2folder --printer 192.168.1.50 run`. Global options
(`--config`, `--printer`, `--name`, `--log-file`, `--verbose`) go before the
subcommand; run options such as `--output` may be given without it.

Run the service:

```sh
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 run --output ./scans
```

Then choose the host on the printer panel (scan to PC) and start the scan.

At the start `run` logs a short summary: version, printer, config file,
each panel name with its folder, the web page address (or "web page off") and
the log file. The printer accepting a name is logged as "'NAME' is now on the
printer panel under Scan to PC", each saved scan as "saved PATH".

The other subcommands:

```sh
# Ask a few questions (printer, panel name, folder, web page, on Windows
# autostart) and write the config file. Run it again to change the file.
PYTHONPATH=src python3 -m pushscan2folder setup
```

If no printer is configured yet, setup first searches the local network for
eSCL scanners with mDNS (Bonjour, service `_uscan._tcp`). The search takes
about 5 seconds. It lists the address and model of each scanner it finds with a
number, and you type that number or an IP address. If nothing answers, setup
asks for the IP address as before. A firewall that blocks multicast or a VPN
can be the reason. The IP address is shown in the network settings on the
printer panel. The search needs only the Python standard library.

The password of the web page is never written to `config.toml`: setup stores it
in `web_password.txt` next to the config file (mode 0600 where supported) and
names that file in `[web] password_file`. If the file already has `[[target]]`
entries, setup asks only for printer, web page and autostart and leaves the
targets alone. Setup also starts by itself when the program is started
without any argument in a console and no config file exists yet; non-interactive
starts (Docker, services) never ask anything.

Run without a window (details for Windows in [windows.md](windows.md)):

```sh
# Start detached in the background with the current options and return.
# Windows: no console window. Linux/macOS: its own session.
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 start
PYTHONPATH=src python3 -m pushscan2folder status   # running?, PID, log file, last log lines
PYTHONPATH=src python3 -m pushscan2folder stop     # stops it and releases the panel names
```

`start` accepts the same options as `run` and refuses if a background instance
is already running. The log goes to the state folder
(`%LOCALAPPDATA%\pushscan2folder\pushscan2folder.log` on Windows,
`$XDG_STATE_HOME/pushscan2folder/pushscan2folder.log`, default
`~/.local/state/...`, elsewhere) unless `--log-file` is given. `stop` writes a
stop request file that the poll loop checks once per second and terminates the
process only if it has not ended after 30 seconds. While a scan runs, `stop`
waits up to 600 seconds (10 minutes) instead and prints "A scan is running; it
is finished and saved first ...". The instance keeps a busy marker file in its
state folder for the time of a scan. A multi-page platen scan that waits for
the next-page decision on the panel ends right away with the pages scanned so
far, and these are saved. A page that is being scanned finishes first.
`uninstall` runs `stop` too and waits in the same way. `status` exits with 0 if the
instance runs and 1 if not. A foreground `run` refuses to start while the
background instance runs, because both would register the same names. It
points to `pushscan2folder stop`.

```sh
# Stop the instance, remove the Windows autostart entry, then ask (default no)
# whether to delete the config folder and the log/state folder.
PYTHONPATH=src python3 -m pushscan2folder uninstall
# Non-interactive: keeps the config and log unless --purge is added.
PYTHONPATH=src python3 -m pushscan2folder uninstall --yes [--purge]
```

Scans are never deleted, and a folder that contains a scan folder is kept.

`health` checks whether the running service has talked to the printer
recently. It is used by the Docker healthcheck (see [Docker](docker.md#healthcheck)):

```sh
# Exit code 0 if the heartbeat file is younger than --max-age seconds
# (default 120), otherwise 1. It prints the reason.
PYTHONPATH=src python3 -m pushscan2folder health \
  --heartbeat-file /tmp/pushscan2folder.alive [--max-age 120]
```

`probe` and `scan` are for debugging:

```sh
# Register, poll once, print the raw answers and release (debugging).
# Add --keep to stay registered.
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 probe

# Scan once via eSCL without using the panel
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 scan --output ./scans
```

## Options

Global options go before the subcommand. Every option can also be set with an
environment variable. The command line wins over the environment, and the
environment wins over the [configuration file](#configuration-file). More in
[Precedence](#precedence).

| Option         | Env var            | Default             | Applies to    | Description |
|----------------|--------------------|---------------------|---------------|-------------|
| `--config`     | `PUSHSCAN_CONFIG`     | `~/.config/pushscan2folder/config.toml` if present | all | TOML configuration file, see [Configuration file](#configuration-file) |
| `--printer`    | `PUSHSCAN_PRINTER`    | (required)          | all           | Printer IP or host name |
| `--name`       | `PUSHSCAN_NAME`       | `USER  HOSTNAME`    | all           | Name shown on the panel, see [Panel names](#panel-names). The default replaces characters the panel cannot show with `-` |
| `-v/--verbose` | `PUSHSCAN_VERBOSE`    | off                 | all           | Debug logging. The env var enables it with `1`, `true` or `yes` |
| `--output`     | `PUSHSCAN_OUTPUT`     | `./scans`           | run, scan     | Output directory (created if missing) |
| `--interval`   | `PUSHSCAN_INTERVAL`   | `4`                 | run           | Poll interval in seconds |
| `--format`     | `PUSHSCAN_FORMAT`     | `pdf`               | run (env: run only) | `pdf` or `jpeg`. Fallback, see [Panel settings](#panel-settings) |
| `--color`      | `PUSHSCAN_COLOR`      | `color`             | run           | `color` or `gray`. Only used with `--ignore-panel` or if the panel sends no colour |
| `--resolution` | `PUSHSCAN_RESOLUTION` | `300`               | run           | DPI. Fallback. The panel offers 75, 150, 300, 600 |
| `--source`     | `PUSHSCAN_SOURCE`     | `auto`              | run (env: run only) | `auto`, `platen` or `adf`. Fallback |
| `--trim`       | `PUSHSCAN_TRIM`       | none                | run           | Cut off a border by scanning a smaller area, e.g. `right=1,bottom=2` (keys `left`, `top`, `right`, `bottom`, in mm, 0 to 50). Platen only. Replaces the `trim_*` config values as a whole, see [Trimming a border](#trimming-a-border) |
| `--targets`    | `PUSHSCAN_TARGETS`    | -                   | run           | Several panel entries, each with its own folder and optional preset, see [Multiple targets](#multiple-targets). Replaces `--name` for `run` |
| `--ignore-panel` | `PUSHSCAN_IGNORE_PANEL` | off             | run           | Ignore the panel settings and always use the four options above (`--format`, `--color`, `--resolution`, `--source`). Env var: `1`, `true` or `yes`. Also disables multi-page scans |
| `--multipage`  | `PUSHSCAN_MULTIPAGE`  | `document`          | run           | `document`, `auto`, `both` or `off`, see [Multi-page scans](#multi-page-scans-from-the-platen) |
| `--open-after-scan` | `PUSHSCAN_OPEN_AFTER_SCAN` | `false`     | run, start    | `true` or `false` (also `yes`/`no`, `1`/`0`, `on`/`off`; the old `folder` and `file` count as `true`). Desktop PC only: after a job is saved, open the folder (Windows: Explorer with the new file selected), once per job. On Linux it needs `DISPLAY` or `WAYLAND_DISPLAY`. A failure only logs a warning. Docker has no desktop, keep it `false` |
| `--filename`   | `PUSHSCAN_FILENAME`   | `scan_{now:%Y%m%d_%H%M%S}` | run    | Template for the file name of a scan, without the extension, see [File names](#file-names) |
| `--heartbeat-file` | `PUSHSCAN_HEARTBEAT_FILE` | -          | run, health   | File that `run` touches after every successful contact with the printer, and that `health` checks. The Docker image sets it, see [Docker](docker.md#healthcheck) |
| `--max-age`    | -                  | `120`               | health        | Seconds after which `health` calls the heartbeat file too old |
| `--no-pause`   | `PUSHSCAN_NO_PAUSE`   | off                 | all           | Windows: never wait for Enter before a console window opened for this program closes. The autostart entry sets it |
| `--web`        | `PUSHSCAN_WEB`        | off                 | run           | Serve the [web page](web.md). Env var: `1`, `true` or `yes` |
| `--web-port`   | `PUSHSCAN_WEB_PORT`   | `8080`              | run           | Port of the web page |
| `--web-bind`   | `PUSHSCAN_WEB_BIND`   | `0.0.0.0`           | run           | Address of the web page |
| -              | `PUSHSCAN_WEB_PASSWORD` / `PUSHSCAN_WEB_PASSWORD_FILE` | (required with `--web`) | run | Web password (min. 8 characters), or a file containing it. Env, or `[web] password_file` of the config file. Never the password itself in the config file |
| `--keep`       | -                  | off                 | probe         | Do not release the session |

Notes:

- `scan` has its own `--format` and `--source` options. They do not read the
  `PUSHSCAN_FORMAT` / `PUSHSCAN_SOURCE` variables, and `scan` always uses the
  default colour mode and resolution (color, 300 dpi) and always uses eSCL.
- The scan area comes from the panel size; without panel data it is A4.

## Configuration file

Instead of a long command line you can keep the settings in a TOML file
(this needs Python 3.11 for `tomllib`). See [config.example.toml](../config.example.toml)
for a commented example.

Location: `--config PATH` / `PUSHSCAN_CONFIG`; without it
`$XDG_CONFIG_HOME/pushscan2folder/config.toml` (default
`~/.config/pushscan2folder/config.toml`) is used if it exists. A path given
explicitly must exist, otherwise the program exits with an error.

Unknown keys, wrong types and invalid values are rejected with a message naming
the file and the key, so typos are caught.

| Key | Values | Same as |
|-----|--------|---------|
| `printer` | IP or host name | `--printer` |
| `output` | folder; relative target outputs resolve against it | `--output` |
| `[defaults]` `resolution` | `75`, `150`, `300`, `600` | `--resolution` |
| `[defaults]` `color` | `color`, `gray` | `--color` |
| `[defaults]` `format` | `pdf`, `jpeg` | `--format` |
| `[defaults]` `source` | `auto`, `platen`, `adf` | `--source` |
| `[defaults]` `size` | `a4`, `letter`, `legal`, `10x15`, `13x18` | scan area without panel data |
| `[defaults]` `open_after_scan` | `true`, `false` (the old `"off"`, `"folder"`, `"file"` are still read) | `--open-after-scan` |
| `[defaults]` `filename` | template, see [File names](#file-names) | `--filename` |
| `[defaults.document]` `multipage` | `true` / `false`, built-in `true` | `--multipage` (panel document type *Document*) |
| `[defaults.auto]` `multipage` | `true` / `false`, built-in `false` | `--multipage` (panel document type *Auto*) |
| `[advanced]` `interval` | seconds | `--interval` |
| `[advanced]` `verbose`, `ignore_panel` | `true` / `false` | `--verbose`, `--ignore-panel` |
| `[advanced]` `trim_left`, `trim_top`, `trim_right`, `trim_bottom` | number, mm, 0 to 50 | `--trim` |
| `[web]` `enabled` | `true` / `false` | `--web` |
| `[web]` `bind` | address, default `0.0.0.0` | `--web-bind` |
| `[web]` `port` | 1 to 65535, default 8080 | `--web-port` |
| `[web]` `password_file` | file holding the password; relative to the config file. The password itself is never a key | `PUSHSCAN_WEB_PASSWORD_FILE` |
| `[[target]]` `name` | required, max 31 chars, unique | `NAME` |
| `[[target]]` `output` | folder; `"."` is the output directory itself; default `<output>/<name>` | `NAME=DIR` |
| `[[target]]` `filename` | template, see [File names](#file-names); wins over `[defaults]` for this target | - |
| `[[target]]` `open_after_scan` | `true`, `false`; wins over `[defaults]` for this target, for example `false` for an archive folder | - |
| `[target.document]` `multipage` | `true` / `false` | `mp:` for document type *Document* |
| `[target.auto]` `resolution`, `format`, `size` | as above | the `@preset` options |
| `[target.auto]` `multipage` | `true` / `false` | `mp:` for document type *Auto scan* |

The multi-page booleans of a target start from `[defaults.document]` and
`[defaults.auto]` (or `--multipage`) and replace the value for that target. If
a target sets neither, it follows the defaults.

The printer panel has three document types. *Photo* needs no table, because the
panel sends all of its settings itself (JPEG, size, resolution). With *Document*
the panel sends them too and `[defaults.document]` only decides about the
multi-page dialog. With *Auto* the panel sends no size, format or resolution, so
`[defaults]` and `[target.auto]` decide.

If `[defaults.document]` or `[defaults.auto]` is left out, the built-in value applies (`true` for *Document*, `false` for *Auto*). Setting only one of them keeps
the built-in value of the other.

### Older config files

Files from earlier versions still work. The old keys are read and the log shows
a warning that lists them. Setup and the web page write the new layout.

| Old place | New place |
|-----------|-----------|
| `interval`, `verbose`, `ignore_panel` at the top level | `[advanced]` |
| `trim_*` in `[defaults]` | `[advanced]` |
| `multipage = "document"` (or `auto`, `both`, `off`) at the top level | `multipage` in `[defaults.document]` and `[defaults.auto]` |
| `document_multipage` in a `[[target]]` | `multipage` in `[target.document]` |

If the old and the new place of the same key are both present, the file is
rejected with a message such as "keep only ...".

## Precedence

Command line > environment variable > config file > built-in default.

- The Docker image sets `PUSHSCAN_OUTPUT=/scans`, so in the container the
  file's `output` key is overridden. Mount your folders below `/scans` or use
  absolute target outputs (see [Docker](docker.md)).
- If `--targets` / `PUSHSCAN_TARGETS` is set, it replaces the `[[target]]` list
  of the file completely.
- The panel settings come first for the scan itself, the CLI options only fill
  in, see [Panel settings](#panel-settings) and
  [Presets per target](#presets-per-target).

## Changing the file while running

Before each poll cycle, never during a scan, `run` checks the modification
time and size of the config file. If it changed, the file is read again like at
startup. Command line options and `PUSHSCAN_*` environment variables still win
over the file. This also applies to changes made on the [web page](web.md).

These are applied right away: the scan defaults (`[defaults]` keys, `size`,
`filename`, the `multipage` keys), `interval`, `ignore_panel` and the `trim_*`
values from `[advanced]`, `open_after_scan`, the targets, `output` and `printer`. Targets whose names stay
keep their registration on the panel. If the printer changes, the names are
released on the old printer and registered on the new one.

These need a restart: the web page on or off, its bind address, port and
password file, the log file, the debug log (`verbose` in `[advanced]`) and the heartbeat file.
If the file changes one of them, the log shows a warning that names it.

An invalid file, or an invalid file name template, is logged once as an error
and the running settings stay. A deleted file changes nothing. In Docker this
works when you edit `./config/config.toml` on the host.

## Panel settings

The printer sends 32 bytes with each scan request: document type, colour,
source, size, format, resolution, bleed-through, descreen and unsharp mask.
The tool maps these to eSCL, so the scan follows what you chose on the panel.

The CLI options `--format`, `--color`, `--resolution` and `--source` (and the
`PUSHSCAN_*` env vars) are only the fallback. They apply to document type
"Auto scan", where the panel sends no details, and to any field the panel
leaves unset. With `--ignore-panel` (or `PUSHSCAN_IGNORE_PANEL=1`) the CLI values
are always used.

- Bleed-through, descreen and unsharp mask have no eSCL equivalent and are
  ignored (see [Troubleshooting](troubleshooting.md#limitations)).
- "Compact PDF" is scanned as a normal PDF at 300 dpi.
- TIFF is not supported, because neither eSCL nor the native protocol delivers
  it. Such scans are saved as JPEG.
- Size "Auto" scans the full platen width at A4 height (no auto-crop).
- The panel resolutions 75/150/300/600 dpi all work over eSCL, even though the
  eSCL capabilities only list 75, 100, 150, 200, 600 and 1200.
- Cancelling a scan on the panel leaves a truncated document. The tool detects
  this and discards it, so nothing is saved.

## Trimming a border

Some scanners capture a thin border at the glass edge. On a TR8550, tests
showed `trim_right = 1` and `trim_bottom = 2` (mm) remove it. With
`--trim right=1,bottom=2` (or `PUSHSCAN_TRIM`, or the `trim_*` keys in the
`[advanced]` table of the config file) the tool asks the printer for a smaller scan area, so the border
is never scanned. No image processing is involved. Trimming applies to the
platen only, ADF scans are not trimmed. If less than 1 inch would remain in
either direction, trimming is skipped and a warning is logged. The setting is
global, not per target.

## Multi-page scans from the platen

For platen scans with document type *Document* the printer shows a dialog
after every page: *Stop*, *Black and white*, *Colour* and *Finish*. Put the
next page on the glass and press *Colour* or *Black and white* to scan it
(each page can have its own colour mode), or press *Finish* to end. All pages
are saved as one PDF (with format JPEG: one file per page).

This uses Canon's own scanner protocol (`/canon/ij/command2/port3`) instead of
eSCL, because only that protocol has the "next page" question.
The printer delivers each page as a JPEG; the PDF embeds the JPEGs unchanged.

`--multipage` (`PUSHSCAN_MULTIPAGE`) sets which document types get the
dialog. In the config file the same is set with `multipage` in
`[defaults.document]` (built-in `true`) and `[defaults.auto]` (built-in
`false`):

| Value                | Dialog for                                        |
|----------------------|---------------------------------------------------|
| `document` (default) | Document, like the official software              |
| `auto`               | Auto scan only                                    |
| `both`               | Document and auto scan                            |
| `off`                | never; all scans use eSCL                         |

Verified with A4 at 300 dpi; other resolutions and sizes use the same
parameters but have not been tested yet.

`1`/`true`/`yes` mean `document`, `0`/`false`/`no` mean `off`. With auto scan
the panel sends no resolution or format, so the fallback options are used.
ADF scans always use eSCL (the ADF already delivers all pages in one PDF).

The printer may reset the document type to *Auto scan* after a scan, so check
it before the next multi-page scan.

## ADF

The printer detects the source with its paper sensor; the panel has no source
choice. Legal size is only available from the ADF. The ADF is simplex only.
Without panel data (auto scan) and with `--source auto`, the tool asks the
printer whether paper is loaded. It uses the ADF if so and the platen otherwise.

## Multiple targets

One instance can register several names with the printer. Each name shows up as
its own computer on the panel, and its scans go to a separate folder:

```sh
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 run \
  --output ./scans --targets "Scans,Paperless=consume,Archive=/data/archive"
```

The list is separated by commas, and each entry takes one of two forms:

- `NAME` saves into `<output>/NAME`. Characters other than letters, digits, `.`, `_`
  and `-` become `_`.
- `NAME=DIR` saves into `DIR`. A relative `DIR` is resolved against `--output`,
  an absolute one is used as is. `.` means `--output` itself, without a subfolder.

Names must be unique and follow the [panel name rules](#panel-names). Two
targets may not share a folder (`a b` and `a_b` both map to `a_b`, for
example). All names share one poll loop, so the poll interval applies to the
whole list.

## Panel names

Observed on the TR8550:

- Only A-Z, a-z, 0-9, space, `-`, `_` and `@` are shown. The printer
  accepts other characters (`.`, `&`, umlauts, accents, emoji, ...) but shows
  them as blanks, so pushscan2folder rejects names containing them.
- Names have at most 31 characters. The panel shows about 25 and then `...`
  (a warning is logged for longer names).
- 20 names at the same time worked (a scrollable list), and no limit was found.
- The list is ordered by registration time, not alphabetically.

## Presets per target

Append `@` and options joined with `+` to give a target its own settings:

```sh
--targets "Scans,Paperless@300dpi,Archive@600dpi+jpeg+mp:both"
```

| Option | Meaning |
|--------|---------|
| `75dpi`, `150dpi`, `300dpi`, `600dpi` | resolution |
| `pdf`, `jpeg` | file format |
| `a4`, `letter`, `legal`, `10x15`, `13x18` | scan area |
| `mp:document`, `mp:auto`, `mp:both`, `mp:off` | multi-page dialog, overrides `--multipage` for this target |

Which value wins:

- Auto scan on the panel: the preset wins for resolution, format and size.
  The colour always comes from the panel (the start button pressed), a preset
  has no colour. Settings missing from the preset come from the global options.
- Document and photo: the panel settings win, and the preset only fills in
  what the panel does not send.
- With `--ignore-panel` the preset always applies.

Options are not case sensitive. An unknown option stops the program with an
error, so `NAME=DIR` cannot be used with a folder name containing `@`.

The `@preset` string is the short form of the `[target.auto]` table of the
[configuration file](#configuration-file).

For paperless-ngx, mount its consume folder inside the output directory, for
example `- /path/to/paperless/consume:/scans/Paperless` in Docker (see
[Docker](docker.md#paperless-ngx)), and use the target `Paperless@300dpi`. A
folder inside the output directory can also be chosen on the
[web page](web.md); an absolute one like `Paperless=/consume` works too, but
only from the command line or the config file.

## File names

The template for the name of a scan file is set with `filename` in
`[defaults]`, `--filename` or `PUSHSCAN_FILENAME`. A `filename` in a
`[[target]]` applies to that target only and wins over the other settings. The
usual precedence applies otherwise (see [Precedence](#precedence)). On the
[web page](web.md#pages) the Settings page has a "File name" field.

The default is `scan_{now:%Y%m%d_%H%M%S}`, which gives the same names as
before, for example `scan_20261122_183005.pdf`. The template has no extension,
because the extension comes from the format (`.pdf` or `.jpg`).

| Field | Meaning | Example |
|-------|---------|---------|
| `{name}` | the panel name, made safe for a file name | `My PC` gives `My_PC` |
| `{date}` | the date | `2026-11-22` |
| `{time}` | the time | `183005` |
| `{now:FORMAT}` | the date and time with Python `strftime` codes | `{now:%Y%m%d_%H%M%S}` gives `20261122_183005` |

```toml
[defaults]
filename = "{name}_{date}_{time}"     # My_PC_2026-11-22_183005.pdf

[[target]]
name = "Paperless"
filename = "scan_{now:%Y%m%d_%H%M%S}"   # this target keeps the default style
```

No other fields exist. Attribute access such as `{now.year}` and positional
fields such as `{}` are rejected, and so is a template that gives an empty
name. The program checks the template at startup, so a mistake stops it with an
error message and not in the middle of a scan.

The result is made safe for the file system:

- Characters that Windows does not allow in file names (`<>:"/\|?*` and
  control characters) become `_`, on every system. Spaces and dots at the start
  and the end are removed.
- The name is cut to 120 characters.
- A device name such as `CON` gets a `_` in front, as with
  [folder names](windows.md#where-files-go) on Windows.
- A job of several JPEG files gets `_01`, `_02` and so on after the name.
- An existing file is never overwritten. A `-1`, `-2` and so on is added to the
  name instead, for example `scan_20261122_183005-1.pdf`.

The target editor on the web page has no field for the template of a target.
Saving the targets on the web page keeps the `filename` that a target has in
the file.
