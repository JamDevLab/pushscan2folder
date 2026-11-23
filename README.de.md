<p align="center">
  <img src="src/pushscan2folder/favicon.svg" width="96" alt="pushscan2folder icon">
</p>

<h1 align="center">pushscan2folder</h1>

<p align="center">Nutze einen Linux-Rechner, einen Docker-Container oder einen Windows-PC als Ziel für "Scannen an PC" bei Canon-IJ-Druckern.</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-1F5FAD" alt="License: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-1F5FAD" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/dependencies-Pillow%20(optional)-1F5FAD" alt="dependencies: Pillow (optional)">
  <img src="https://img.shields.io/badge/docker-ready-2496ED" alt="Docker">
</p>

<p align="center"><a href="README.md">English</a> | Deutsch</p>

`pushscan2folder` meldet sich beim Drucker an, sodass sein Name in der Liste
"Scannen an PC" auf dem Bedienfeld des Druckers erscheint. Wählst du ihn dort
aus, scannt das Tool und speichert das Ergebnis als PDF- oder JPEG-Datei.
Getestet mit einem Canon PIXMA TR8550 (TR8500-Serie).

## Funktionen

- Fügt dem Bedienfeld des Druckers einen Eintrag für "Scannen an PC" hinzu
- Mehrere Ziele, jedes mit eigenem Ordner
- Mehrseitige PDFs vom Vorlagenglas, mit dem Dialog für die nächste Seite am Bedienfeld
- Einstellungen pro Ziel für den Dokumenttyp *Automatisch* und ein Ordner pro Dokumenttyp
- Optionale passwortgeschützte Weboberfläche für Status, Log, Ziele und Einstellungen
- Für Docker und NAS geeignet, nur ausgehende Verbindungen zum Drucker (TCP 80)
- Fotos: Bei der Bedienfeld-Größe "auto scan" oder "auto multi scan" werden die Fotos aus dem Glasscan ausgeschnitten, eine Datei pro Foto (braucht Pillow, optional)
- Python 3.11+, nur Standardbibliothek; das optionale Paket Pillow wird nur zum Ausschneiden von Fotos gebraucht

## Unterstützte Drucker

Getestete Modelle:

| Model                    | Verified features                               | Status |
|--------------------------|-------------------------------------------------|--------|
| Canon PIXMA TR8550 (TR8500 series) | push scan, multi target, ADF, panel settings, multi-page platen | ok     |

Andere Canon-IJ-Modelle funktionieren vielleicht, vielleicht auch nicht. Um ein
anderes Modell zu melden, siehe [CONTRIBUTING.md](CONTRIBUTING.md) (auf
Englisch). Bekannte Grenzen stehen in
[Fehlersuche](docs/troubleshooting.de.md#einschränkungen).

## Schnellstart

Mit Docker Compose. Das Image liegt in der GitHub Container Registry
(`ghcr.io/jamdevlab/pushscan2folder`, für amd64 und arm64), du brauchst also
keinen Klon:

```sh
mkdir pushscan2folder && cd pushscan2folder
mkdir -p scans config
curl -fsSLO https://raw.githubusercontent.com/JamDevLab/pushscan2folder/main/docker-compose.yml
curl -fsSL -o config/config.toml https://raw.githubusercontent.com/JamDevLab/pushscan2folder/main/config.example.toml
# PUSHSCAN_PRINTER (und user:) in docker-compose.yml setzen
docker compose up -d
docker compose logs -f
```

Trage die Ziele in `config/config.toml` ein. Zum Aktualisieren:
`docker compose pull && docker compose up -d`. Um das Image selbst zu bauen,
siehe [Docker](docs/docker.de.md#selbst-bauen).

Die `docker-compose.yml` sieht so aus, damit du siehst, was du ändern musst:

```yaml
services:
  pushscan2folder:
    image: ghcr.io/jamdevlab/pushscan2folder:latest   # or a fixed version, e.g. :0.4.0
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

Die Weboberfläche ist standardmäßig aus. Zum Einschalten die Web-Zeilen
einkommentieren (`PUSHSCAN_WEB`, ein eigenes `PUSHSCAN_WEB_PASSWORD` und den
Port), dann läuft sie auf Port 8080. Mehr in [Docker](docs/docker.de.md) und
[Weboberfläche](docs/web.de.md).

Auf einem normalen Linux-Rechner:

```sh
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 run --folder ./scans
```

Wähle dann den Host am Bedienfeld des Druckers (Scannen an PC) und starte den Scan.

## Konfiguration

Das Bedienfeld des Druckers bestimmt Farbe, Quelle (das Einzugsfach, wenn
Papier darin liegt, sonst das Vorlagenglas) und, bei den Dokumenttypen Dokument
und Foto, Größe, Format und Auflösung. Den Rest legt die TOML-Datei
([config.example.toml](config.example.toml)) fest: Ordner, Dateinamen, welche
Dokumenttypen nach der nächsten Seite fragen, und die Einstellungen für den
Dokumenttyp Auto. Nur die Adresse des Druckers und der Basisordner können auch
über Kommandozeile oder Umgebung kommen (`--printer`, `--folder`,
`PUSHSCAN_PRINTER`, `PUSHSCAN_FOLDER`). Die Adresse des Druckers ist die einzige
erforderliche Einstellung. `pushscan2folder check` zeigt, was eine Datei
bewirkt.

Eine minimale Datei mit zwei Zielen:

```toml
printer = "192.168.1.50"
folder = "/scans"

[[target]]
name = "Scans"

[[target]]
name = "Paperless"
folder = "consume"
```

Die vollständige Schlüsseltabelle, Ordner, der Dialog für die nächste Seite,
Rand abschneiden und Einstellungen vom Bedienfeld stehen in
[docs/configuration.de.md](docs/configuration.de.md).

## Weboberfläche

Eine optionale Seite für das LAN oder ein NAS zeigt Status, letzte Scans und
das Log und bearbeitet Ziele und Einstellungen. Sie ist standardmäßig aus und
durch ein Passwort geschützt. Sie funktioniert ohne JavaScript; ein kleines
Skript aktualisiert Status und Log an Ort und Stelle und warnt vor
ungespeicherten Änderungen. Details, das Sicherheitsmodell und HTTPS stehen in
[docs/web.de.md](docs/web.de.md).

## Windows und macOS

Windows ist in [docs/windows.de.md](docs/windows.de.md) beschrieben
([English](docs/windows.md)). macOS wurde nicht getestet; die Anleitung für
einen normalen Linux-Rechner oben passt am ehesten.

## Weitere Dokumentation

- [Konfiguration](docs/configuration.de.md): Optionen, Konfigurationsdatei, Ziele, Ordner, Rand, Dialog für die nächste Seite
- [Weboberfläche](docs/web.de.md): Seiten, Passwörter, Sicherheit, HTTPS
- [Docker](docs/docker.de.md): Compose, Benutzer, Volumes, paperless-ngx, NAS
- [Fehlersuche](docs/troubleshooting.de.md): Einschränkungen und häufige Probleme
- [So funktioniert es](docs/how-it-works.de.md): Registrierung, Abfrage, Protokollübersicht
- [PROTOCOL.md](docs/PROTOCOL.md): Interrupt-Bytes und offene Fragen (auf Englisch)

## Mitwirken

Tests ausführen:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

Um ein anderes Druckermodell zu melden oder mitzuarbeiten, siehe [CONTRIBUTING.md](CONTRIBUTING.md) (auf Englisch).

## Mit KI entwickelt

Dieses Projekt ist mit Hilfe eines KI-Programmierassistenten (Claude von
Anthropic) entstanden. Der Assistent hat den Großteil von Code, Tests und
Dokumentation geschrieben und bei der Auswertung der Netzwerkmitschnitte
geholfen. Der Maintainer hat die Arbeit gesteuert, die Entscheidungen
getroffen und die Funktionen mit einem echten Drucker getestet.

## Lizenz

pushscan2folder steht unter AGPL-3.0-or-later, siehe [LICENSE](LICENSE).
Die optionale Abhängigkeit [Pillow](https://python-pillow.org/) (MIT-CMU-Lizenz) schneidet Fotos aus und ist in der Windows-exe und im Docker-Image enthalten.
Canon und PIXMA sind Marken von Canon Inc. Dieses Projekt steht in keiner Verbindung zu Canon und wird von Canon weder unterstützt noch empfohlen.

### Rechtlicher Hinweis

Dieses Projekt enthält keinen Canon-Code und keine Canon-Binärdateien und
verbreitet keine. Das CHMP-Push-Scan-Protokoll wurde von Grund auf neu
implementiert, auf Basis einer statischen Analyse des Windows-Tools "IJ Network
Scanner Selector EX2". Das Scanner-Protokoll für mehrseitige Scans beruht auf
der Beobachtung des Netzwerkverkehrs zwischen der offiziellen Software und dem
Drucker. Beides geschah ausschließlich zu Interoperabilitätszwecken.
