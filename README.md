<p align="center">
  <img src="src/pushscan2folder/favicon.svg" width="96" alt="pushscan2folder icon">
</p>

<h1 align="center">pushscan2folder</h1>

<p align="center">Use a Linux machine or a Docker container as a "scan to PC" destination for Canon IJ printers.</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-1F5FAD" alt="License: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-1F5FAD" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/dependencies-none-1F5FAD" alt="dependencies: none">
  <img src="https://img.shields.io/badge/docker-ready-2496ED" alt="Docker">
</p>

<p align="center">English | <a href="README.de.md">Deutsch</a></p>

`pushscan2folder` registers itself with the printer, so its name shows up in the
printer's "scan to PC" list on the panel. When you pick it there, the tool
scans and saves the result as a PDF or JPEG file. Tested with a Canon PIXMA TR8550 (TR8500 series).

## Features

- Adds a "scan to PC" entry to the printer panel
- Several targets, each with its own folder
- Multi-page PDFs from the glass, with the next-page dialog on the panel
- Presets per target for the auto document type
- Optional password-protected web page for status, log, targets and settings
- Docker and NAS ready, only outbound connections to the printer (TCP 80)
- Python 3.11+, standard library only

## Quick start

With Docker Compose:

```sh
git clone https://github.com/JamDevLab/pushscan2folder.git
cd pushscan2folder
mkdir -p scans config && cp config.example.toml config/config.toml
```

Set the printer IP in `docker-compose.yml` and the targets in
`config/config.toml`, then:

```sh
docker compose up -d --build
docker compose logs -f
```

The web page is off by default. To turn it on, uncomment the web lines in
`docker-compose.yml` (`PUSHSCAN_WEB`, your own `PUSHSCAN_WEB_PASSWORD` and the
port) and open port 8080.

On plain Linux:

```sh
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 run --output ./scans
```

Then choose the host on the printer panel (scan to PC) and start the scan.
Details are in [Docker](#docker) and [Usage](#usage).

## Contents

- [Usage](#usage)
- [Options](#options)
- [Configuration file](#configuration-file)
- [Panel settings](#panel-settings)
- [Multiple targets](#multiple-targets)
- [Web page (optional)](#web-page-optional)
- [Docker](#docker)
- [How it works](#how-it-works)
- [Tested models and limitations](#tested-models-and-limitations)
- [Contributing](#contributing)
- [Developed with AI](#developed-with-ai)
- [License](#license)

## Usage

Run the service:

```sh
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 run --output ./scans
```

Then choose the host on the printer panel (scan to PC) and start the scan.

Other subcommands:

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
environment wins over the [configuration file](#configuration-file).

| Option         | Env var            | Default             | Applies to    | Description |
|----------------|--------------------|---------------------|---------------|-------------|
| `--config`     | `PUSHSCAN_CONFIG`     | `~/.config/pushscan2folder/config.toml` if present | all | TOML configuration file, see [Configuration file](#configuration-file) |
| `--printer`    | `PUSHSCAN_PRINTER`    | (required)          | all           | Printer IP or host name |
| `--name`       | `PUSHSCAN_NAME`       | `USER  HOSTNAME`    | all           | Name shown on the panel, see [Panel names](#panel-names). The default replaces characters the panel cannot show with `-` |
| `-v/--verbose` | `PUSHSCAN_VERBOSE`    | off                 | all           | Debug logging. The env var enables it with `1`, `true` or `yes` |
| `--output`     | `PUSHSCAN_OUTPUT`     | `./scans`           | run, scan     | Output directory (created if missing) |
| `--interval`   | `PUSHSCAN_INTERVAL`   | `4`                 | run           | Poll interval in seconds |
| `--format`     | `PUSHSCAN_FORMAT`     | `pdf`               | run (env: run only) | `pdf` or `jpeg`. Fallback, see Panel settings |
| `--color`      | `PUSHSCAN_COLOR`      | `color`             | run           | `color` or `gray`. Only used with `--ignore-panel` or if the panel sends no colour |
| `--resolution` | `PUSHSCAN_RESOLUTION` | `300`               | run           | DPI. Fallback. The panel offers 75, 150, 300, 600 |
| `--source`     | `PUSHSCAN_SOURCE`     | `auto`              | run (env: run only) | `auto`, `platen` or `adf`. Fallback |
| `--trim`       | `PUSHSCAN_TRIM`       | none                | run           | Cut off a border by scanning a smaller area, e.g. `right=3,bottom=2` (keys `left`, `top`, `right`, `bottom`, in mm, 0 to 50). Platen only. Replaces the `trim_*` config values as a whole, see [Trimming](#trimming-a-border) |
| `--targets`    | `PUSHSCAN_TARGETS`    | -                   | run           | Several panel entries, each with its own folder and optional preset (see below). Replaces `--name` for `run` |
| `--ignore-panel` | `PUSHSCAN_IGNORE_PANEL` | off             | run           | Ignore the panel settings and always use the four options above. Env var: `1`, `true` or `yes`. Also disables multi-page scans |
| `--multipage`  | `PUSHSCAN_MULTIPAGE`  | `document`          | run           | `document`, `auto`, `both` or `off`, see [Multi-page scans](#multi-page-scans-from-the-platen) |
| `--web`        | `PUSHSCAN_WEB`        | off                 | run           | Serve the [web page](#web-page-optional). Env var: `1`, `true` or `yes` |
| `--web-port`   | `PUSHSCAN_WEB_PORT`   | `8080`              | run           | Port of the web page |
| `--web-bind`   | `PUSHSCAN_WEB_BIND`   | `0.0.0.0`           | run           | Address of the web page |
| -              | `PUSHSCAN_WEB_PASSWORD` / `PUSHSCAN_WEB_PASSWORD_FILE` | (required with `--web`) | run | Web password (min. 8 characters), or a file containing it. Env only, never the config file |
| `--keep`       | -                  | off                 | probe         | Do not release the session |

Notes:

- `scan` has its own `--format` and `--source` options. They do not read the
  `PUSHSCAN_FORMAT` / `PUSHSCAN_SOURCE` variables, and `scan` always uses the
  default colour mode and resolution (color, 300 dpi) and always uses eSCL.
- The scan area comes from the panel size; without panel data it is A4.

## Configuration file

Instead of a long command line you can keep the settings in a TOML file
(this needs Python 3.11 for `tomllib`). See [config.example.toml](config.example.toml)
for a commented example.

Location: `--config PATH` / `PUSHSCAN_CONFIG`; without it
`$XDG_CONFIG_HOME/pushscan2folder/config.toml` (default
`~/.config/pushscan2folder/config.toml`) is used if it exists. A path given
explicitly must exist, otherwise the program exits with an error.

Precedence: command line > environment variable > config file > built-in
default. The Docker image sets `PUSHSCAN_OUTPUT=/scans`, so in the container the
file's `output` key is overridden. Mount your folders below `/scans` or use
absolute target outputs. If `--targets` / `PUSHSCAN_TARGETS` is set, it replaces
the `[[target]]` list of the file completely. Unknown keys, wrong types and
invalid values are rejected with a message naming the file and the key, so
typos are caught.

| Key | Values | Same as |
|-----|--------|---------|
| `printer` | IP or host name | `--printer` |
| `output` | folder; relative target outputs resolve against it | `--output` |
| `interval` | seconds | `--interval` |
| `verbose`, `ignore_panel` | `true` / `false` | `--verbose`, `--ignore-panel` |
| `multipage` | `document`, `auto`, `both`, `off` | `--multipage` |
| `[defaults]` `resolution` | `75`, `150`, `300`, `600` | `--resolution` |
| `[defaults]` `color` | `color`, `gray` | `--color` |
| `[defaults]` `format` | `pdf`, `jpeg` | `--format` |
| `[defaults]` `source` | `auto`, `platen`, `adf` | `--source` |
| `[defaults]` `size` | `a4`, `letter`, `legal`, `10x15`, `13x18` | scan area without panel data |
| `[defaults]` `trim_left`, `trim_top`, `trim_right`, `trim_bottom` | number, mm, 0 to 50 | `--trim` |
| `[[target]]` `name` | required, max 31 chars, unique | `NAME` |
| `[[target]]` `output` | folder; default `<output>/<name>` | `NAME=DIR` |
| `[[target]]` `document_multipage` | `true` / `false` | `mp:` for document type *Document* |
| `[target.auto]` `resolution`, `format`, `size` | as above | the `@preset` options |
| `[target.auto]` `multipage` | `true` / `false` | `mp:` for document type *Auto scan* |

The multi-page booleans start from the global `multipage` mode and add or
remove *Document* / *Auto scan* for that target. If a target sets neither, it
follows the global mode.

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
  ignored (see Limitations).
- "Compact PDF" is scanned as a normal PDF at 300 dpi.
- TIFF is not supported, because neither eSCL nor the native protocol delivers
  it. Such scans are saved as JPEG.
- Size "Auto" scans the full platen width at A4 height (no auto-crop).
- The panel resolutions 75/150/300/600 dpi all work over eSCL, even though the
  eSCL capabilities only list 75, 100, 150, 200, 600 and 1200.
- Cancelling a scan on the panel leaves a truncated document. The tool detects
  this and discards it, so nothing is saved.

### Trimming a border

Some scanners capture a thin border at the glass edge. The TR8550 seems to
show about 3 mm on the right and 2 mm at the bottom (still to be verified).
With `--trim right=3,bottom=2` (or `PUSHSCAN_TRIM`, or the `trim_*` keys in the
config file) the tool asks the printer for a smaller scan area, so the border
is never scanned. No image processing is involved. Trimming applies to the
platen only, ADF scans are not trimmed. If less than 1 inch would remain in
either direction, trimming is skipped and a warning is logged. The setting is
global, not per target.

### Multi-page scans from the platen

For platen scans with document type *Document* the printer shows a dialog
after every page: *Stop*, *Black and white*, *Colour* and *Finish*. Put the
next page on the glass and press *Colour* or *Black and white* to scan it
(each page can have its own colour mode), or press *Finish* to end. All pages
are saved as one PDF (with format JPEG: one file per page).

This uses Canon's own scanner protocol (`/canon/ij/command2/port3`) instead of
eSCL, because only that protocol has the "next page" question.
The printer delivers each page as a JPEG; the PDF embeds the JPEGs unchanged.

`--multipage` (`PUSHSCAN_MULTIPAGE`) sets which document types get the
dialog:

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

### ADF

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
  an absolute one is used as is.

Names must be unique and follow the [panel name rules](#panel-names). Two
targets may not share a folder (`a b` and `a_b` both map to `a_b`, for
example). All names share one poll loop, so the poll interval applies to the
whole list.

### Panel names

Observed on the TR8550:

- Only A-Z, a-z, 0-9, space, `-`, `_` and `@` are shown. The printer
  accepts other characters (`.`, `&`, umlauts, accents, emoji, ...) but shows
  them as blanks, so pushscan2folder rejects names containing them.
- Names have at most 31 characters. The panel shows about 25 and then `...`
  (a warning is logged for longer names).
- 20 names at the same time worked (a scrollable list), and no limit was found.
- The list is ordered by registration time, not alphabetically.

### Presets per target

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
example `- /path/to/paperless/consume:/scans/Paperless` in Docker, and use the
target `Paperless@300dpi`. A folder inside the output directory can also
be chosen on the web page; an absolute one like `Paperless=/consume` works
too, but only from the command line or the config file.

## Web page (optional)

A small web page for local use (LAN, NAS) with the current status, recent
scans, the log, an editor for the targets, a settings form and a raw editor
for the config file. It is off by default and needs no extra packages. It
works without JavaScript. One small script (`/app.js`, served by the program
itself, no inline scripts) updates the status and log pages in place without
a visible reload, warns about unsaved changes on the edit pages and lets the
Tab key insert two spaces in the raw editor. Without JavaScript the status and
log pages simply reload every 10 s.

```sh
PUSHSCAN_WEB=1 PUSHSCAN_WEB_PASSWORD='a long password' \
PUSHSCAN_CONFIG=~/pushscan.toml \
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 run
# web page on http://0.0.0.0:8080
```

| Setting | Meaning |
|---------|---------|
| `PUSHSCAN_WEB=1` / `--web` | enable (`run` only) |
| `PUSHSCAN_WEB_PORT` / `--web-port` | port, default 8080 |
| `PUSHSCAN_WEB_BIND` / `--web-bind` | address, default `0.0.0.0` (use `127.0.0.1` to keep it local) |
| `PUSHSCAN_WEB_PASSWORD` | password, at least 8 characters |
| `PUSHSCAN_WEB_PASSWORD_FILE` | file with the password (e.g. a Docker secret); used if the variable above is unset |
| `PUSHSCAN_WEB_SECURE_COOKIE=1` | only behind an HTTPS reverse proxy: `Secure` cookie (see HTTPS below) |
| `PUSHSCAN_WEB_PASSWORD_CHECK=0` | skip the password rules (see below) |
| `PUSHSCAN_WEB_AUTH=0` | no login at all (see below) |

Without a valid password the program refuses to start (exit code 2). It never
reads the password from the config file and never logs or shows it.

Two opt-in switches relax this. Both are environment variables only (no command
line option, no config file key), and anything but a clear `1` or `0` is an
error, so a typo cannot turn a protection off.

- `PUSHSCAN_WEB_PASSWORD_CHECK=0` skips the password rules: the minimum of 8
  characters and the rejection of the example password `change-me-please`. An
  empty password is still an error. The program logs one warning at startup.
- `PUSHSCAN_WEB_AUTH=0` runs the web page without a login. No password is
  needed; one that is set is ignored, and the log says so. The program logs a
  warning at startup, and every page shows "No password set" in the navigation
  bar. Anyone who can reach the port can change the targets and the settings
  and can edit the config file. Use it only in a trusted network and never
  with a port forwarded to the internet. Everything else stays: CSRF tokens
  on all forms (one per process instead of per session), the Origin check,
  the security headers, and the rule that target folders stay inside the
  output directory.
  Without a login the page answers only when it is opened by IP address,
  as `localhost`, by a name without dots (`nas`) or by a local name ending in
  `.local`, `.lan`, `.home`, `.home.arpa`, `.internal` or `.fritz.box`. This
  blocks DNS rebinding, where a foreign website makes its own name point to
  your NAS.

Pages:

- Status (`/`) shows the printer, the last successful poll or last error,
  pending target changes, the targets (folder, registered, auto-scan preset,
  multi-page) and the last scans. It refreshes every 10 s.
- Log (`/log`) shows the last 500 log lines (INFO and above).
- Targets (`/targets`) adds, changes and deletes targets with name, folder,
  multi-page dialog and the auto-scan preset. Names and folders are validated
  as in the config file. The cards can be reordered with "Move up" and
  "Move down", and "Add target" adds an empty card; none of this is saved
  until you press Save. The printer panel lists the targets in this order,
  so after a change of the order the names briefly disappear while they are
  registered again. Saving writes the config file, and the running
  service switches to the new list before its next poll cycle (shown as
  "pending" until then). The per-target Auto scan options show the current
  default, for example "Default (300 dpi)", which comes from the Settings page.
- Settings (`/settings`) edits `resolution`, `color`, `format`, `source`,
  `size` and the four `trim_*` values of `[defaults]`, and `multipage`,
  `ignore_panel` and `interval`, each with a short explanation. Values are
  validated with the same rules as the config file; an empty field removes the
  key. `printer` and the base `output` folder are shown read-only. If an
  environment variable or command line option overrides a value (for example
  `PUSHSCAN_INTERVAL` or `PUSHSCAN_TRIM`), the page says so and shows the
  value in use; the saved value has no effect while the override exists.
  Settings are written to the file only and take effect after a restart.
- Config file (`/config`, linked from Settings) is a text editor for the whole
  config file. It writes the text exactly as given, comments included, after
  checking it like at startup; an invalid file is not written and the error
  (with line number for TOML syntax errors) is shown next to your text. The web
  page still gets no file access beyond the output directory, so the editor
  refuses a changed `output` or `printer`, and a `[[target]]` whose output
  folder is not a relative path inside the output directory. Targets already
  in the file with such a folder (for example `output = "/consume"`) may stay
  unchanged. The form carries a hash of the file text: if the file changed on
  disk meanwhile, nothing is saved and the new content is shown. Target
  changes are applied like on the Targets page, everything else after a
  restart. The size limit is 64 KB.

Whether the targets can be edited depends on where they come from:

- from `PUSHSCAN_TARGETS` / `--targets`: editing is disabled, because the
  variable would override the file at the next start;
- from the config file (`PUSHSCAN_CONFIG`, `--config` or the default location):
  editable; if the file does not exist yet, the first save creates it.

Comments in the config file are lost when saving from the Targets or Settings
form. The file is rewritten; other keys keep their values. Only the raw editor
keeps comments. Every saved target gets both
multi-page switches written explicitly.

Folders set on the web page are always inside the output directory
(`--output` / `PUSHSCAN_OUTPUT`, `/scans` in Docker). Enter a plain relative
path such as `Paperless` or `office/invoices`. The page rejects absolute paths,
`..`, backslashes and symlinks that lead outside the output directory, so it
cannot write anywhere else. A target whose folder is outside the output
directory (for example `output = "/consume"`) can only be changed in the config
file. The web page shows it read-only and keeps it when you save; you can still
delete it there.

Security notes:

- The page uses plain HTTP with a shared password. Use it in a trusted LAN only
  and never expose it to the internet. Anyone who can sniff your network can
  read the password and the session cookie.
- The cookie is `HttpOnly` and `SameSite=Strict`. A session ends after 2 hours
  without a request, 12 hours after login, or when the service restarts. At
  most 20 sessions exist at a time. The server keeps only a hash of each
  session token.
- Use a long password. After 5 wrong passwords the login is locked for 1
  minute; each further lockout doubles this, up to 15 minutes. The lock is
  global, not per IP, because behind a Docker port mapping all clients look
  alike.
- Prefer `PUSHSCAN_WEB_PASSWORD_FILE` (for example a Docker secret) over
  `PUSHSCAN_WEB_PASSWORD`, because environment variables are visible in
  `docker inspect`.
- Every form carries a CSRF token, cross-origin POSTs are rejected, and the
  pages send strict headers (CSP, no framing, no caching). Only the pages
  themselves, a stylesheet, the icon and the small script are served; the web page cannot read
  or download files.
- Browsers send cookies to every service on the same host regardless of the
  port, so reach the page by its own host name if other web services run on
  the same NAS.

HTTPS: put a TLS reverse proxy (Caddy, nginx, Traefik) in front and set
`PUSHSCAN_WEB_SECURE_COOKIE=1`. The cookie is then called `__Host-p2f_session`
and marked `Secure`, so the page works only through HTTPS. The proxy must pass
on the original `Host` header (nginx: `proxy_set_header Host $host;`),
otherwise forms are refused with "Origin does not match Host". Bind the service
to an internal address (`PUSHSCAN_WEB_BIND`) so it cannot be reached around
the proxy.

Docker: the provided `docker-compose.yml` is prepared for the web page
(`./config:/config`, `PUSHSCAN_CONFIG: /config/config.toml`); uncomment the
web lines and the port to turn it on. Mount
a directory for the config, not a single file: a single-file bind mount cannot
be replaced atomically, so the program would fall back to rewriting it in
place. The directory must be writable for the user set in `user:`. Do not set
`PUSHSCAN_TARGETS` when you edit the targets on the web page.

## Docker

Build and run:

```sh
docker build -t pushscan2folder .
mkdir -p scans
docker run -d --name pushscan2folder --restart unless-stopped \
  --user "$(id -u):$(id -g)" \
  -e PUSHSCAN_PRINTER=192.168.1.50 -e PUSHSCAN_NAME=docker-scan \
  -v "$PWD/scans:/scans" pushscan2folder
```

Or use the provided `docker-compose.yml`. It keeps the targets and scan
settings in `config/config.toml`; only the printer IP and the (commented
out) web settings are in the compose file:

```sh
mkdir -p scans config && cp config.example.toml config/config.toml
# set PUSHSCAN_PRINTER in docker-compose.yml (and the web lines if wanted)
docker compose up -d --build
docker compose logs -f
```

The program refuses to start with the example password `change-me-please`.
Every option can also be set as an environment variable (see
[Options](#options)), which then wins over the config file.

The image runs as a non-root user. The output directory must be writable by
that user. Either pass `--user "$(id -u):$(id -g)"` (as above, or `user:` in
compose) so files belong to you, or `chown` the host directory to the
container user's UID (check with `docker run --rm --entrypoint id pushscan2folder`).

Scanning needs no port mapping; the container only connects out to the
printer on TCP 80. Port 8080 is only for the web page.

## How it works

1. Register. The tool announces itself to the printer with Canon's CHMP
   push-scan notification protocol (HTTP POST to
   `/canon/ij/command1/port2`). The name you chose appears on the panel.
2. Poll. The tool polls the printer every 4 seconds like the official software (configurable). If the
   printer is unreachable, it registers again with exponential back-off, capped
   at 10 s, so the names reappear within about 10 s after a printer restart.
3. Scan. When the user starts a scan to this host on the panel, the poll
   answer has status `0x8000` ("scan requested") and carries 32 bytes of panel
   settings. The tool scans with these settings, using either Canon's own
   scanner protocol (multi-page platen scans, see below) or eSCL. It writes
   `scan_YYYYmmdd_HHMMSS[_NN].pdf|jpg` into the output directory and never
   overwrites existing files. Selecting a name on the panel without
   starting a scan triggers nothing.
4. Release. On SIGINT/SIGTERM the tool releases the session.

The tool needs Python >= 3.11 and the standard library only. It makes only outbound connections to the printer (TCP 80). No inbound ports are needed (except for the optional web page), so Docker's default bridge networking works.

### Registration and long scans

The printer drops a registration after roughly 60 s without polls (status
`0x1`). While a scan runs (multi-page platen scans as well as long eSCL scans,
e.g. 600 dpi or several ADF pages) the tool keeps polling every 5 s, so the
names stay on the panel. If a registration is dropped anyway, the tool
registers again automatically.

### Protocol summary

Transport: HTTP POST to `http://<printer>:80/canon/ij/command1/port2` with the
headers `Content-Type: application/octet-stream`, `X-CHMP-Version: 1.0`,
`X-CHMP-CommandType: BJNPNotify`, `X-CHMP-EventType: PuScan`.

Request body, 0x68 bytes, big endian:

| Offset | Size     | Field        | Notes                                      |
|--------|----------|--------------|--------------------------------------------|
| +0x00  | u16      | type         | 1 = register, 2 = poll, 4 = release        |
| +0x02  | u16      | reserved     |                                            |
| +0x04  | u32      | session id   | poll / release                             |
| +0x08  | 64 bytes | host name    | UTF-16BE, NUL padded (register only)       |
| +0x48  | u32      | reserved     |                                            |
| +0x60  | u32      | reserved     |                                            |

Response body, 0x110 bytes, big endian:

| Offset | Size     | Field          | Notes                                    |
|--------|----------|----------------|------------------------------------------|
| +0x02  | u16      | status         | 0x8000 = scan requested (poll)           |
| +0x04  | u32      | session id     | register                                 |
| +0x08  | u32      | unknown        |                                          |
| +0x0c  | u32      | event value    | poll, status 0x8000                      |
| +0x10  | 32 bytes | interrupt data | poll, status 0x8000                      |
| +0x8c  | u32      | unknown        |                                          |

The layout of the 32 interrupt bytes and the open questions are in
[docs/PROTOCOL.md](docs/PROTOCOL.md).

## Tested models and limitations

| Model                    | Verified features                               | Status |
|--------------------------|-------------------------------------------------|--------|
| Canon PIXMA TR8550 (TR8500 series) | push scan, multi target, ADF, panel settings, multi-page platen | ok     |

To report another model, see [CONTRIBUTING.md](CONTRIBUTING.md).

Limitations:

- Only tested with a Canon PIXMA TR8550. Other IJ models may or may not work.
- The panel settings "reduce bleed-through", "descreen" and "unsharp mask" are
  read but not applied yet. eSCL has no equivalent, and the official software
  probably applies them on the PC. Applying them would need image processing on
  your computer and may be added later, for example as an optional extra.
- Protocol details and open questions are in [docs/PROTOCOL.md](docs/PROTOCOL.md).
- Panel names: 31 characters, about 25 visible, ASCII letters, digits, space, `-`, `_`, `@` only.
- The tool contacts only the printer. Discovery is not implemented, so you must
  give the printer address.

## Contributing

Run the tests with:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

To report another printer model or to contribute, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Developed with AI

This project was developed with the help of an AI coding assistant (Claude by
Anthropic). The assistant wrote most of the code, tests and documentation and
helped analyse the network captures. The maintainer directed the work, made
the design decisions and tested the features with a real printer.

## License

pushscan2folder is licensed under AGPL-3.0-or-later, see [LICENSE](LICENSE).
Canon and PIXMA are trademarks of Canon Inc. This project is not affiliated with or endorsed by Canon.

### Legal note

This project contains no Canon code or binaries and distributes none. The CHMP
push-scan protocol was reimplemented from scratch, based on static analysis of
the Windows tool "IJ Network Scanner Selector EX2". The scanner protocol for
multi-page scans is based on observing the network traffic between the official
software and the printer. Both were done solely for interoperability purposes.
