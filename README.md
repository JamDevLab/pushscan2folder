<p align="center">
  <img src="src/pushscan2folder/favicon.svg" width="96" alt="pushscan2folder icon">
</p>

<h1 align="center">pushscan2folder</h1>

<p align="center">Use a Linux machine, a Docker container or a Windows PC as a "scan to PC" destination for Canon IJ printers.</p>

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

## Supported printers

Tested models:

| Model                    | Verified features                               | Status |
|--------------------------|-------------------------------------------------|--------|
| Canon PIXMA TR8550 (TR8500 series) | push scan, multi target, ADF, panel settings, multi-page platen | ok     |

Other Canon IJ models may or may not work. To report another model, see
[CONTRIBUTING.md](CONTRIBUTING.md). Known limits are in
[Troubleshooting](docs/troubleshooting.md#limitations).

## Quick start

With Docker Compose. The image is published on the GitHub Container Registry
(`ghcr.io/jamdevlab/pushscan2folder`, for amd64 and arm64), so you need no
clone:

```sh
mkdir pushscan2folder && cd pushscan2folder
mkdir -p scans config
curl -fsSLO https://raw.githubusercontent.com/JamDevLab/pushscan2folder/main/docker-compose.yml
curl -fsSL -o config/config.toml https://raw.githubusercontent.com/JamDevLab/pushscan2folder/main/config.example.toml
# set PUSHSCAN_PRINTER (and user:) in docker-compose.yml
docker compose up -d
docker compose logs -f
```

Set the targets in `config/config.toml`. To update, run
`docker compose pull && docker compose up -d`. To build the image yourself,
see [Docker](docs/docker.md#build-it-yourself).

The `docker-compose.yml` looks like this. It is shown here so you can see what
to change:

```yaml
services:
  pushscan2folder:
    image: ghcr.io/jamdevlab/pushscan2folder:latest   # or a fixed version, e.g. :0.2.0
    # build: .                           # instead of image: build it from a clone
    restart: unless-stopped
    user: "1000:1000"                    # owner of ./scans and ./config (id -u, id -g)
    environment:
      PUSHSCAN_PRINTER: 192.168.1.50     # printer IP or host name
      PUSHSCAN_CONFIG: /config/config.toml
      # PUSHSCAN_WEB: "1"                # web page
      # PUSHSCAN_WEB_PASSWORD: change-me-please   # your own, at least 8 characters
    volumes:
      - ./scans:/scans
      - ./config:/config
      # - /path/to/paperless/consume:/scans/Paperless  # paperless-ngx
    # ports:
    #   - "8080:8080"                    # web page
```

The web page is off by default. To turn it on, uncomment the web lines
(`PUSHSCAN_WEB`, your own `PUSHSCAN_WEB_PASSWORD` and the port) and open
port 8080. More in [Docker](docs/docker.md) and [Web page](docs/web.md).

On plain Linux:

```sh
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 run --output ./scans
```

Then choose the host on the printer panel (scan to PC) and start the scan.

## Configuration

Settings come from command line options, environment variables (`PUSHSCAN_*`)
or a TOML file ([config.example.toml](config.example.toml)). The command line
wins over the environment, and the environment wins over the file. The
printer address is the only required setting.

A minimal file with two targets:

```toml
printer = "192.168.1.50"

[[target]]
name = "Scans"

[[target]]
name = "Paperless"
output = "consume"
```

The full option table, targets and presets, trimming, multi-page scans and
panel settings are in [docs/configuration.md](docs/configuration.md).

## Web page

An optional page for the LAN or a NAS shows the status, the last scans and the
log, and edits targets and settings. It is off by default and protected by a
password. It works without JavaScript; a small script updates status and log
in place and warns about unsaved changes. Details, the security model and
HTTPS are in [docs/web.md](docs/web.md).

## Windows and macOS

Windows is covered in [docs/windows.md](docs/windows.md)
([Deutsch](docs/windows.de.md)). macOS has not been tested; the plain Linux
instructions above are the closest match.

## More documentation

- [Configuration](docs/configuration.md): options, config file, targets, presets, trim, multi-page
- [Web page](docs/web.md): pages, passwords, security, HTTPS
- [Docker](docs/docker.md): compose, user, volumes, paperless-ngx, NAS
- [Troubleshooting](docs/troubleshooting.md): limitations and common problems
- [How it works](docs/how-it-works.md): registration, polling, protocol summary
- [PROTOCOL.md](docs/PROTOCOL.md): interrupt bytes and open questions

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
