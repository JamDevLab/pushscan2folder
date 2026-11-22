# Docker

[English](docker.md) | Deutsch

Zurück zur [README](../README.de.md).

Es gibt noch kein veröffentlichtes Image. Beide Varianten unten bauen das
Image aus einem Klon des Repositorys.

## Docker Compose

Die mitgelieferte `docker-compose.yml` hält Ziele und Scan-Einstellungen in
`config/config.toml`; in der Compose-Datei stehen nur die Drucker-IP und die
(auskommentierten) Einstellungen der Weboberfläche:

```sh
mkdir -p scans config && cp config.example.toml config/config.toml
# PUSHSCAN_PRINTER in docker-compose.yml setzen (bei Bedarf die Web-Zeilen)
docker compose up -d --build
docker compose logs -f
```

Die Datei sieht so aus (die Web-Zeilen sind auskommentiert, die Weboberfläche
ist also standardmäßig aus):

```yaml
services:
  pushscan2folder:
    build: .
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

Bauen und starten:

```sh
docker build -t pushscan2folder .
mkdir -p scans
docker run -d --name pushscan2folder --restart unless-stopped \
  --user "$(id -u):$(id -g)" \
  -e PUSHSCAN_PRINTER=192.168.1.50 -e PUSHSCAN_NAME=docker-scan \
  -v "$PWD/scans:/scans" pushscan2folder
```

## Benutzer, UID und GID

Das Image läuft als Benutzer ohne Root-Rechte. Dieser Benutzer muss das
Ausgabeverzeichnis beschreiben können. Übergib entweder
`--user "$(id -u):$(id -g)"` (wie oben, oder `user:` in Compose), damit die
Dateien dir gehören, oder setze mit `chown` die UID des Container-Benutzers auf
das Host-Verzeichnis (prüfe sie mit
`docker run --rm --entrypoint id pushscan2folder`).

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
