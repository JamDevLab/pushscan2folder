# Troubleshooting and limitations

English | [Deutsch](troubleshooting.de.md)

Back to the [README](../README.md).

## Reporting a problem

Run the tool with `--verbose` (or `PUSHSCAN_VERBOSE=1`) and attach the log to
the issue. Remove IP addresses and names first if you want. The issue forms on
GitHub ask for the details. To report a new printer model, see
[CONTRIBUTING.md](../CONTRIBUTING.md).

## Limitations

- Only tested with a Canon PIXMA TR8550. Other IJ models may or may not work.
- The panel settings "reduce bleed-through", "descreen" and "unsharp mask" are
  read but not applied yet. eSCL has no equivalent, and the official software
  probably applies them on the PC. Applying them would need image processing on
  your computer and may be added later, for example as an optional extra.
- Protocol details and open questions are in [PROTOCOL.md](PROTOCOL.md).
- Panel names: 31 characters, about 25 visible, ASCII letters, digits, space,
  `-`, `_`, `@` only. See [Panel names](configuration.md#panel-names).
- The tool contacts only the printer. Discovery is not implemented, so you must
  give the printer address.

## Known behaviour

- TIFF is not supported. Such scans are saved as JPEG. "Compact PDF" is
  scanned as a normal PDF at 300 dpi.
- Size "Auto" scans the full platen width at A4 height (no auto-crop).
- Cancelling a scan on the panel leaves a truncated document. The tool
  detects this and discards it, so nothing is saved.
- The printer may reset the document type to *Auto scan* after a scan, so
  check it before the next multi-page scan.
- Multi-page scans are verified with A4 at 300 dpi. Other resolutions and
  sizes use the same parameters but have not been tested yet.
- The border trim values for the TR8550 (3 mm right, 2 mm bottom) are still
  to be verified.
- Selecting a name on the panel without starting a scan triggers nothing.
- The printer drops a registration after roughly 60 s without polls. The tool
  polls every 5 s during long scans and registers again automatically, see
  [How it works](how-it-works.md#registration-and-long-scans).
- After a change of the target order on the web page, the names briefly
  disappear from the panel while they are registered again.

## Common problems

- The name does not show up on the panel: names with characters other than
  letters, digits, space, `-`, `_` and `@` are rejected, see
  [Panel names](configuration.md#panel-names). After a printer restart the
  names reappear within about 10 s.
- A preset has no colour: the colour always comes from the panel, see
  [Presets per target](configuration.md#presets-per-target).
- The multi-page dialog does not appear: it is only shown for platen scans,
  by default only for document type *Document*, and not with `--ignore-panel`.
  See [Multi-page scans](configuration.md#multi-page-scans-from-the-platen).
- Scans cannot be written in Docker: the output directory must be writable
  for the container user, see [User, uid and gid](docker.md#user-uid-and-gid).
- The web page refuses to start: see [Password options](web.md#password-options).
  Forms refused with "Origin does not match Host" behind a reverse proxy: see
  [HTTPS](web.md#https-behind-a-reverse-proxy).
- The targets cannot be edited on the web page: editing is disabled when they
  come from `PUSHSCAN_TARGETS` / `--targets`, see
  [Editing targets and folders](web.md#editing-targets-and-folders).
