# Docker

[English](docker.md) | Deutsch

Zurück zur [README](../README.de.md).

Ab Version 0.2.0 gibt es ein veröffentlichtes Image, das bei jedem Release
gebaut wird: `ghcr.io/jamdevlab/pushscan2folder`, für linux/amd64 und
linux/arm64 (zum Beispiel ein Raspberry Pi). Die Tags sind die genaue Version
(`0.2.0`), Major.Minor (`0.2`) und `latest`. Du brauchst keinen Klon.

## Docker Compose

Die mitgelieferte `docker-compose.yml` hält Ziele und Scan-Einstellungen in
`config/config.toml`; in der Compose-Datei stehen nur die Drucker-IP und die
(auskommentierten) Einstellungen der Weboberfläche:

```sh
mkdir pushscan2folder && cd pushscan2folder
mkdir -p scans config
curl -fsSLO https://raw.githubusercontent.com/JamDevLab/pushscan2folder/main/docker-compose.yml
curl -fsSL -o config/config.toml https://raw.githubusercontent.com/JamDevLab/pushscan2folder/main/config.example.toml
# PUSHSCAN_PRINTER (und user:) in docker-compose.yml setzen (bei Bedarf die Web-Zeilen)
docker compose up -d
docker compose logs -f
```

Zum Aktualisieren: `docker compose pull && docker compose up -d`. Nimm
`:latest` oder lege eine Version fest, zum Beispiel `:0.2.0`.

Die Datei sieht so aus (die Web-Zeilen sind auskommentiert, die Weboberfläche
ist also standardmäßig aus):

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

Mit dem Beispielpasswort `change-me-please` startet das Programm nicht. Jede
Option lässt sich auch als Umgebungsvariable setzen (siehe
[Konfiguration](configuration.de.md#optionen)), sie hat dann Vorrang vor der
Konfigurationsdatei.

## Reines Docker

```sh
mkdir -p scans
docker run -d --name pushscan2folder --restart unless-stopped \
  --user "$(id -u):$(id -g)" \
  -e PUSHSCAN_PRINTER=192.168.1.50 -e PUSHSCAN_NAME=docker-scan \
  -v "$PWD/scans:/scans" ghcr.io/jamdevlab/pushscan2folder:latest
```

## Selbst bauen

Klone das Repository und nimm `docker-compose.dev.yml`. Sie baut das Image aus
dem Klon, schaltet das Debug-Log ein und startet nicht von selbst neu. Sie
nutzt dieselben Ordner `scans` und `config` wie `docker-compose.yml`. Stoppe
deshalb vorher die andere, sonst melden beide dieselben Namen am Drucker an:

```sh
docker compose down
docker compose -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.dev.yml logs -f
```

Bei reinem Docker baue ein lokales Image und nimm im `docker run`-Befehl oben
`pushscan2folder` statt des veröffentlichten Image-Namens:

```sh
docker build -t pushscan2folder .
```

## Benutzer, UID und GID

Das Image läuft als Benutzer ohne Root-Rechte. Dieser Benutzer muss das
Ausgabeverzeichnis beschreiben können. Übergib entweder
`--user "$(id -u):$(id -g)"` (wie oben, oder `user:` in Compose), damit die
Dateien dir gehören, oder setze mit `chown` die UID des Container-Benutzers auf
das Host-Verzeichnis (prüfe sie mit
`docker run --rm --entrypoint id ghcr.io/jamdevlab/pushscan2folder:latest`).

## Volumes

- `./scans:/scans` ist das Ausgabeverzeichnis. Das Image setzt
  `PUSHSCAN_OUTPUT=/scans`; das überschreibt den Schlüssel `output` der
  Konfigurationsdatei (siehe [Vorrang](configuration.de.md#vorrang)). Binde
  deine Ordner unterhalb von `/scans` ein oder verwende absolute
  Ausgabepfade bei den Zielen.
- `./config:/config` enthält `config.toml`. Binde ein Verzeichnis ein, keine
  einzelne Datei: Eine einzeln eingebundene Datei lässt sich nicht atomar
  ersetzen, dann würde das Programm sie beim Speichern über die
  [Weboberfläche](web.de.md) direkt neu schreiben. Das Verzeichnis muss für
  den Benutzer aus `user:` beschreibbar sein.

## Netzwerk

Zum Scannen braucht der Container keine Port-Weiterleitung, er verbindet sich
nur ausgehend mit dem Drucker auf TCP 80. Port 8080 ist nur für die
[Weboberfläche](web.de.md). Dockers Standard-Bridge-Netzwerk funktioniert.

## Paperless-ngx

Binde den Consume-Ordner von paperless innerhalb des Ausgabeverzeichnisses ein
und nutze ein Ziel mit dem Namen des Ordners, zum Beispiel `Paperless@300dpi`:

```yaml
    volumes:
      - /path/to/paperless/consume:/scans/Paperless
```

Der Ordner lässt sich auch auf der Weboberfläche wählen, weil er innerhalb des
Ausgabeverzeichnisses liegt. Ein absoluter Zielordner wie
`Paperless=/consume` funktioniert nur über die Kommandozeile oder die
Konfigurationsdatei. Siehe
[Voreinstellungen pro Ziel](configuration.de.md#voreinstellungen-pro-ziel).

## NAS-Hinweise

- Wähle für `user:` UID und GID des NAS-Benutzers, dem die Scans gehören sollen.
- Rufe die Weboberfläche über einen eigenen Hostnamen auf, wenn weitere
  Weboberflächen auf dem NAS laufen (Browser schicken Cookies an jeden Dienst
  auf demselben Host, egal auf welchem Port), siehe
  [Sicherheitsmodell](web.de.md#sicherheitsmodell).
- Nimm lieber `PUSHSCAN_WEB_PASSWORD_FILE` (ein Docker-Secret) als die
  einfache Variable, denn Umgebungsvariablen sind in `docker inspect` sichtbar.
- Setze `PUSHSCAN_TARGETS` nicht, wenn du die Ziele auf der Weboberfläche
  bearbeitest.
