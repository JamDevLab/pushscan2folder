# CLAUDE.md

Notes for Claude Code (and other coding agents) working in this repository.
Read [CONTRIBUTING.md](CONTRIBUTING.md) first; everything there applies.

## Project

pushscan2folder starts scans from the panel of a Canon PIXMA TR8550/TR8500
and saves them to folders on a PC, NAS or Docker host. It polls the printer
over HTTP (Canon's own push-scan protocol plus eSCL) and needs no Canon
software. License: AGPL-3.0.

## Layout

- `src/pushscan2folder/`: the package.
  - `__main__.py`: command line, subcommands, the Windows menu.
  - `service.py`: poll loop, panel request to scan settings to files.
  - `protocol.py`, `client.py`, `native.py`, `escl.py`: printer protocols.
  - `panel.py`: decoding the panel bytes (document type, size, format, ...).
  - `crop.py`: cutting photos out of a glass scan (needs Pillow).
  - `pdf.py`: writing PDFs from JPEGs, no dependency.
  - `config.py`: TOML config, environment variables, live reload.
  - `web.py`: the optional web page (standard library HTTP server);
    `status.py`: thread-safe state it reads.
  - `wizard.py`: interactive `setup`; `discovery.py`: mDNS printer search
    (never test it against a real network).
  - `background.py`, `autostart.py`, `desktop.py`, `platform_support.py`,
    `uninstall.py`, `terminal.py`: desktop integration.
- `tests/`: unittest; `tests/support.py` and the fake printer in
  `tests/test_service.py` stand in for real hardware.
- `docs/`: user docs, English plus a German `*.de.md` copy of each page;
  `docs/PROTOCOL.md` describes the printer protocol.
- `packaging/`: PyInstaller entry point and the Inno Setup installer script.
- `.github/workflows/`: tests (Linux and Windows on Python 3.11 and 3.13, plus 3.12 and 3.15 on Linux, macOS on 3.13 only),
  Docker image, Windows release build.

## Commands

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m unittest tests.test_panel
PYTHONPATH=src python3 -m pushscan2folder -v --printer <ip> run
```

Run the whole suite before you call a change done. It must pass with and
without Pillow installed (tests that need Pillow skip themselves).

## Rules

- Standard library only. Pillow is the one optional dependency
  (`requirements.txt`); code must check `crop.available()` and fall back to
  saving the whole scan. Do not add other dependencies.
- Tests never touch the network or a real printer, and never bind the real
  web port (8737); use port 0 and the fake printer.
- Never contact devices on the LAN without the user asking; the printer is
  only reached when the user runs the tool against it.
- Clean room: no Canon binaries, disassembly, decompiled code or addresses in
  the repository, issues or PRs. Protocol observations (hex dumps of your own
  traffic) are fine.
- Never commit `private/` (local reverse engineering material and logs),
  `.claude/`, `scans/` or build output. No passwords or tokens in any file;
  the web password comes only from an environment variable or a file.
- Code, comments, commit messages and docs in English. Small commits with
  clear messages. No AI `Co-Authored-By` trailers; the README credits the AI
  help instead.
- Core logic changes need a test.

## Docs

- When behaviour changes, update the matching page in `docs/` and the
  README, and keep the German `*.de.md` pages in sync with the English ones.
- Add an entry under `## [Unreleased]` in `CHANGELOG.md`.
- Style: plain sentences, no em or en dashes, no bold labels at the start of
  list items, no "not X but Y" phrasing.

## Releases

- Work happens on `next`; `main` gets it through a pull request.
- A push to `next` builds the Windows program as a workflow artifact.
- A `v*` tag publishes the GitHub release (installer) and the Docker image
  `ghcr.io/jamdevlab/pushscan2folder`.
- The version lives in `src/pushscan2folder/__init__.py`; version examples
  also appear in the README, `docs/docker*.md`, `docker-compose.yml`,
  `packaging/pushscan2folder.iss` and the bug report template.
- Pushing, merging, tagging and releasing need the maintainer's explicit go.

## Status and open points

- Released: 0.3.0 (2026-11-23). `## [Unreleased]` in `CHANGELOG.md` lists
  what is on `next` since then.
- Tested by hand only with a TR8550: Windows (installer, menu, background
  mode) and Docker on Linux. macOS runs only in CI.
- Open protocol questions (some panel bytes, size codes 4 to 7 and 0x0a):
  "Open questions" in `docs/PROTOCOL.md`. Unknown panel values are logged
  as a warning.
- Known limits: the native multi-page protocol is used for the platen only;
  photo cut-out works on the eSCL path for the platen only and does not
  straighten tilted photos; the feeder trim is 0 by default because the
  feeder sometimes pulls pages in skewed.
- Postponed by the maintainer, do not start unasked: code signing of the
  Windows installer, a tray icon and a configuration window.

## Testing against the real printer

Only when the maintainer asks, and only the printer they name. A private
config (not in git) lives in `private/config.toml`; run it in the
foreground or background with
`PYTHONPATH=src .venv/bin/python -m pushscan2folder --config private/config.toml run`
and redirect the log below `private/` (scans go to the gitignored `scans/`). Never test the mDNS search
against the real network, and never contact other devices.
