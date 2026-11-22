# Web page

English | [Deutsch](web.de.md)

Back to the [README](../README.md).

- [Overview](#overview)
- [Enabling it](#enabling-it)
- [Password options](#password-options)
- [Pages](#pages)
- [Editing targets and folders](#editing-targets-and-folders)
- [Security model](#security-model)
- [HTTPS behind a reverse proxy](#https-behind-a-reverse-proxy)
- [Docker](#docker)

## Overview

A small web page for local use (LAN, NAS) with the current status, recent
scans, the log, an editor for the targets, a settings form and a raw editor
for the config file. It is off by default and needs no extra packages. It
works without JavaScript. One small script (`/app.js`, served by the program
itself, no inline scripts) updates the status and log pages in place without
a visible reload, warns about unsaved changes on the edit pages and lets the
Tab key insert two spaces in the raw editor. Without JavaScript the status and
log pages simply reload every 10 s.

In the provided `docker-compose.yml` the web lines are commented out, so the
page is off there too until you uncomment them.

## Enabling it

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
| `[web] password_file` | config file key, same as above; used if both variables are unset. Relative paths are relative to the config file |
| `PUSHSCAN_WEB_SECURE_COOKIE=1` | only behind an HTTPS reverse proxy: `Secure` cookie, see [HTTPS](#https-behind-a-reverse-proxy) |
| `PUSHSCAN_WEB_PASSWORD_CHECK=0` | skip the password rules, see [Password options](#password-options) |
| `PUSHSCAN_WEB_AUTH=0` | no login at all, see [Password options](#password-options) |

The config file can hold a `[web]` table with `enabled`, `bind`, `port` and
`password_file` (see [Configuration](configuration.md)); `pushscan2folder setup`
writes it and stores the password in `web_password.txt` next to the config file.
The command line and the environment win over the table. The Settings page shows
the table read-only: the login cannot be changed from the web page.

Without a valid password the program refuses to start (exit code 2). It never
reads the password itself from the config file and never logs or shows it.

## Password options

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

## Pages

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
  `size`, `open_after_scan` and the four `trim_*` values of `[defaults]`, and `multipage`,
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

## Editing targets and folders

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

The raw editor also refuses changes to `output`, `printer` and the `[web]`
table. `[web]` decides who can reach the page and where the password is, so it
can only be changed in the file itself or with `pushscan2folder setup`.

## Security model

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
  themselves, a stylesheet, the icon and the small script are served; the web
  page cannot read or download files.
- Browsers send cookies to every service on the same host regardless of the
  port, so reach the page by its own host name if other web services run on
  the same NAS.

## HTTPS behind a reverse proxy

Put a TLS reverse proxy (Caddy, nginx, Traefik) in front and set
`PUSHSCAN_WEB_SECURE_COOKIE=1`. The cookie is then called `__Host-p2f_session`
and marked `Secure`, so the page works only through HTTPS. The proxy must pass
on the original `Host` header (nginx: `proxy_set_header Host $host;`),
otherwise forms are refused with "Origin does not match Host". Bind the service
to an internal address (`PUSHSCAN_WEB_BIND`) so it cannot be reached around
the proxy.

## Docker

The provided `docker-compose.yml` is prepared for the web page
(`./config:/config`, `PUSHSCAN_CONFIG: /config/config.toml`); uncomment the
web lines and the port to turn it on. Mount
a directory for the config, not a single file: a single-file bind mount cannot
be replaced atomically, so the program would fall back to rewriting it in
place. The directory must be writable for the user set in `user:`. Do not set
`PUSHSCAN_TARGETS` when you edit the targets on the web page. More in
[Docker](docker.md).
