# Configuration

English | [Deutsch](configuration.de.md)

Back to the [README](../README.md).

- [Subcommands](#subcommands)
- [Options](#options)
- [Configuration file](#configuration-file)
- [What the panel decides](#what-the-panel-decides)
- [Keys](#keys)
- [Next page dialog](#next-page-dialog)
- [Folders](#folders)
- [Date fields in folders](#date-fields-in-folders)
- [Document type Auto](#document-type-auto)
- [Trimming a border](#trimming-a-border)
- [Checking the file](#checking-the-file)
- [Precedence](#precedence)
- [Changing the file while running](#changing-the-file-while-running)
- [Panel settings](#panel-settings)
- [ADF](#adf)
- [Multiple targets](#multiple-targets)
- [Panel names](#panel-names)
- [File names](#file-names)

## Subcommands

Without a subcommand, `run` is used, so `pushscan2folder --printer 192.168.1.50`
works like `pushscan2folder --printer 192.168.1.50 run`. Global options
(`--config`, `--printer`, `--name`, `--log-file`, `--verbose`) go before the
subcommand; run options such as `--folder` may be given without it.

Run the service:

```sh
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 run --folder ./scans
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

The web page needs no password when it listens on this PC only (`bind` is
`127.0.0.1`, `::1` or `localhost`); setup then asks for none. The password of
the web page is never written to `config.toml`: setup stores it
in `web_password.txt` next to the config file (mode 0600 where supported) and
names that file in `[web] password_file`. If the file already has `[[target]]`
entries, setup asks only for printer, web page and autostart and leaves the
targets alone. Setup also starts by itself when the program is started
without any argument in a console and no config file exists yet; non-interactive
starts (Docker, services) never ask anything.

Check the config file without starting the service (see
[Checking the file](#checking-the-file)):

```sh
PYTHONPATH=src python3 -m pushscan2folder check
```

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
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 scan --folder ./scans
```

## Options

Global options go before the subcommand. The command line wins over the
environment, and the environment wins over the
[configuration file](#configuration-file). More in [Precedence](#precedence).
Scan settings such as format, resolution, colour and source are not options.
The panel and the config file decide them, see
[What the panel decides](#what-the-panel-decides).

| Option         | Env var            | Default             | Applies to    | Description |
|----------------|--------------------|---------------------|---------------|-------------|
| `--config`     | `PUSHSCAN_CONFIG`     | `~/.config/pushscan2folder/config.toml` if present | all | TOML configuration file, see [Configuration file](#configuration-file) |
| `--printer`    | `PUSHSCAN_PRINTER`    | (required)          | all           | Printer IP or host name |
| `--name`       | `PUSHSCAN_NAME`       | `USER  HOSTNAME`    | all           | Name shown on the panel, see [Panel names](#panel-names). Used when the config file has no `[[target]]`. The default replaces characters the panel cannot show with `-` |
| `-v/--verbose` | `PUSHSCAN_VERBOSE`    | off                 | all           | Debug logging. The env var enables it with `1`, `true` or `yes` |
| `--folder`     | `PUSHSCAN_FOLDER`     | `folder` of the file, else `./scans` | run, start, scan | Base folder of all targets (created if missing) |
| `--heartbeat-file` | `PUSHSCAN_HEARTBEAT_FILE` | -          | run, start, health | File that `run` touches after every successful contact with the printer, and that `health` checks. The Docker image sets it, see [Docker](docker.md#healthcheck) |
| `--max-age`    | -                  | `120`               | health        | Seconds after which `health` calls the heartbeat file too old |
| `--no-pause`   | `PUSHSCAN_NO_PAUSE`   | off                 | all           | Windows: never wait for Enter before a console window opened for this program closes. The autostart entry sets it |
| `--web`        | `PUSHSCAN_WEB`        | off                 | run, start    | Serve the [web page](web.md). Env var: `1`, `true` or `yes` |
| `--web-port`   | `PUSHSCAN_WEB_PORT`   | `8737`              | run, start    | Port of the web page |
| `--web-bind`   | `PUSHSCAN_WEB_BIND`   | see `[web]` `bind`  | run, start    | Address of the web page |
| -              | `PUSHSCAN_WEB_PASSWORD` / `PUSHSCAN_WEB_PASSWORD_FILE` | (required with `--web` unless the bind address is loopback) | run | Web password (min. 8 characters), or a file containing it. Env, or `[web] password_file` of the config file. Never the password itself in the config file |
| `--keep`       | -                  | off                 | probe         | Do not release the session |

The `scan` subcommand (one scan over eSCL without the panel) has its own
options `--folder`, `--format` (`pdf` or `jpeg`, default `pdf`), `--color`
(`color` or `gray`, default `color`), `--resolution` (default 300) and
`--source` (`auto`, `platen` or `adf`, default `auto`). It does not use the
config file settings for these.

## Configuration file

Instead of a long command line you keep the settings in a TOML file
(this needs Python 3.11 for `tomllib`). See [config.example.toml](../config.example.toml)
for a commented example. Every key is optional.

Location: `--config PATH` / `PUSHSCAN_CONFIG`; without it
`$XDG_CONFIG_HOME/pushscan2folder/config.toml` (default
`~/.config/pushscan2folder/config.toml`) is used if it exists. A path given
explicitly must exist, otherwise the program exits with an error.

Unknown keys, wrong types and invalid values are rejected with a message naming
the file and the key, so typos are caught. Keys of earlier versions are not
read any more, see the [changelog](../CHANGELOG.md) for the renames.

A small file with two targets:

```toml
printer = "192.168.1.50"
folder = "/scans"

[[target]]
name = "Scans"

[[target]]
name = "Paperless"
next_page = ["document", "auto"]
```

Tables written in braces, such as `auto = { ... }` and `trim = { ... }`, must
stay on one line. TOML does not allow a line break inside them.

## What the panel decides

The printer panel sends its choices with every scan request, and the tool
follows them:

- The colour is the start button you press (colour or black and white).
- The source is the document feeder when paper is in it, else the glass.
- For the document types *Document* and *Photo* the panel also sends size,
  format and resolution.

So the config file has no keys for colour, source, size, format or resolution
of these two types. It decides what the panel does not send:

- the folders, the file names and whether a finished file is opened,
- which document types get the [next page dialog](#next-page-dialog), on the
  glass and, if you want it, after the feeder,
- the settings of the document type *Auto*, where the panel sends no size,
  format or resolution ([Document type Auto](#document-type-auto)),
- the border trim ([Trimming a border](#trimming-a-border)).

## Keys

Top level:

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `printer` | text | none (required, here or by `--printer`) | printer IP or host name |
| `folder` | text | `./scans`, on Windows and macOS `Documents/Scans` | base folder; relative target folders resolve against it, see [Folders](#folders) |
| `filename` | text | `scan_{now:%Y%m%d_%H%M%S}` | template of the file name without extension, see [File names](#file-names) |
| `next_page` | list of `"document"`, `"auto"`, `"photo"` | `["document"]` | document types that get the next page dialog on the glass, see [Next page dialog](#next-page-dialog). `[]` means none |
| `feeder_next_page` | list of `"document"`, `"auto"`, `"photo"` | `[]` | document types that get the next page dialog after a scan from the document feeder, see [Next page dialog after the feeder](#next-page-dialog-after-the-feeder). `[]` means none |
| `auto` | inline table | `{ resolution = 300, format = "pdf", size = "a4" }` | settings for the document type *Auto*, see [Document type Auto](#document-type-auto) |
| `open_after_scan` | `true` / `false` | `false` | desktop PC only: after a job is saved, open the folder (Windows: Explorer with the new file selected), once per job. On Linux it needs `DISPLAY` or `WAYLAND_DISPLAY`. A failure only logs a warning. Docker has no desktop, keep it `false` (else one warning at the start of the first job) |

`[advanced]`, rarely needed:

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `interval` | number | `4` | seconds between polls |
| `verbose` | `true` / `false` | `false` | debug log, needs a restart |
| `trim` | inline table | none | border to cut off glass scans, keys `left`, `top`, `right`, `bottom`, mm, 0 to 50, see [Trimming a border](#trimming-a-border) |
| `adf_trim` | inline table | none | the same for scans from the document feeder |

`[web]`, see [Web page](web.md):

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `enabled` | `true` / `false` | `false` | serve the web page |
| `bind` | text | `0.0.0.0` when a password is set, else `127.0.0.1` (this PC only) | address of the web page. On a loopback address (`127.0.0.1`, `::1`, `localhost`) no password is needed |
| `port` | 1 to 65535 | `8737` | port of the web page |
| `password_file` | text | none | file holding the password, relative to the config file. The password itself is never a key |

`[[target]]`, one block per entry on the printer panel:

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `name` | text | required | name on the panel, max 31 characters, unique, see [Panel names](#panel-names) |
| `folder` | text | the name of the target | folder of the scans; `"."` is the base folder itself. Date fields are allowed, see [Folders](#folders) |
| `document_folder`, `auto_folder`, `photo_folder` | text | `folder` | another folder for scans of one document type |
| `filename` | text | top level `filename` | file name template for this target |
| `next_page` | list | top level `next_page` | replaces the global list for this target |
| `feeder_next_page` | list | top level `feeder_next_page` | replaces the global list for this target |
| `auto` | inline table | top level `auto` | keys set here win over the global `auto`, the others stay |
| `open_after_scan` | `true` / `false` | top level value | for this target, for example `false` for an archive folder |

## Next page dialog

For scans on the glass the printer can show a dialog after every page:
*Stop*, *Black and white*, *Colour* and *Finish*. Put the next page on the
glass and press *Colour* or *Black and white* to scan it (each page can have
its own colour mode), or press *Finish* to end. All pages are saved as one PDF
(with format JPEG: one file per page).

This uses Canon's own scanner protocol (`/canon/ij/command2/port3`) instead of
eSCL, because only that protocol has the "next page" question. The printer
delivers each page as a JPEG; the PDF embeds the JPEGs unchanged.

`next_page` lists the document types that get the dialog. The default is
`["document"]`, like the official software. A target can set its own list, and
`next_page = []` turns the dialog off.

```toml
next_page = ["document", "auto"]       # also ask with Auto
```

By default the feeder scans all pages in one go and uses eSCL without a dialog.
See the next section for an optional dialog after the feeder.

For *Photo* the dialog is only shown for fixed photo sizes. With the sizes
*auto scan* and *auto multi scan* the printer sends the whole glass and the
photos are cut out on the PC instead (see [Photos](#photos)), so `"photo"` in
the list has no effect for these two sizes.

Verified with A4 at 300 dpi; other resolutions and sizes use the same
parameters but have not been tested yet. With *Auto* the panel sends no
resolution or format, so the `auto` settings are used. The printer may reset the
document type to *Auto* after a scan, so check it before the next multi-page
scan.

### Next page dialog after the feeder

The feeder sometimes pulls two sheets at once. With `feeder_next_page` the
panel shows the same dialog after the feeder was scanned, so you can check the
page count and feed a sheet again before the file is saved. The key has the
same form as `next_page`: a list of document types out of `"document"`,
`"auto"` and `"photo"`. The default is `[]` (off). A target's list replaces the
global one.

```toml
feeder_next_page = ["document"]
```

If paper is in the feeder and the document type is in the list, the program
scans the feeder via eSCL and then shows the dialog. To scan more sheets, put
them into the feeder first and then press *Colour* or *Black and white*. The
feeder is scanned again in that colour. *Finish* ends the job. All pages end up
in one PDF (format PDF) or as single JPEG files.

The printer only shows the dialog after a page was scanned with Canon's native
protocol. So before each dialog the program scans a tiny dummy area (1 x 1 inch
at 150 dpi) from the glass and throws it away. This adds about 10 seconds per
round, and the scan head moves briefly. It does not matter what is on the
glass.

If the feeder is empty when you choose more, the program logs a warning and
asks again. After 3 rounds in a row without a page it finishes. The pages
scanned so far are always kept.

### Photos

With the document type *Photo* the panel offers the sizes *auto scan* and
*auto multi scan*. The printer always sends the whole glass, and
pushscan2folder cuts the photos out on the PC:

- *Auto scan* saves one file with the area of the photo or photos.
- *Auto multi scan* saves one file per photo, ordered from top to bottom and
  then from left to right.

This works with the lid open or closed and only on the glass (not the ADF).
Tilted photos stay tilted, because the cut is a bounding box without
straightening. With the panel format PDF the tool scans JPEG, cuts out the
photos and writes one PDF per photo.

Cutting out needs the optional Python package Pillow. The Windows exe and the
Docker image include it. When you run from source, install it with
`pip install -r requirements.txt`. Without Pillow everything works as before and
the whole glass is saved; the log then says "install Pillow to cut the photos
out of the scan".

## Folders

`folder` at the top level is the base folder. Each `[[target]]` saves below it:

- Without `folder` the target saves into a subfolder named after it. Characters
  other than letters, digits, `.`, `_` and `-` become `_`.
- A relative `folder` is resolved against the base folder, an absolute one is
  used as is, and `"."` means the base folder itself.
- `document_folder`, `auto_folder` and `photo_folder` give one document type
  another folder, with the same rules. Without them the type uses `folder`.

```toml
folder = "/scans"

[[target]]
name = "Paperless"                # /scans/Paperless
photo_folder = "Photos"           # photos go to /scans/Photos

[[target]]
name = "Archive"
folder = "Archive/{now:%Y}"       # /scans/Archive/2026
```

Two targets may not share a folder (`a b` and `a_b` both map to `a_b`, for
example). The Docker image sets `PUSHSCAN_FOLDER=/scans`, see
[Precedence](#precedence).

## Date fields in folders

The folders of a target (`folder` and the three type folders) may contain the
same fields as [file names](#file-names): `{name}` (the target name),
`{date}` (`2026-11-22`), `{time}` (`183005`) and `{now:FORMAT}` with Python
`strftime` codes. The fields are filled in when a scan is saved, so the folder
can change by year or month without editing the file.

```toml
folder = "Archive/{now:%Y}/{now:%m}"    # Archive/2026/11
```

The value of one field is always a single folder name part. A field never
adds a path separator or `..`: a format such as `{now:%d/%m}` gives `03_11`,
not two folders. The slashes you type between the fields are the only way to
make subfolders. A wrong field, such as `{now.year}` or `{}`, is rejected when the
file is read.

## Document type Auto

With the panel document type *Auto* the panel sends only type, colour and
source. The `auto` table decides the rest:

```toml
auto = { resolution = 300, format = "pdf", size = "a4" }
```

| Key | Values | Default |
|-----|--------|---------|
| `resolution` | `75`, `150`, `300`, `600` | `300` |
| `format` | `"pdf"`, `"jpeg"` | `"pdf"` |
| `size` | `"a4"`, `"letter"`, `"legal"`, `"10x15"`, `"13x18"` | `"a4"` |

You may set only some keys. A `[[target]]` can have its own `auto`; its keys win
over the global table and the others stay, so `auto = { format = "jpeg" }` in
a target keeps the global resolution and size.

## Trimming a border

Some scanners capture a thin border at the glass edge. On a TR8550, tests
showed that 1 mm on the right and 2 mm at the bottom remove it. With the
`trim` table in `[advanced]` the tool asks the printer for a smaller scan
area, so the border is never scanned. No image processing is involved.

```toml
[advanced]
trim = { right = 1, bottom = 2 }     # glass
adf_trim = { }                       # document feeder, 0 by default
```

The keys are `left`, `top`, `right` and `bottom`, in mm from 0 to 50. Sides
that are not named stay 0. `trim` applies to the glass only. Scans from the
document feeder have their own table `adf_trim`, 0 by default. The TR8550
honours the smaller area on the feeder. The feeder sometimes pulls a page in
slightly skewed, so a trim there can cut off a little of the page; leave it
empty unless the border bothers you. If less than 1 inch would remain in
either direction, trimming is skipped and a warning is logged. The setting is
global, not per target.

## Checking the file

`pushscan2folder check` reads the config file like `run` does, reports an error
with the key that is wrong, or shows what the file does: base folder, file
names, the settings for *Auto*, the trim, and for each target its folders with
today's date filled in. It does not contact the printer. Run it after editing
the file. The output for [config.example.toml](../config.example.toml):

```
$ pushscan2folder --config config.example.toml check
config file: config.example.toml
printer: 192.168.1.50
base folder: /scans
file names: scan_{now:%Y-%m-%d_%H-%M-%S}
next page dialog: document
next page dialog after the feeder: none
document type Auto: 300 dpi, pdf, a4
trim: glass right 1 mm, bottom 2 mm; feeder none
open after scan: no
poll interval: 4 s
target 'Scans':
  folder: /scans/Scans
target 'Paperless':
  folder: /scans/Paperless
  photo scans: /scans/Photos
  next page dialog: document, auto
target 'Archive':
  folder: /scans/Archive/2026
  next page dialog: none
  next page dialog after the feeder: document
  document type Auto: 600 dpi, jpeg, a4
OK
```

The exit code is 0 if the file can be used and 2 otherwise, also when no printer
is set.

## Precedence

Command line > environment variable > config file > built-in default.

Of the keys in the file, only `printer` and `folder` can be overridden this way
(by `--printer` / `PUSHSCAN_PRINTER` and `--folder` / `PUSHSCAN_FOLDER`), plus
the web options of `[web]` and `verbose`. Everything else is set in the file
only.

- The Docker image sets `PUSHSCAN_FOLDER=/scans`, so in the container the
  file's `folder` key is overridden. Mount your folders below `/scans` or use
  absolute target folders (see [Docker](docker.md)).
- The panel settings come first for the scan itself, the `auto` table only
  fills in for the document type *Auto*, see
  [Panel settings](#panel-settings).

## Changing the file while running

Before each poll cycle, never during a scan, `run` checks the modification
time and size of the config file. If it changed, the file is read again like at
startup. The command line options and the `PUSHSCAN_FOLDER` and
`PUSHSCAN_PRINTER` variables still win over the file. This also applies to
changes made on the [web page](web.md).

These are applied right away: `folder`, `filename`, `next_page`, `feeder_next_page`, `auto`,
`open_after_scan`, `interval`, `trim` and `adf_trim`, the targets and
`printer`. Targets whose names stay keep their registration on the panel. If the
printer changes, the names are released on the old printer and registered on the
new one.

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
Only for the document type *Auto* the [`auto` table](#document-type-auto)
supplies size, format and resolution.

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

## ADF

The printer detects the source with its paper sensor; the panel has no source
choice. Legal size is only available from the ADF. The ADF is simplex only.
The tool uses the feeder when paper is loaded in it and the glass otherwise.

## Multiple targets

One instance can register several names with the printer. Each name shows up as
its own computer on the panel, and its scans go to a separate folder. You
define them as `[[target]]` blocks in the config file (or on the
[web page](web.md)):

```toml
folder = "/scans"

[[target]]
name = "Scans"

[[target]]
name = "Paperless"
folder = "consume"

[[target]]
name = "Archive"
folder = "/data/archive"
```

See [Folders](#folders) for how the folders resolve. Names must be unique and
follow the [panel name rules](#panel-names). All names share one poll loop, so
the poll interval applies to the whole list. Without any `[[target]]` the tool
registers one name, `--name` or `USER  HOSTNAME`, and saves into the base
folder.

For paperless-ngx, mount its consume folder inside the base folder, for
example `- /path/to/paperless/consume:/scans/Paperless` in Docker (see
[Docker](docker.md#paperless-ngx)), and use a target named `Paperless`. A
folder inside the base folder can also be chosen on the
[web page](web.md); an absolute one like `/consume` works too, but only in the
config file.

## Panel names

Observed on the TR8550:

- Only A-Z, a-z, 0-9, space, `-`, `_` and `@` are shown. The printer
  accepts other characters (`.`, `&`, umlauts, accents, emoji, ...) but shows
  them as blanks, so pushscan2folder rejects names containing them.
- Names have at most 31 characters. The panel shows about 25 and then `...`
  (a warning is logged for longer names).
- 20 names at the same time worked (a scrollable list), and no limit was found.
- The list is ordered by registration time, not alphabetically.

## File names

The template for the name of a scan file is set with `filename` at the top
level of the config file. A `filename` in a `[[target]]` applies to that target
only and wins over the global one. On the
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
