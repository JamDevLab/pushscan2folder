# Docker

English | [Deutsch](docker.de.md)

Back to the [README](../README.md).

From version 0.2.0 on, a published image is built on each release:
`ghcr.io/jamdevlab/pushscan2folder`, for linux/amd64 and linux/arm64 (for
example a Raspberry Pi). The tags are the exact version (`0.2.0`), major.minor
(`0.2`) and `latest`. You do not need a clone.

## Docker Compose

The provided `docker-compose.yml` keeps the targets and scan settings in
`config/config.toml`; only the printer IP and the (commented out) web settings
are in the compose file:

```sh
mkdir pushscan2folder && cd pushscan2folder
mkdir -p scans config
curl -fsSLO https://raw.githubusercontent.com/JamDevLab/pushscan2folder/main/docker-compose.yml
curl -fsSL -o config/config.toml https://raw.githubusercontent.com/JamDevLab/pushscan2folder/main/config.example.toml
# set PUSHSCAN_PRINTER (and user:) in docker-compose.yml (and the web lines if wanted)
docker compose up -d
docker compose logs -f
```

To update, run `docker compose pull && docker compose up -d`. Use `:latest` or
pin a version, for example `:0.2.0`.

The file looks like this (the web lines are commented out, so the web page is
off by default):

```yaml
services:
  pushscan2folder:
    image: ghcr.io/jamdevlab/pushscan2folder:latest   # or a fixed version, e.g. :0.2.0
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

The program refuses to start with the example password `change-me-please`.
Every option can also be set as an environment variable (see
[Configuration](configuration.md#options)), which then wins over the config
file.

## Plain docker

```sh
mkdir -p scans
docker run -d --name pushscan2folder --restart unless-stopped \
  --user "$(id -u):$(id -g)" \
  -e PUSHSCAN_PRINTER=192.168.1.50 -e PUSHSCAN_NAME=docker-scan \
  -v "$PWD/scans:/scans" ghcr.io/jamdevlab/pushscan2folder:latest
```

## Build it yourself

Clone the repository and use `docker-compose.dev.yml`. It builds the image
from the clone, turns on the debug log and does not restart by itself. It
uses the same `scans` and `config` folders as `docker-compose.yml`, so stop
the other one first, or both register the same panel names:

```sh
docker compose down
docker compose -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.dev.yml logs -f
```

For plain docker, build a local image and use `pushscan2folder` instead of the
published image name in the `docker run` command above:

```sh
docker build -t pushscan2folder .
```

## User, uid and gid

The image runs as a non-root user. The output directory must be writable by
that user. Either pass `--user "$(id -u):$(id -g)"` (as above, or `user:` in
compose) so files belong to you, or `chown` the host directory to the
container user's UID (check with
`docker run --rm --entrypoint id ghcr.io/jamdevlab/pushscan2folder:latest`).

## Volumes

- `./scans:/scans` is the output directory. The image sets
  `PUSHSCAN_OUTPUT=/scans`, which overrides the `output` key of the config
  file (see [Precedence](configuration.md#precedence)). Mount your folders
  below `/scans` or use absolute target outputs.
- `./config:/config` holds `config.toml`. Mount a directory, not a single
  file: a single-file bind mount cannot be replaced atomically, so the program
  would fall back to rewriting it in place when the [web page](web.md) saves.
  The directory must be writable for the user set in `user:`.

## Network

Scanning needs no port mapping; the container only connects out to the
printer on TCP 80. Port 8080 is only for the [web page](web.md). Docker's
default bridge networking works.

## Paperless-ngx

Mount the paperless consume folder inside the output directory and use a
target named like the folder, for example `Paperless@300dpi`:

```yaml
    volumes:
      - /path/to/paperless/consume:/scans/Paperless
```

The folder can also be chosen on the web page, because it lies inside the
output directory. An absolute target folder like `Paperless=/consume` only
works from the command line or the config file. See
[Presets per target](configuration.md#presets-per-target).

## NAS notes

- Pick the uid and gid of the NAS user that should own the scans for `user:`.
- Reach the web page by its own host name if other web services run on the
  same NAS (browsers send cookies to every service on the same host,
  regardless of the port), see [Security model](web.md#security-model).
- Prefer `PUSHSCAN_WEB_PASSWORD_FILE` (a Docker secret) over the plain
  variable, because environment variables are visible in `docker inspect`.
- Do not set `PUSHSCAN_TARGETS` when you edit the targets on the web page.
