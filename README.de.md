<p align="center">
  <img src="src/pushscan2folder/favicon.svg" width="96" alt="pushscan2folder icon">
</p>

<h1 align="center">pushscan2folder</h1>

<p align="center">Nutze einen Linux-Rechner oder einen Docker-Container als Ziel für "Scannen an PC" bei Canon-IJ-Druckern.</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-1F5FAD" alt="License: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-1F5FAD" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/dependencies-none-1F5FAD" alt="dependencies: none">
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
- Voreinstellungen pro Ziel für den Dokumenttyp *Automatisch*
- Optionale passwortgeschützte Weboberfläche für Status, Log, Ziele und Einstellungen
- Für Docker und NAS geeignet, nur ausgehende Verbindungen zum Drucker (TCP 80)
- Python 3.11+, nur Standardbibliothek

## Schnellstart

Mit Docker Compose:

```sh
git clone https://github.com/JamDevLab/pushscan2folder.git
cd pushscan2folder
mkdir -p scans config && cp config.example.toml config/config.toml
```

Trage die IP des Druckers in `docker-compose.yml` ein und die Ziele in
`config/config.toml`, dann:

```sh
docker compose up -d --build
docker compose logs -f
```

Die Weboberfläche ist standardmäßig aus. Zum Einschalten die Web-Zeilen in
`docker-compose.yml` einkommentieren (`PUSHSCAN_WEB`, ein eigenes
`PUSHSCAN_WEB_PASSWORD` und den Port), dann läuft sie auf Port 8080.

Auf einem normalen Linux-Rechner:

```sh
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 run --output ./scans
```

Wähle dann den Host am Bedienfeld des Druckers (Scannen an PC) und starte den Scan.
Details stehen in [Docker](#docker) und [Verwendung](#verwendung).

## Inhalt

- [Verwendung](#verwendung)
- [Optionen](#optionen)
- [Konfigurationsdatei](#konfigurationsdatei)
- [Einstellungen vom Bedienfeld](#einstellungen-vom-bedienfeld)
- [Mehrere Ziele](#mehrere-ziele)
- [Weboberfläche (optional)](#weboberfläche-optional)
- [Docker](#docker)
- [So funktioniert es](#so-funktioniert-es)
- [Getestete Modelle und Einschränkungen](#getestete-modelle-und-einschränkungen)
- [Mitwirken](#mitwirken)
- [Mit KI entwickelt](#mit-ki-entwickelt)
- [Lizenz](#lizenz)

## Verwendung

Dienst starten:

```sh
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 run --output ./scans
```

Wähle dann den Host am Bedienfeld des Druckers (Scannen an PC) und starte den Scan.

Weitere Unterbefehle:

```sh
# Register, poll once, print the raw answers and release (debugging).
# Add --keep to stay registered.
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 probe

# Scan once via eSCL without using the panel
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 scan --output ./scans
```

## Optionen

Globale Optionen stehen vor dem Unterbefehl. Jede Option lässt sich auch über
eine Umgebungsvariable setzen. Die Kommandozeile hat Vorrang vor der Umgebung,
und die Umgebung hat Vorrang vor der [Konfigurationsdatei](#konfigurationsdatei).

| Option         | Umgebungsvariable  | Standard            | Gilt für      | Beschreibung |
|----------------|--------------------|---------------------|---------------|-------------|
| `--config`     | `PUSHSCAN_CONFIG`     | `~/.config/pushscan2folder/config.toml` falls vorhanden | alle | TOML-Konfigurationsdatei, siehe [Konfigurationsdatei](#konfigurationsdatei) |
| `--printer`    | `PUSHSCAN_PRINTER`    | (erforderlich)      | alle          | IP oder Hostname des Druckers |
| `--name`       | `PUSHSCAN_NAME`       | `USER  HOSTNAME`    | alle          | Name auf dem Bedienfeld, siehe [Namen auf dem Bedienfeld](#namen-auf-dem-bedienfeld). Der Standardwert ersetzt Zeichen, die das Bedienfeld nicht anzeigen kann, durch `-` |
| `-v/--verbose` | `PUSHSCAN_VERBOSE`    | aus                 | alle          | Debug-Protokollierung. Die Umgebungsvariable aktiviert sie mit `1`, `true` oder `yes` |
| `--output`     | `PUSHSCAN_OUTPUT`     | `./scans`           | run, scan     | Ausgabeverzeichnis (wird bei Bedarf angelegt) |
| `--interval`   | `PUSHSCAN_INTERVAL`   | `4`                 | run           | Abfrageintervall in Sekunden |
| `--format`     | `PUSHSCAN_FORMAT`     | `pdf`               | run (Umgebung: nur run) | `pdf` oder `jpeg`. Ersatzwert, siehe Einstellungen vom Bedienfeld |
| `--color`      | `PUSHSCAN_COLOR`      | `color`             | run           | `color` oder `gray`. Nur mit `--ignore-panel` oder wenn das Bedienfeld keine Farbe sendet |
| `--resolution` | `PUSHSCAN_RESOLUTION` | `300`               | run           | DPI. Ersatzwert. Das Bedienfeld bietet 75, 150, 300, 600 |
| `--source`     | `PUSHSCAN_SOURCE`     | `auto`              | run (Umgebung: nur run) | `auto`, `platen` oder `adf`. Ersatzwert |
| `--trim`       | `PUSHSCAN_TRIM`       | keiner              | run           | Rand abschneiden, indem ein kleinerer Bereich gescannt wird, z. B. `right=3,bottom=2` (Schlüssel `left`, `top`, `right`, `bottom`, in mm, 0 bis 50). Nur Vorlagenglas. Ersetzt die `trim_*`-Werte der Konfigurationsdatei als Ganzes, siehe [Rand abschneiden](#rand-abschneiden) |
| `--targets`    | `PUSHSCAN_TARGETS`    | -                   | run           | Mehrere Einträge auf dem Bedienfeld, jeder mit eigenem Ordner und optionaler Voreinstellung (siehe unten). Ersetzt `--name` für `run` |
| `--ignore-panel` | `PUSHSCAN_IGNORE_PANEL` | aus             | run           | Ignoriert die Einstellungen vom Bedienfeld und nutzt immer die vier Optionen oben. Umgebungsvariable: `1`, `true` oder `yes`. Deaktiviert auch mehrseitige Scans |
| `--multipage`  | `PUSHSCAN_MULTIPAGE`  | `document`          | run           | `document`, `auto`, `both` oder `off`, siehe [Mehrseitige Scans](#mehrseitige-scans-vom-vorlagenglas) |
| `--web`        | `PUSHSCAN_WEB`        | aus                 | run           | Stellt die [Weboberfläche](#weboberfläche-optional) bereit. Umgebungsvariable: `1`, `true` oder `yes` |
| `--web-port`   | `PUSHSCAN_WEB_PORT`   | `8080`              | run           | Port der Weboberfläche |
| `--web-bind`   | `PUSHSCAN_WEB_BIND`   | `0.0.0.0`           | run           | Adresse der Weboberfläche |
| -              | `PUSHSCAN_WEB_PASSWORD` / `PUSHSCAN_WEB_PASSWORD_FILE` | (erforderlich mit `--web`) | run | Passwort der Weboberfläche (mind. 8 Zeichen) oder eine Datei, die es enthält. Nur per Umgebung, nie in der Konfigurationsdatei |
| `--keep`       | -                  | aus                 | probe         | Gibt die Sitzung nicht frei |

Hinweise:

- `scan` hat eigene Optionen `--format` und `--source`. Sie lesen die Variablen
  `PUSHSCAN_FORMAT` / `PUSHSCAN_SOURCE` nicht, und `scan` nutzt immer den
  Standard-Farbmodus und die Standardauflösung (color, 300 dpi) sowie immer eSCL.
- Der Scanbereich kommt aus der Größe vom Bedienfeld; ohne Daten vom Bedienfeld
  ist es A4.

## Konfigurationsdatei

Statt einer langen Kommandozeile kannst du die Einstellungen in einer TOML-Datei
halten (das braucht Python 3.11 wegen `tomllib`). Ein kommentiertes Beispiel
steht in [config.example.toml](config.example.toml).

Ort: `--config PATH` / `PUSHSCAN_CONFIG`; ohne Angabe wird
`$XDG_CONFIG_HOME/pushscan2folder/config.toml` (standardmäßig
`~/.config/pushscan2folder/config.toml`) verwendet, falls es existiert. Ein
ausdrücklich angegebener Pfad muss existieren, sonst beendet sich das Programm
mit einem Fehler.

Vorrang: Kommandozeile > Umgebungsvariable > Konfigurationsdatei > eingebauter
Standardwert. Das Docker-Image setzt `PUSHSCAN_OUTPUT=/scans`, daher wird im
Container der Schlüssel `output` der Datei überschrieben. Binde deine Ordner
unterhalb von `/scans` ein oder verwende absolute Ausgabepfade bei den Zielen.
Ist `--targets` / `PUSHSCAN_TARGETS` gesetzt, ersetzt es die `[[target]]`-Liste
der Datei vollständig. Unbekannte Schlüssel, falsche Typen und ungültige Werte
werden mit einer Meldung abgelehnt, die Datei und Schlüssel nennt, damit
Tippfehler auffallen.

| Schlüssel | Werte | Entspricht |
|-----------|-------|------------|
| `printer` | IP oder Hostname | `--printer` |
| `output` | Ordner; relative Ausgabepfade der Ziele werden darauf bezogen | `--output` |
| `interval` | Sekunden | `--interval` |
| `verbose`, `ignore_panel` | `true` / `false` | `--verbose`, `--ignore-panel` |
| `multipage` | `document`, `auto`, `both`, `off` | `--multipage` |
| `[defaults]` `resolution` | `75`, `150`, `300`, `600` | `--resolution` |
| `[defaults]` `color` | `color`, `gray` | `--color` |
| `[defaults]` `format` | `pdf`, `jpeg` | `--format` |
| `[defaults]` `source` | `auto`, `platen`, `adf` | `--source` |
| `[defaults]` `size` | `a4`, `letter`, `legal`, `10x15`, `13x18` | Scanbereich ohne Daten vom Bedienfeld |
| `[defaults]` `trim_left`, `trim_top`, `trim_right`, `trim_bottom` | Zahl, mm, 0 bis 50 | `--trim` |
| `[[target]]` `name` | erforderlich, max. 31 Zeichen, eindeutig | `NAME` |
| `[[target]]` `output` | Ordner; Standard `<output>/<name>` | `NAME=DIR` |
| `[[target]]` `document_multipage` | `true` / `false` | `mp:` für den Dokumenttyp *Dokument* |
| `[target.auto]` `resolution`, `format`, `size` | wie oben | die `@preset`-Optionen |
| `[target.auto]` `multipage` | `true` / `false` | `mp:` für den Dokumenttyp *Automatisch* |

Die Booleschen Werte für mehrseitige Scans gehen vom globalen Modus
`multipage` aus und fügen *Dokument* / *Automatisch* für dieses Ziel hinzu oder
entfernen es. Setzt ein Ziel keinen von beiden, folgt es dem globalen Modus.

## Einstellungen vom Bedienfeld

Der Drucker sendet mit jeder Scan-Anforderung 32 Bytes: Dokumenttyp, Farbe,
Quelle, Größe, Format, Auflösung, Durchscheinen, Entrasterung und
Unscharfmaskierung. Das Tool bildet diese auf eSCL ab, sodass der Scan dem
entspricht, was du am Bedienfeld gewählt hast.

Die CLI-Optionen `--format`, `--color`, `--resolution` und `--source` (und die
`PUSHSCAN_*`-Umgebungsvariablen) sind nur der Ersatzwert. Sie gelten für den
Dokumenttyp *Automatisch*, bei dem das Bedienfeld keine Details sendet, und für
jedes Feld, das das Bedienfeld offen lässt. Mit `--ignore-panel` (oder
`PUSHSCAN_IGNORE_PANEL=1`) gelten immer die CLI-Werte.

- Durchscheinen, Entrasterung und Unscharfmaskierung haben keine eSCL-Entsprechung
  und werden ignoriert (siehe Einschränkungen).
- "Kompaktes PDF" wird als normales PDF mit 300 dpi gescannt.
- TIFF wird nicht unterstützt, weil weder eSCL noch das native Protokoll es
  liefert. Solche Scans werden als JPEG gespeichert.
- Die Größe "Auto" scannt die volle Breite des Vorlagenglases bei A4-Höhe (kein
  automatischer Zuschnitt).
- Die Auflösungen 75/150/300/600 dpi vom Bedienfeld funktionieren alle über
  eSCL, obwohl die eSCL-Fähigkeiten nur 75, 100, 150, 200, 600 und 1200 auflisten.
- Wird ein Scan am Bedienfeld abgebrochen, bleibt ein unvollständiges Dokument
  zurück. Das Tool erkennt das und verwirft es, es wird also nichts gespeichert.

### Rand abschneiden

Manche Scanner erfassen am Rand des Vorlagenglases einen dünnen Streifen. Der
TR8550 zeigt anscheinend etwa 3 mm rechts und 2 mm unten (noch zu prüfen). Mit
`--trim right=3,bottom=2` (oder `PUSHSCAN_TRIM`, oder den `trim_*`-Schlüsseln in
der Konfigurationsdatei) fordert das Tool beim Drucker einen kleineren
Scanbereich an, sodass der Rand gar nicht erst gescannt wird. Es gibt keine
Bildverarbeitung. Der Zuschnitt gilt nur für das Vorlagenglas, ADF-Scans werden
nicht zugeschnitten. Bliebe in einer Richtung weniger als 1 Zoll übrig, wird der
Zuschnitt übersprungen und eine Warnung ins Log geschrieben. Die Einstellung ist
global, nicht pro Ziel.

### Mehrseitige Scans vom Vorlagenglas

Bei Scans vom Vorlagenglas mit dem Dokumenttyp *Dokument* zeigt der Drucker nach
jeder Seite einen Dialog: *Stopp*, *Schwarzweiß*, *Farbe* und *Beenden*. Lege die
nächste Seite auf das Glas und drücke *Farbe* oder *Schwarzweiß*, um sie zu
scannen (jede Seite kann ihren eigenen Farbmodus haben), oder *Beenden*, um zu
beenden. Alle Seiten werden in einem PDF gespeichert (beim Format JPEG: eine
Datei pro Seite).

Dafür verwendet das Tool Canons eigenes Scanner-Protokoll
(`/canon/ij/command2/port3`) statt eSCL, weil nur dieses Protokoll die Frage
nach der nächsten Seite kennt. Der Drucker liefert jede Seite als JPEG, und das
PDF bettet die JPEGs unverändert ein.

`--multipage` (`PUSHSCAN_MULTIPAGE`) legt fest, welche Dokumenttypen den Dialog
bekommen:

| Wert                 | Dialog für                                        |
|----------------------|---------------------------------------------------|
| `document` (Standard)| Dokument, wie bei der offiziellen Software        |
| `auto`               | nur *Automatisch*                                   |
| `both`               | *Dokument* und *Automatisch*                          |
| `off`                | nie; alle Scans nutzen eSCL                       |

Geprüft mit A4 bei 300 dpi. Andere Auflösungen und Größen nutzen dieselben
Parameter, sind aber noch nicht getestet.

`1`/`true`/`yes` bedeuten `document`, `0`/`false`/`no` bedeuten `off`. Bei
*Automatisch* sendet das Bedienfeld weder Auflösung noch Format, daher gelten die
Ersatzoptionen. Scans über das Einzugsfach nutzen immer eSCL (das Einzugsfach
liefert bereits alle Seiten in einem PDF).

Der Drucker setzt den Dokumenttyp nach einem Scan unter Umständen auf *Automatisch*
zurück. Prüfe ihn daher vor dem nächsten mehrseitigen Scan.

### Einzugsfach (ADF)

Der Drucker erkennt die Quelle selbst mit seinem Papiersensor, das Bedienfeld
bietet keine Quellenauswahl. Das Format Legal gibt es nur über das Einzugsfach.
Das Einzugsfach scannt nur einseitig. Ohne Daten vom Bedienfeld (*Automatisch*) und
mit `--source auto` fragt das Tool den Drucker, ob Papier eingelegt ist. Ist das
der Fall, nutzt es das Einzugsfach, sonst das Vorlagenglas.

## Mehrere Ziele

Eine Instanz kann mehrere Namen beim Drucker registrieren. Jeder Name erscheint
als eigener Computer auf dem Bedienfeld, und seine Scans landen in einem
eigenen Ordner:

```sh
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 run \
  --output ./scans --targets "Scans,Paperless=consume,Archive=/data/archive"
```

Die Liste wird durch Kommas getrennt, und jeder Eintrag hat eine von zwei Formen:

- `NAME` speichert in `<output>/NAME`. Andere Zeichen als Buchstaben, Ziffern,
  `.`, `_` und `-` werden zu `_`.
- `NAME=DIR` speichert in `DIR`. Ein relatives `DIR` wird relativ zu `--output`
  aufgelöst, ein absolutes unverändert verwendet.

Namen müssen eindeutig sein und die [Regeln für Namen auf dem Bedienfeld](#namen-auf-dem-bedienfeld)
einhalten. Zwei Ziele dürfen sich keinen Ordner teilen (`a b` und `a_b`
ergeben beide `a_b`, zum Beispiel). Alle Namen teilen sich eine Abfrageschleife,
daher gilt das Abfrageintervall für die ganze Liste.

### Namen auf dem Bedienfeld

Am TR8550 beobachtet:

- Nur A-Z, a-z, 0-9, Leerzeichen, `-`, `_` und `@` werden angezeigt. Der Drucker
  akzeptiert andere Zeichen (`.`, `&`, Umlaute, Akzente, Emoji, ...), zeigt sie
  aber als Leerstellen an. Deshalb lehnt pushscan2folder Namen mit solchen
  Zeichen ab.
- Namen haben höchstens 31 Zeichen. Das Bedienfeld zeigt etwa 25 und danach `...`
  (für längere Namen wird eine Warnung protokolliert).
- 20 Namen gleichzeitig funktionierten (eine scrollbare Liste), und es wurde
  keine Obergrenze gefunden.
- Die Liste ist nach Registrierungszeit sortiert, nicht alphabetisch.

### Voreinstellungen pro Ziel

Hänge `@` und mit `+` verbundene Optionen an, um einem Ziel eigene Einstellungen
zu geben:

```sh
--targets "Scans,Paperless@300dpi,Archive@600dpi+jpeg+mp:both"
```

| Option | Bedeutung |
|--------|-----------|
| `75dpi`, `150dpi`, `300dpi`, `600dpi` | Auflösung |
| `pdf`, `jpeg` | Dateiformat |
| `a4`, `letter`, `legal`, `10x15`, `13x18` | Scanbereich |
| `mp:document`, `mp:auto`, `mp:both`, `mp:off` | Dialog für mehrseitige Scans, überschreibt `--multipage` für dieses Ziel |

Welcher Wert gewinnt:

- *Automatisch* am Bedienfeld: Die Voreinstellung gewinnt bei Auflösung,
  Format und Größe. Die Farbe kommt immer vom Bedienfeld (die gedrückte
  Starttaste), eine Voreinstellung hat keine Farbe. Einstellungen, die in der
  Voreinstellung fehlen, kommen aus den globalen Optionen.
- Dokument und Foto: Die Einstellungen vom Bedienfeld gewinnen, und die
  Voreinstellung füllt nur auf, was das Bedienfeld nicht sendet.
- Mit `--ignore-panel` gilt die Voreinstellung immer.

Bei den Optionen wird nicht zwischen Groß- und Kleinschreibung unterschieden.
Eine unbekannte Option stoppt das Programm mit einem Fehler, daher lässt sich
`NAME=DIR` nicht mit einem Ordnernamen verwenden, der `@` enthält.

Der `@preset`-String ist die Kurzform der Tabelle `[target.auto]` der
[Konfigurationsdatei](#konfigurationsdatei).

Für paperless-ngx bindest du dessen Consume-Ordner innerhalb des
Ausgabeordners ein, in Docker zum Beispiel mit
`- /path/to/paperless/consume:/scans/Paperless`, und nutzt das Ziel
`Paperless@300dpi`. Ordner innerhalb des Ausgabeordners lassen sich auch
auf der Weboberfläche wählen. Ein absoluter Pfad wie `Paperless=/consume`
funktioniert ebenfalls, aber nur über die Kommandozeile oder die
Konfigurationsdatei.

## Weboberfläche (optional)

Eine kleine Weboberfläche für den lokalen Gebrauch (LAN, NAS) mit aktuellem
Status, letzten Scans, dem Log, einem Editor für die Ziele, einem
Einstellungsformular und einem Rohtext-Editor für die Konfigurationsdatei. Sie
ist standardmäßig aus und braucht keine zusätzlichen Pakete. Sie funktioniert
ohne JavaScript. Ein kleines Skript (`/app.js`, vom Programm selbst
ausgeliefert, keine Inline-Skripte) aktualisiert Status und Log ohne
sichtbares Neuladen, warnt auf den Bearbeitungsseiten vor ungespeicherten
Änderungen und fügt im Rohtext-Editor mit der Tab-Taste zwei Leerzeichen ein.
Ohne JavaScript laden Status und Log einfach alle 10 s neu.

```sh
PUSHSCAN_WEB=1 PUSHSCAN_WEB_PASSWORD='a long password' \
PUSHSCAN_CONFIG=~/pushscan.toml \
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 run
# web page on http://0.0.0.0:8080
```

| Einstellung | Bedeutung |
|-------------|-----------|
| `PUSHSCAN_WEB=1` / `--web` | aktivieren (nur `run`) |
| `PUSHSCAN_WEB_PORT` / `--web-port` | Port, Standard 8080 |
| `PUSHSCAN_WEB_BIND` / `--web-bind` | Adresse, Standard `0.0.0.0` (mit `127.0.0.1` bleibt sie lokal) |
| `PUSHSCAN_WEB_PASSWORD` | Passwort, mindestens 8 Zeichen |
| `PUSHSCAN_WEB_PASSWORD_FILE` | Datei mit dem Passwort (z. B. ein Docker-Secret); wird genutzt, wenn die Variable darüber nicht gesetzt ist |
| `PUSHSCAN_WEB_SECURE_COOKIE=1` | nur hinter einem HTTPS-Reverse-Proxy: `Secure`-Cookie (siehe HTTPS unten) |
| `PUSHSCAN_WEB_PASSWORD_CHECK=0` | Passwortregeln überspringen (siehe unten) |
| `PUSHSCAN_WEB_AUTH=0` | gar keine Anmeldung (siehe unten) |

Ohne gültiges Passwort startet das Programm nicht (Exit-Code 2). Es liest das
Passwort nie aus der Konfigurationsdatei und schreibt oder zeigt es nie.

Zwei Schalter lockern das, beide nur auf Wunsch. Sie sind reine
Umgebungsvariablen (keine Kommandozeilenoption, kein Schlüssel in der
Konfigurationsdatei), und alles außer einem klaren `1` oder `0` ist ein
Fehler, damit ein Tippfehler keinen Schutz ausschaltet.

- `PUSHSCAN_WEB_PASSWORD_CHECK=0` überspringt die Passwortregeln: die
  Mindestlänge von 8 Zeichen und die Ablehnung des Beispielpassworts
  `change-me-please`. Ein leeres Passwort bleibt ein Fehler. Das Programm
  schreibt beim Start eine Warnung ins Log.
- `PUSHSCAN_WEB_AUTH=0` betreibt die Weboberfläche ohne Anmeldung. Es braucht
  kein Passwort; ein gesetztes wird ignoriert, und das Log sagt das. Das
  Programm schreibt beim Start eine Warnung, und jede Seite zeigt in der
  Navigation "No password set". Wer den Port erreicht, kann Ziele und
  Einstellungen ändern und die Konfigurationsdatei bearbeiten. Nutze das nur in
  einem vertrauenswürdigen Netz und niemals mit einem ins Internet
  weitergeleiteten Port. Alles andere bleibt: CSRF-Token in allen Formularen
  (eines pro Prozess statt pro Sitzung), die Origin-Prüfung, die
  Sicherheits-Header und die Regel, dass Zielordner im Ausgabeverzeichnis
  bleiben.
  Ohne Anmeldung antwortet die Seite nur, wenn sie über eine IP-Adresse, als
  `localhost`, über einen Namen ohne Punkt (`nas`) oder über einen lokalen
  Namen mit `.local`, `.lan`, `.home`, `.home.arpa`, `.internal` oder
  `.fritz.box` aufgerufen wird. Das verhindert DNS-Rebinding, bei dem eine
  fremde Webseite ihren eigenen Namen auf dein NAS zeigen lässt.

Seiten:

- Status (`/`) zeigt den Drucker, die letzte erfolgreiche Abfrage oder den
  letzten Fehler, ausstehende Änderungen an den Zielen, die Ziele (Ordner,
  registriert, Voreinstellung für *Automatisch*, mehrseitig) und die letzten Scans. Sie
  aktualisiert sich alle 10 s.
- Log (`/log`) zeigt die letzten 500 Logzeilen (INFO und höher).
- Ziele (`/targets`) fügt Ziele hinzu, ändert und löscht sie, mit Name, Ordner,
  Dialog für mehrseitige Scans und Voreinstellung für *Automatisch*. Namen und Ordner
  werden wie in der Konfigurationsdatei geprüft. Die Karten lassen sich mit
  "Move up" und "Move down" umsortieren, "Add target" fügt eine leere Karte
  hinzu; gespeichert wird erst mit "Save". Das Bedienfeld des Druckers listet
  die Ziele in dieser Reihenfolge. Nach einer geänderten Reihenfolge
  verschwinden die Namen kurz, während sie neu registriert werden. Beim Speichern wird die
  Konfigurationsdatei geschrieben, und der laufende Dienst wechselt vor seinem
  nächsten Abfragezyklus zur neuen Liste (bis dahin als "pending" angezeigt).
  Die Optionen für *Automatisch* je Ziel zeigen den aktuellen Standardwert,
  etwa "Default (300 dpi)"; er stammt von der Einstellungsseite.
- Einstellungen (`/settings`) bearbeitet `resolution`, `color`, `format`,
  `source`, `size` und die vier `trim_*`-Werte aus `[defaults]` sowie
  `multipage`, `ignore_panel` und `interval`, jeweils mit kurzer Erklärung. Die
  Werte werden mit denselben Regeln wie die Konfigurationsdatei geprüft; ein
  leeres Feld entfernt den Schlüssel. `printer` und der Basis-Ausgabeordner
  `output` werden nur angezeigt. Überschreibt eine Umgebungsvariable oder
  Kommandozeilenoption einen Wert (etwa `PUSHSCAN_INTERVAL` oder
  `PUSHSCAN_TRIM`), weist die Seite darauf hin und zeigt den verwendeten Wert;
  der gespeicherte Wert wirkt nicht, solange die Überschreibung besteht. Die
  Einstellungen werden nur in die Datei geschrieben und gelten nach einem
  Neustart.
- Konfigurationsdatei (`/config`, von den Einstellungen aus verlinkt) ist ein
  Texteditor für die ganze Datei. Der Text wird unverändert gespeichert,
  Kommentare inklusive, nachdem er wie beim Start geprüft wurde; eine ungültige
  Datei wird nicht geschrieben, der Fehler (bei TOML-Syntaxfehlern mit
  Zeilennummer) steht neben deinem Text. Die Weboberfläche bekommt trotzdem
  keinen Dateizugriff außerhalb des Ausgabeordners: Der Editor lehnt ein
  geändertes `output` oder `printer` ab, ebenso ein `[[target]]`, dessen
  Ausgabeordner kein relativer Pfad innerhalb des Ausgabeordners ist. Ziele, die
  bereits so in der Datei stehen (etwa `output = "/consume"`), dürfen
  unverändert bleiben. Das Formular enthält einen Hash des Dateitexts: Hat sich
  die Datei inzwischen geändert, wird nichts gespeichert und der neue Inhalt
  angezeigt. Änderungen an den Zielen werden wie auf der Zielseite übernommen,
  alles andere nach einem Neustart. Die Größengrenze ist 64 KB.

Ob sich die Ziele bearbeiten lassen, hängt davon ab, woher sie kommen:

- aus `PUSHSCAN_TARGETS` / `--targets`: Bearbeiten ist abgeschaltet, weil die
  Variable die Datei beim nächsten Start überschreiben würde;
- aus der Konfigurationsdatei (`PUSHSCAN_CONFIG`, `--config` oder der
  Standardort): editierbar; existiert die Datei noch nicht, legt das erste
  Speichern sie an.

Kommentare in der Konfigurationsdatei gehen beim Speichern über das Ziel- oder
Einstellungsformular verloren. Die Datei wird neu geschrieben; andere Schlüssel
behalten ihre Werte. Nur der Rohtext-Editor behält Kommentare. Bei jedem
gespeicherten Ziel werden beide Schalter für mehrseitige Scans ausdrücklich
geschrieben.

Ordner, die du auf der Weboberfläche einträgst, liegen immer innerhalb des
Ausgabeordners (`--output` / `PUSHSCAN_OUTPUT`, in Docker `/scans`). Gib einen
einfachen relativen Pfad ein, etwa `Paperless` oder `buero/rechnungen`.
Absolute Pfade, `..`, Backslashes und Symlinks, die aus dem Ausgabeordner
herausführen, lehnt die Seite ab, sie kann also nirgendwo anders schreiben.
Ein Ziel mit einem Ordner außerhalb des Ausgabeordners (zum Beispiel
`output = "/consume"`) lässt sich nur in der Konfigurationsdatei ändern. Die
Weboberfläche zeigt es schreibgeschützt an und behält es beim Speichern bei;
löschen kannst du es dort trotzdem.

Sicherheitshinweise:

- Die Oberfläche nutzt reines HTTP mit einem gemeinsamen Passwort. Verwende sie
  nur in einem vertrauenswürdigen LAN und setze sie niemals dem Internet aus.
  Wer deinen Netzwerkverkehr mitlesen kann, sieht Passwort und Sitzungs-Cookie.
- Das Cookie ist `HttpOnly` und `SameSite=Strict`. Eine Sitzung endet nach
  2 Stunden ohne Anfrage, 12 Stunden nach der Anmeldung oder beim Neustart des
  Dienstes. Es gibt höchstens 20 Sitzungen gleichzeitig. Der Server speichert
  von jedem Sitzungs-Token nur einen Hash.
- Nutze ein langes Passwort. Nach 5 falschen Passwörtern ist die Anmeldung
  1 Minute gesperrt; jede weitere Sperre verdoppelt die Zeit, bis höchstens
  15 Minuten. Die Sperre gilt global, nicht pro IP, weil hinter einer
  Docker-Portweiterleitung alle Clients gleich aussehen.
- Nimm lieber `PUSHSCAN_WEB_PASSWORD_FILE` (zum Beispiel ein Docker-Secret) als
  `PUSHSCAN_WEB_PASSWORD`, denn Umgebungsvariablen sind in `docker inspect`
  sichtbar.
- Jedes Formular trägt ein CSRF-Token, Cross-Origin-POSTs werden abgelehnt,
  und die Seiten senden strikte Header (CSP, kein Framing, kein Caching).
  Ausgeliefert werden nur die Seiten selbst, ein Stylesheet, das Icon und das kleine Skript; die
  Weboberfläche kann keine Dateien lesen oder herunterladen.
- Browser schicken Cookies an jeden Dienst auf demselben Host, egal auf welchem
  Port. Laufen weitere Weboberflächen auf dem NAS, rufe diese Seite besser über
  einen eigenen Hostnamen auf.

HTTPS: Stelle einen TLS-Reverse-Proxy (Caddy, nginx, Traefik) davor und setze
`PUSHSCAN_WEB_SECURE_COOKIE=1`. Das Cookie heißt dann `__Host-p2f_session` und
ist als `Secure` markiert, die Seite funktioniert dann nur noch über HTTPS. Der
Proxy muss den ursprünglichen `Host`-Header weitergeben (nginx:
`proxy_set_header Host $host;`), sonst werden Formulare mit "Origin does not
match Host" abgelehnt. Binde den Dienst an eine interne Adresse
(`PUSHSCAN_WEB_BIND`), damit man den Proxy nicht umgehen kann.

Docker: Die mitgelieferte `docker-compose.yml` ist für die Weboberfläche
vorbereitet (`./config:/config`, `PUSHSCAN_CONFIG: /config/config.toml`); zum
Einschalten die Web-Zeilen und den Port einkommentieren. Binde für die Konfiguration ein Verzeichnis ein, keine einzelne
Datei: Eine einzeln eingebundene Datei lässt sich nicht atomar ersetzen, dann
schreibt das Programm sie direkt neu. Das Verzeichnis muss für den Benutzer
aus `user:` beschreibbar sein. Setze `PUSHSCAN_TARGETS` nicht, wenn du die
Ziele auf der Weboberfläche bearbeitest.

## Docker

Bauen und starten:

```sh
docker build -t pushscan2folder .
mkdir -p scans
docker run -d --name pushscan2folder --restart unless-stopped \
  --user "$(id -u):$(id -g)" \
  -e PUSHSCAN_PRINTER=192.168.1.50 -e PUSHSCAN_NAME=docker-scan \
  -v "$PWD/scans:/scans" pushscan2folder
```

Oder nutze die mitgelieferte `docker-compose.yml`. Sie hält Ziele und
Scan-Einstellungen in `config/config.toml`; in der Compose-Datei stehen nur
die Drucker-IP und die (auskommentierten) Einstellungen der Weboberfläche:

```sh
mkdir -p scans config && cp config.example.toml config/config.toml
# PUSHSCAN_PRINTER in docker-compose.yml setzen (bei Bedarf die Web-Zeilen)
docker compose up -d --build
docker compose logs -f
```

Mit dem Beispielpasswort `change-me-please` startet das Programm nicht. Jede
Option lässt sich auch als Umgebungsvariable setzen (siehe
[Optionen](#optionen)), sie hat dann Vorrang vor der Konfigurationsdatei.

Das Image läuft als Benutzer ohne Root-Rechte. Dieser Benutzer muss das
Ausgabeverzeichnis beschreiben können. Übergib entweder
`--user "$(id -u):$(id -g)"` (wie oben, oder `user:` in Compose), damit die
Dateien dir gehören, oder setze mit `chown` die UID des Container-Benutzers auf
das Host-Verzeichnis (prüfe sie mit
`docker run --rm --entrypoint id pushscan2folder`).

Zum Scannen braucht der Container keine Port-Weiterleitung, er verbindet sich
nur ausgehend mit dem Drucker auf TCP 80. Port 8080 ist nur für die
Weboberfläche.

## So funktioniert es

1. Registrieren. Das Tool meldet sich mit Canons CHMP-Push-Scan-Benachrichtigungsprotokoll
   beim Drucker an (HTTP POST an `/canon/ij/command1/port2`). Der gewählte
   Name erscheint auf dem Bedienfeld.
2. Abfragen. Das Tool fragt den Drucker wie die offizielle Software alle 4 Sekunden ab (einstellbar). Ist
   der Drucker nicht erreichbar, registriert es sich mit exponentiellem Back-off
   neu, begrenzt auf 10 s, sodass die Namen etwa 10 s nach einem Neustart des
   Druckers wieder erscheinen.
3. Scannen. Startet der Benutzer am Bedienfeld einen Scan an diesen Host, hat
   die Antwort der Abfrage den Status `0x8000` ("Scan angefordert") und enthält
   32 Bytes Einstellungen vom Bedienfeld. Das Tool scannt mit diesen
   Einstellungen, entweder über Canons eigenes Scanner-Protokoll (mehrseitige
   Scans vom Vorlagenglas, siehe unten) oder über eSCL. Es schreibt
   `scan_YYYYmmdd_HHMMSS[_NN].pdf|jpg` in das Ausgabeverzeichnis und
   überschreibt nie vorhandene Dateien. Wählst du am Bedienfeld einen Namen aus,
   ohne einen Scan zu starten, passiert nichts.
4. Freigeben. Bei SIGINT/SIGTERM gibt das Tool die Sitzung frei.

Das Tool braucht Python >= 3.11 und nur die Standardbibliothek. Es baut nur ausgehende Verbindungen zum Drucker auf (TCP 80). Eingehende Ports sind nicht nötig (außer für die optionale Weboberfläche), daher funktioniert Dockers Standard-Bridge-Netzwerk.

### Registrierung und lange Scans

Der Drucker verwirft eine Registrierung nach etwa 60 s ohne Abfrage (Status
`0x1`). Während ein Scan läuft (mehrseitige Scans vom Vorlagenglas ebenso wie
lange eSCL-Scans, z. B. mit 600 dpi oder mehreren Seiten aus dem Einzugsfach),
fragt das Tool alle 5 s weiter ab, damit die Namen auf dem Bedienfeld bleiben.
Wird eine Registrierung trotzdem verworfen, registriert sich das Tool
automatisch neu.

### Protokollübersicht

Transport: HTTP POST an `http://<printer>:80/canon/ij/command1/port2` mit den
Headern `Content-Type: application/octet-stream`, `X-CHMP-Version: 1.0`,
`X-CHMP-CommandType: BJNPNotify`, `X-CHMP-EventType: PuScan`.

Request-Body, 0x68 Bytes, Big Endian:

| Offset | Size     | Field        | Notes                                      |
|--------|----------|--------------|--------------------------------------------|
| +0x00  | u16      | type         | 1 = register, 2 = poll, 4 = release        |
| +0x02  | u16      | reserved     |                                            |
| +0x04  | u32      | session id   | poll / release                             |
| +0x08  | 64 bytes | host name    | UTF-16BE, NUL padded (register only)       |
| +0x48  | u32      | reserved     |                                            |
| +0x60  | u32      | reserved     |                                            |

Response-Body, 0x110 Bytes, Big Endian:

| Offset | Size     | Field          | Notes                                    |
|--------|----------|----------------|------------------------------------------|
| +0x02  | u16      | status         | 0x8000 = scan requested (poll)           |
| +0x04  | u32      | session id     | register                                 |
| +0x08  | u32      | unknown        |                                          |
| +0x0c  | u32      | event value    | poll, status 0x8000                      |
| +0x10  | 32 bytes | interrupt data | poll, status 0x8000                      |
| +0x8c  | u32      | unknown        |                                          |

Den Aufbau der 32 Interrupt-Bytes und die offenen Fragen findest du in
[docs/PROTOCOL.md](docs/PROTOCOL.md) (auf Englisch).

## Getestete Modelle und Einschränkungen

| Model                    | Verified features                               | Status |
|--------------------------|-------------------------------------------------|--------|
| Canon PIXMA TR8550 (TR8500 series) | push scan, multi target, ADF, panel settings, multi-page platen | ok     |

Einschränkungen:

- Nur mit einem Canon PIXMA TR8550 getestet. Andere IJ-Modelle funktionieren
  vielleicht, vielleicht auch nicht.
- Die Bedienfeld-Einstellungen "Durchscheinen reduzieren", "Entrasterung" und
  "Unscharfmaskierung" werden gelesen, aber noch nicht angewendet. eSCL kennt
  keine Entsprechung, und die offizielle Software wendet sie wahrscheinlich auf
  dem PC an. Sie anzuwenden bräuchte Bildverarbeitung auf deinem Rechner und
  kommt vielleicht später dazu, zum Beispiel als optionales Extra.
- Protokolldetails und offene Fragen stehen in [docs/PROTOCOL.md](docs/PROTOCOL.md) (auf Englisch).
- Namen auf dem Bedienfeld: 31 Zeichen, etwa 25 sichtbar, nur ASCII-Buchstaben, Ziffern, Leerzeichen, `-`, `_`, `@`.
- Das Tool kontaktiert nur den Drucker. Eine automatische Suche ist nicht
  implementiert, daher musst du die Adresse des Druckers angeben.

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
Canon und PIXMA sind Marken von Canon Inc. Dieses Projekt steht in keiner Verbindung zu Canon und wird von Canon weder unterstützt noch empfohlen.

### Rechtlicher Hinweis

Dieses Projekt enthält keinen Canon-Code und keine Canon-Binärdateien und
verbreitet keine. Das CHMP-Push-Scan-Protokoll wurde von Grund auf neu
implementiert, auf Basis einer statischen Analyse des Windows-Tools "IJ Network
Scanner Selector EX2". Das Scanner-Protokoll für mehrseitige Scans beruht auf
der Beobachtung des Netzwerkverkehrs zwischen der offiziellen Software und dem
Drucker. Beides geschah ausschließlich zu Interoperabilitätszwecken.
