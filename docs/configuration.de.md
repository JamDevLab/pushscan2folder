# Konfiguration

[English](configuration.md) | Deutsch

Zurück zur [README](../README.de.md).

- [Unterbefehle](#unterbefehle)
- [Optionen](#optionen)
- [Konfigurationsdatei](#konfigurationsdatei)
- [Vorrang](#vorrang)
- [Datei im laufenden Betrieb ändern](#datei-im-laufenden-betrieb-ändern)
- [Einstellungen vom Bedienfeld](#einstellungen-vom-bedienfeld)
- [Rand abschneiden](#rand-abschneiden)
- [Mehrseitige Scans vom Vorlagenglas](#mehrseitige-scans-vom-vorlagenglas)
- [Einzugsfach (ADF)](#einzugsfach-adf)
- [Mehrere Ziele](#mehrere-ziele)
- [Namen auf dem Bedienfeld](#namen-auf-dem-bedienfeld)
- [Voreinstellungen pro Ziel](#voreinstellungen-pro-ziel)
- [Dateinamen](#dateinamen)

## Unterbefehle

Ohne Unterbefehl wird `run` genommen: `pushscan2folder --printer 192.168.1.50`
entspricht `pushscan2folder --printer 192.168.1.50 run`. Globale Optionen
(`--config`, `--printer`, `--name`, `--log-file`, `--verbose`) stehen vor dem
Unterbefehl; Optionen von `run` wie `--output` gehen auch ohne ihn.

Dienst starten:

```sh
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 run --output ./scans
```

Wähle dann den Host am Bedienfeld des Druckers (Scannen an PC) und starte den Scan.

Beim Start schreibt `run` eine kurze Zusammenfassung ins Log: Version, Drucker,
Konfigurationsdatei, jeden Namen mit seinem Ordner, die Adresse der Weboberfläche
(oder "web page off") und die Logdatei. Dass der Drucker einen Namen angenommen hat,
steht als "'NAME' is now on the printer panel under Scan to PC" im Log, jeder
gespeicherte Scan als "saved PFAD".

Die weiteren Unterbefehle:

```sh
# Stellt ein paar Fragen (Drucker, Name, Ordner, Weboberfläche, unter Windows
# Autostart) und schreibt die Konfigurationsdatei. Erneut starten zum Ändern.
PYTHONPATH=src python3 -m pushscan2folder setup
```

Ist noch kein Drucker eingetragen, sucht das Setup zuerst im lokalen Netz mit
mDNS (Bonjour, Dienst `_uscan._tcp`) nach eSCL-Scannern. Die Suche dauert etwa
5 Sekunden. Sie listet Adresse und Modell jedes gefundenen Scanners mit einer
Nummer auf, und du gibst diese Nummer oder eine IP-Adresse ein. Antwortet
niemand, fragt das Setup wie bisher nach der IP-Adresse. Ein Firewall-Filter für
Multicast oder ein VPN kann der Grund sein. Die IP-Adresse steht in den
Netzwerkeinstellungen am Bedienfeld des Druckers. Die Suche braucht nur die
Python-Standardbibliothek.

Die Weboberfläche braucht kein Passwort, wenn sie nur auf diesem PC lauscht (`bind` ist
`127.0.0.1`, `::1` oder `localhost`); das Setup fragt dann keines ab. Das Passwort der
Weboberfläche kommt nie in `config.toml`: Das Setup legt es in
`web_password.txt` neben der Konfigurationsdatei ab (Modus 0600, wo möglich) und
trägt die Datei in `[web] password_file` ein. Hat die Datei schon
`[[target]]`-Einträge, fragt das Setup nur nach Drucker, Weboberfläche und
Autostart und lässt die Ziele unverändert. Das Setup startet auch von selbst, wenn
das Programm ohne Argument in einer Konsole gestartet wird und es noch keine
Konfigurationsdatei gibt; nicht interaktive Starts (Docker, Dienste) fragen nie.

Ohne Fenster laufen (Einzelheiten für Windows in [windows.de.md](windows.de.md)):

```sh
# Startet abgekoppelt im Hintergrund mit den aktuellen Optionen und kehrt zurück.
# Windows: kein Konsolenfenster. Linux/macOS: eigene Sitzung.
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 start
PYTHONPATH=src python3 -m pushscan2folder status   # läuft es?, PID, Logdatei, letzte Logzeilen
PYTHONPATH=src python3 -m pushscan2folder stop     # beendet es und gibt die Namen am Drucker frei
```

`start` nimmt dieselben Optionen wie `run` und lehnt ab, wenn schon eine
Hintergrundinstanz läuft. Das Log geht in den Statusordner
(`%LOCALAPPDATA%\pushscan2folder\pushscan2folder.log` unter Windows,
sonst `$XDG_STATE_HOME/pushscan2folder/pushscan2folder.log`, Standard
`~/.local/state/...`), sofern nicht `--log-file` angegeben ist. `stop` schreibt eine
Stopp-Anforderungsdatei, die die Abfrageschleife einmal pro Sekunde prüft, und
bricht den Prozess nur ab, wenn er nach 30 Sekunden nicht beendet ist. Läuft
gerade ein Scan, wartet `stop` stattdessen bis zu 600 Sekunden (10 Minuten) und
gibt "A scan is running; it is finished and saved first ..." aus. Die Instanz
legt für die Dauer eines Scans eine Busy-Markierungsdatei in ihrem Statusordner
an. Ein mehrseitiger Scan vom Vorlagenglas, der am Bedienfeld auf die
Entscheidung über die nächste Seite wartet, endet sofort mit den bisher
gescannten Seiten, und diese werden gespeichert. Eine Seite, die gerade
gescannt wird, wird noch fertig. `uninstall` führt ebenfalls `stop` aus und
wartet genauso. `status`
endet mit 0, wenn die Instanz läuft, sonst mit 1. Ein `run` im Vordergrund
startet nicht, solange die Hintergrundinstanz läuft, weil beide dieselben Namen
anmelden würden. Es verweist auf `pushscan2folder stop`.

```sh
# Beendet die Instanz, entfernt den Windows-Autostart-Eintrag und fragt dann
# (Standard nein), ob Konfigurationsordner und Log-/Statusordner gelöscht werden.
PYTHONPATH=src python3 -m pushscan2folder uninstall
# Nicht interaktiv: behält Konfiguration und Log, außer mit --purge.
PYTHONPATH=src python3 -m pushscan2folder uninstall --yes [--purge]
```

Scans werden nie gelöscht, und ein Ordner, der einen Scan-Ordner enthält, bleibt erhalten.

`health` prüft, ob der laufende Dienst kürzlich mit dem Drucker gesprochen hat.
Der Docker-Healthcheck nutzt es (siehe [Docker](docker.de.md#healthcheck)):

```sh
# Exit-Code 0, wenn die Heartbeat-Datei jünger als --max-age Sekunden ist
# (Standard 120), sonst 1. Der Grund wird ausgegeben.
PYTHONPATH=src python3 -m pushscan2folder health \
  --heartbeat-file /tmp/pushscan2folder.alive [--max-age 120]
```

`probe` und `scan` dienen der Fehlersuche:

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
Mehr unter [Vorrang](#vorrang).

| Option         | Umgebungsvariable  | Standard            | Gilt für      | Beschreibung |
|----------------|--------------------|---------------------|---------------|-------------|
| `--config`     | `PUSHSCAN_CONFIG`     | `~/.config/pushscan2folder/config.toml` falls vorhanden | alle | TOML-Konfigurationsdatei, siehe [Konfigurationsdatei](#konfigurationsdatei) |
| `--printer`    | `PUSHSCAN_PRINTER`    | (erforderlich)      | alle          | IP oder Hostname des Druckers |
| `--name`       | `PUSHSCAN_NAME`       | `USER  HOSTNAME`    | alle          | Name auf dem Bedienfeld, siehe [Namen auf dem Bedienfeld](#namen-auf-dem-bedienfeld). Der Standardwert ersetzt Zeichen, die das Bedienfeld nicht anzeigen kann, durch `-` |
| `-v/--verbose` | `PUSHSCAN_VERBOSE`    | aus                 | alle          | Debug-Protokollierung. Die Umgebungsvariable aktiviert sie mit `1`, `true` oder `yes` |
| `--output`     | `PUSHSCAN_OUTPUT`     | `./scans`           | run, scan     | Ausgabeverzeichnis (wird bei Bedarf angelegt) |
| `--interval`   | `PUSHSCAN_INTERVAL`   | `4`                 | run           | Abfrageintervall in Sekunden |
| `--format`     | `PUSHSCAN_FORMAT`     | `pdf`               | run (Umgebung: nur run) | `pdf` oder `jpeg`. Ersatzwert, siehe [Einstellungen vom Bedienfeld](#einstellungen-vom-bedienfeld) |
| `--color`      | `PUSHSCAN_COLOR`      | `color`             | run           | `color` oder `gray`. Nur mit `--ignore-panel` oder wenn das Bedienfeld keine Farbe sendet |
| `--resolution` | `PUSHSCAN_RESOLUTION` | `300`               | run           | DPI. Ersatzwert. Das Bedienfeld bietet 75, 150, 300, 600 |
| `--source`     | `PUSHSCAN_SOURCE`     | `auto`              | run (Umgebung: nur run) | `auto`, `platen` oder `adf`. Ersatzwert |
| `--trim`       | `PUSHSCAN_TRIM`       | keiner              | run           | Rand abschneiden, indem ein kleinerer Bereich gescannt wird, z. B. `right=1,bottom=2` (Schlüssel `left`, `top`, `right`, `bottom`, in mm, 0 bis 50). Nur Vorlagenglas. Ersetzt die `trim_*`-Werte der Konfigurationsdatei als Ganzes, siehe [Rand abschneiden](#rand-abschneiden) |
| `--adf-trim`   | `PUSHSCAN_ADF_TRIM`   | keiner              | run           | Rand bei Scans vom Dokumenteneinzug (ADF) abschneiden, indem ein kleinerer Bereich gescannt wird, gleiche Syntax wie `--trim`. Ersetzt die `adf_trim_*`-Werte der Konfigurationsdatei als Ganzes, siehe [Rand abschneiden](#rand-abschneiden) |
| `--targets`    | `PUSHSCAN_TARGETS`    | -                   | run           | Mehrere Einträge auf dem Bedienfeld, jeder mit eigenem Ordner und optionaler Voreinstellung, siehe [Mehrere Ziele](#mehrere-ziele). Ersetzt `--name` für `run` |
| `--ignore-panel` | `PUSHSCAN_IGNORE_PANEL` | aus             | run           | Ignoriert die Einstellungen vom Bedienfeld und nutzt immer die vier Optionen oben (`--format`, `--color`, `--resolution`, `--source`). Umgebungsvariable: `1`, `true` oder `yes`. Deaktiviert auch mehrseitige Scans |
| `--multipage`  | `PUSHSCAN_MULTIPAGE`  | `document`          | run           | `document`, `auto`, `both` oder `off`, siehe [Mehrseitige Scans](#mehrseitige-scans-vom-vorlagenglas) |
| `--open-after-scan` | `PUSHSCAN_OPEN_AFTER_SCAN` | `false`     | run, start    | `true` oder `false` (auch `yes`/`no`, `1`/`0`, `on`/`off`; die alten `folder` und `file` zählen als `true`). Nur für Desktop-PCs: nach dem Speichern eines Auftrags den Ordner öffnen (Windows: Explorer mit markierter neuer Datei), einmal pro Auftrag. Unter Linux ist `DISPLAY` oder `WAYLAND_DISPLAY` nötig. Ein Fehler schreibt nur eine Warnung. Docker hat keinen Desktop, dort `false` lassen (sonst eine Warnung beim ersten Auftrag) |
| `--filename`   | `PUSHSCAN_FILENAME`   | `scan_{now:%Y%m%d_%H%M%S}` | run    | Vorlage für den Dateinamen eines Scans, ohne Endung, siehe [Dateinamen](#dateinamen) |
| `--heartbeat-file` | `PUSHSCAN_HEARTBEAT_FILE` | -          | run, health   | Datei, die `run` nach jedem erfolgreichen Kontakt mit dem Drucker berührt und die `health` prüft. Das Docker-Image setzt sie, siehe [Docker](docker.de.md#healthcheck) |
| `--max-age`    | -                  | `120`               | health        | Sekunden, nach denen `health` die Heartbeat-Datei für zu alt hält |
| `--no-pause`   | `PUSHSCAN_NO_PAUSE`   | aus                 | alle          | Windows: nicht auf Enter warten, bevor sich ein nur für dieses Programm geöffnetes Konsolenfenster schließt. Der Autostart-Eintrag setzt es |
| `--web`        | `PUSHSCAN_WEB`        | aus                 | run           | Stellt die [Weboberfläche](web.de.md) bereit. Umgebungsvariable: `1`, `true` oder `yes` |
| `--web-port`   | `PUSHSCAN_WEB_PORT`   | `8737`              | run           | Port der Weboberfläche |
| `--web-bind`   | `PUSHSCAN_WEB_BIND`   | siehe `[web]` `bind` | run           | Adresse der Weboberfläche |
| -              | `PUSHSCAN_WEB_PASSWORD` / `PUSHSCAN_WEB_PASSWORD_FILE` | (erforderlich mit `--web`, außer die Bind-Adresse ist Loopback) | run | Passwort der Weboberfläche (mind. 8 Zeichen) oder eine Datei, die es enthält. Per Umgebung oder `[web] password_file` der Konfigurationsdatei. Das Passwort selbst nie in der Konfigurationsdatei |
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
steht in [config.example.toml](../config.example.toml).

Ort: `--config PATH` / `PUSHSCAN_CONFIG`; ohne Angabe wird
`$XDG_CONFIG_HOME/pushscan2folder/config.toml` (standardmäßig
`~/.config/pushscan2folder/config.toml`) verwendet, falls es existiert. Ein
ausdrücklich angegebener Pfad muss existieren, sonst beendet sich das Programm
mit einem Fehler.

Unbekannte Schlüssel, falsche Typen und ungültige Werte werden mit einer
Meldung abgelehnt, die Datei und Schlüssel nennt, damit Tippfehler auffallen.

| Schlüssel | Werte | Entspricht |
|-----------|-------|------------|
| `printer` | IP oder Hostname | `--printer` |
| `output` | Ordner; relative Ausgabepfade der Ziele werden darauf bezogen | `--output` |
| `[defaults]` `resolution` | `75`, `150`, `300`, `600` | `--resolution` |
| `[defaults]` `color` | `color`, `gray` | `--color` |
| `[defaults]` `format` | `pdf`, `jpeg` | `--format` |
| `[defaults]` `source` | `auto`, `platen`, `adf` | `--source` |
| `[defaults]` `size` | `a4`, `letter`, `legal`, `10x15`, `13x18` | Scanbereich ohne Daten vom Bedienfeld |
| `[defaults]` `open_after_scan` | `true`, `false` (die alten `"off"`, `"folder"`, `"file"` werden weiter gelesen) | `--open-after-scan` |
| `[defaults]` `filename` | Vorlage, siehe [Dateinamen](#dateinamen) | `--filename` |
| `[defaults.document]` `multipage` | `true` / `false`, eingebaut `true` | `--multipage` (Dokumenttyp *Dokument* am Bedienfeld) |
| `[defaults.auto]` `multipage` | `true` / `false`, eingebaut `false` | `--multipage` (Dokumenttyp *Automatisch* am Bedienfeld) |
| `[advanced]` `interval` | Sekunden | `--interval` |
| `[advanced]` `verbose`, `ignore_panel` | `true` / `false` | `--verbose`, `--ignore-panel` |
| `[advanced]` `trim_left`, `trim_top`, `trim_right`, `trim_bottom` | Zahl, mm, 0 bis 50 | `--trim` |
| `[advanced]` `adf_trim_left`, `adf_trim_top`, `adf_trim_right`, `adf_trim_bottom` | Zahl, mm, 0 bis 50 | `--adf-trim` |
| `[web]` `enabled` | `true` / `false` | `--web` |
| `[web]` `bind` | Adresse; nicht gesetzt: `0.0.0.0`, wenn ein Passwort gesetzt ist, sonst `127.0.0.1` (nur dieser PC). Auf einer Loopback-Adresse (`127.0.0.1`, `::1`, `localhost`) ist kein Passwort nötig | `--web-bind` |
| `[web]` `port` | 1 bis 65535, Standard 8737 | `--web-port` |
| `[web]` `password_file` | Datei mit dem Passwort; relativ zur Konfigurationsdatei. Das Passwort selbst ist nie ein Schlüssel | `PUSHSCAN_WEB_PASSWORD_FILE` |
| `[[target]]` `name` | erforderlich, max. 31 Zeichen, eindeutig | `NAME` |
| `[[target]]` `output` | Ordner; `"."` ist der Ausgabeordner selbst; Standard `<output>/<name>` | `NAME=DIR` |
| `[[target]]` `filename` | Vorlage, siehe [Dateinamen](#dateinamen); gilt vor `[defaults]` für dieses Ziel | - |
| `[[target]]` `open_after_scan` | `true`, `false`; gilt vor `[defaults]` für dieses Ziel, etwa `false` für einen Archivordner | - |
| `[target.document]` `multipage` | `true` / `false` | `mp:` für den Dokumenttyp *Dokument* |
| `[target.auto]` `resolution`, `format`, `size` | wie oben | die `@preset`-Optionen |
| `[target.auto]` `multipage` | `true` / `false` | `mp:` für den Dokumenttyp *Automatisch* |

Die Booleschen Werte eines Ziels für mehrseitige Scans gehen von
`[defaults.document]` und `[defaults.auto]` (oder `--multipage`) aus und ersetzen
den Wert für dieses Ziel. Setzt ein Ziel keinen von beiden, folgt es den
Vorgaben.

Das Bedienfeld kennt drei Dokumenttypen. *Foto* braucht keine Tabelle, denn das
Bedienfeld sendet alle Einstellungen selbst (JPEG, Größe, Auflösung). Bei
*Dokument* sendet es sie ebenfalls, und `[defaults.document]` entscheidet nur
über den Dialog für mehrseitige Scans. Bei *Automatisch* sendet das Bedienfeld
weder Größe noch Format noch Auflösung, daher entscheiden `[defaults]` und
`[target.auto]`.

Fehlt `[defaults.document]` oder `[defaults.auto]`, gilt der eingebaute Wert
(`true` für *Dokument*, `false` für *Automatisch*). Setzt du nur eine der beiden
Tabellen, behält die andere ihren eingebauten Wert.

### Fotos

Beim Dokumenttyp *Foto* bietet das Bedienfeld die Größen *auto scan* und
*auto multi scan* an. Der Drucker sendet immer die ganze Glasfläche, und
pushscan2folder schneidet die Fotos auf dem PC aus:

- *Auto scan* speichert eine Datei mit dem Bereich des Fotos oder der Fotos.
- *Auto multi scan* speichert eine Datei pro Foto, sortiert von oben nach unten
  und dann von links nach rechts.

Das funktioniert mit offenem oder geschlossenem Deckel und nur auf dem Glas
(nicht im Vorlageneinzug). Schiefe Fotos bleiben schief, denn der Ausschnitt ist
ein umschließendes Rechteck ohne Geraderichten. Bei Bedienfeld-Format PDF scannt
das Tool als JPEG, schneidet die Fotos aus und schreibt ein PDF pro Foto.

Zum Ausschneiden braucht es das optionale Python-Paket Pillow. Die Windows-exe
und das Docker-Image enthalten es. Beim Start aus dem Quellcode installierst du
es mit `pip install -r requirements.txt`. Ohne Pillow funktioniert alles wie
bisher und die ganze Glasfläche wird gespeichert; das Log sagt dann "install
Pillow to cut the photos out of the scan".

### Ältere Konfigurationsdateien

Dateien aus früheren Versionen funktionieren weiter. Die alten Schlüssel werden
gelesen, und das Log zeigt eine Warnung, die sie auflistet. Setup und die
Weboberfläche schreiben das neue Layout.

| Alter Ort | Neuer Ort |
|-----------|-----------|
| `interval`, `verbose`, `ignore_panel` auf oberster Ebene | `[advanced]` |
| `trim_*` in `[defaults]` | `[advanced]` |
| `multipage = "document"` (oder `auto`, `both`, `off`) auf oberster Ebene | `multipage` in `[defaults.document]` und `[defaults.auto]` |
| `document_multipage` in einem `[[target]]` | `multipage` in `[target.document]` |

Stehen der alte und der neue Ort desselben Schlüssels gleichzeitig in der Datei,
wird sie mit einer Meldung wie "keep only ..." abgelehnt.

## Vorrang

Kommandozeile > Umgebungsvariable > Konfigurationsdatei > eingebauter
Standardwert.

- Das Docker-Image setzt `PUSHSCAN_OUTPUT=/scans`, daher wird im Container der
  Schlüssel `output` der Datei überschrieben. Binde deine Ordner unterhalb von
  `/scans` ein oder verwende absolute Ausgabepfade bei den Zielen (siehe
  [Docker](docker.de.md)).
- Ist `--targets` / `PUSHSCAN_TARGETS` gesetzt, ersetzt es die
  `[[target]]`-Liste der Datei vollständig.
- Für den Scan selbst kommen die Einstellungen vom Bedienfeld zuerst, die
  CLI-Optionen füllen nur auf, siehe
  [Einstellungen vom Bedienfeld](#einstellungen-vom-bedienfeld) und
  [Voreinstellungen pro Ziel](#voreinstellungen-pro-ziel).

## Datei im laufenden Betrieb ändern

Vor jedem Abfragezyklus, nie während eines Scans, prüft `run` Änderungsdatum
und Größe der Konfigurationsdatei. Hat sie sich geändert, wird sie wie beim
Start neu gelesen. Kommandozeilenoptionen und `PUSHSCAN_*`-Umgebungsvariablen
gelten weiterhin vor der Datei. Das betrifft auch Änderungen von der
[Weboberfläche](web.de.md).

Sofort übernommen werden: die Scan-Vorgaben (Schlüssel in `[defaults]`, `size`,
`filename`, die `multipage`-Schlüssel), `interval`, `ignore_panel` und die
`trim_*`- und `adf_trim_*`-Werte aus `[advanced]`, `open_after_scan`, die Ziele, `output` und `printer`. Ziele, deren Namen
bleiben, behalten ihre Anmeldung am Bedienfeld. Ändert sich der Drucker, werden
die Namen am alten Drucker freigegeben und am neuen angemeldet.

Einen Neustart brauchen: die Weboberfläche an oder aus, ihre Bind-Adresse, der
Port und die Passwortdatei, die Logdatei, das Debug-Log (`verbose` in `[advanced]`) und die
Heartbeat-Datei. Ändert die Datei eine davon, nennt eine Warnung im Log sie.

Eine ungültige Datei oder eine ungültige Dateinamen-Vorlage wird einmal als
Fehler ins Log geschrieben, und die laufenden Einstellungen bleiben. Eine
gelöschte Datei ändert nichts. In Docker funktioniert das, wenn du
`./config/config.toml` auf dem Host bearbeitest.

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
  und werden ignoriert (siehe [Fehlersuche](troubleshooting.de.md#einschränkungen)).
- "Kompaktes PDF" wird als normales PDF mit 300 dpi gescannt.
- TIFF wird nicht unterstützt, weil weder eSCL noch das native Protokoll es
  liefert. Solche Scans werden als JPEG gespeichert.
- Die Größe "Auto" scannt die volle Breite des Vorlagenglases bei A4-Höhe (kein
  automatischer Zuschnitt).
- Die Auflösungen 75/150/300/600 dpi vom Bedienfeld funktionieren alle über
  eSCL, obwohl die eSCL-Fähigkeiten nur 75, 100, 150, 200, 600 und 1200 auflisten.
- Wird ein Scan am Bedienfeld abgebrochen, bleibt ein unvollständiges Dokument
  zurück. Das Tool erkennt das und verwirft es, es wird also nichts gespeichert.

## Rand abschneiden

Manche Scanner erfassen am Rand des Vorlagenglases einen dünnen Streifen. Der
TR8550 entfernten laut Tests `trim_right = 1` und `trim_bottom = 2` (mm) den
Rand. Mit `--trim right=1,bottom=2` (oder `PUSHSCAN_TRIM`, oder den
`trim_*`-Schlüsseln in der Tabelle `[advanced]` der Konfigurationsdatei) fordert das Tool beim Drucker einen kleineren
Scanbereich an, sodass der Rand gar nicht erst gescannt wird. Es gibt keine
Bildverarbeitung. Der Zuschnitt mit `trim_*` gilt nur für das Vorlagenglas. Scans vom
Dokumenteneinzug haben eigene Werte: `--adf-trim` (oder `PUSHSCAN_ADF_TRIM`, oder
die `adf_trim_*`-Schlüssel in `[advanced]`), mit gleicher Syntax und gleichen
Grenzen, standardmäßig 0. Der TR8550 hält den kleineren Bereich auch am Einzug
ein. Der Einzug zieht eine Seite manchmal leicht schräg ein, dann kann ein
Zuschnitt dort etwas von der Seite abschneiden. Lass ihn auf 0, solange der
Rand nicht stört. Bliebe in einer Richtung weniger als 1 Zoll übrig, wird der
Zuschnitt übersprungen und eine Warnung ins Log geschrieben. Die Einstellung ist
global, nicht pro Ziel.

## Mehrseitige Scans vom Vorlagenglas

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
bekommen. In der Konfigurationsdatei dienen dafür `multipage` in
`[defaults.document]` (eingebaut `true`) und `[defaults.auto]` (eingebaut
`false`):

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

## Einzugsfach (ADF)

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
  aufgelöst, ein absolutes unverändert verwendet. `.` ist `--output` selbst, ohne Unterordner.

Namen müssen eindeutig sein und die [Regeln für Namen auf dem Bedienfeld](#namen-auf-dem-bedienfeld)
einhalten. Zwei Ziele dürfen sich keinen Ordner teilen (`a b` und `a_b`
ergeben beide `a_b`, zum Beispiel). Alle Namen teilen sich eine Abfrageschleife,
daher gilt das Abfrageintervall für die ganze Liste.

## Namen auf dem Bedienfeld

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

## Voreinstellungen pro Ziel

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
`- /path/to/paperless/consume:/scans/Paperless` (siehe
[Docker](docker.de.md#paperless-ngx)), und nutzt das Ziel
`Paperless@300dpi`. Ordner innerhalb des Ausgabeordners lassen sich auch
auf der [Weboberfläche](web.de.md) wählen. Ein absoluter Pfad wie `Paperless=/consume`
funktioniert ebenfalls, aber nur über die Kommandozeile oder die
Konfigurationsdatei.

## Dateinamen

Die Vorlage für den Namen einer Scan-Datei legst du mit `filename` in
`[defaults]`, mit `--filename` oder mit `PUSHSCAN_FILENAME` fest. Ein
`filename` in einem `[[target]]` gilt nur für dieses Ziel und hat Vorrang vor
den anderen Einstellungen. Sonst gilt der übliche Vorrang (siehe
[Vorrang](#vorrang)). Auf der [Weboberfläche](web.de.md#seiten) hat die
Einstellungsseite ein Feld "File name".

Der Standard ist `scan_{now:%Y%m%d_%H%M%S}`. Er ergibt dieselben Namen wie
bisher, zum Beispiel `scan_20261122_183005.pdf`. Die Vorlage hat keine Endung,
denn die Endung kommt vom Format (`.pdf` oder `.jpg`).

| Feld | Bedeutung | Beispiel |
|------|-----------|----------|
| `{name}` | der Name vom Bedienfeld, als Dateiname tauglich gemacht | `My PC` ergibt `My_PC` |
| `{date}` | das Datum | `2026-11-22` |
| `{time}` | die Uhrzeit | `183005` |
| `{now:FORMAT}` | Datum und Uhrzeit mit Python-`strftime`-Codes | `{now:%Y%m%d_%H%M%S}` ergibt `20261122_183005` |

```toml
[defaults]
filename = "{name}_{date}_{time}"     # My_PC_2026-11-22_183005.pdf

[[target]]
name = "Paperless"
filename = "scan_{now:%Y%m%d_%H%M%S}"   # dieses Ziel behält den Standardstil
```

Weitere Felder gibt es nicht. Attributzugriff wie `{now.year}` und
Positionsfelder wie `{}` werden abgelehnt, ebenso eine Vorlage, die einen
leeren Namen ergibt. Das Programm prüft die Vorlage beim Start, ein Fehler
stoppt es also mit einer Meldung und nicht mitten in einem Scan.

Das Ergebnis wird für das Dateisystem bereinigt:

- Zeichen, die Windows in Dateinamen nicht erlaubt (`<>:"/\|?*` und
  Steuerzeichen), werden auf jedem System zu `_`. Leerzeichen und Punkte am
  Anfang und am Ende fallen weg.
- Der Name wird auf 120 Zeichen gekürzt.
- Ein Gerätename wie `CON` bekommt ein `_` davor, wie bei den
  [Ordnernamen](windows.de.md#wo-liegt-was) unter Windows.
- Ein Auftrag mit mehreren JPEG-Dateien bekommt `_01`, `_02` und so weiter nach
  dem Namen.
- Eine vorhandene Datei wird nie überschrieben. Stattdessen wird `-1`, `-2` und
  so weiter an den Namen gehängt, zum Beispiel `scan_20261122_183005-1.pdf`.

Der Ziel-Editor auf der Weboberfläche hat kein Feld für die Vorlage eines
Ziels. Beim Speichern der Ziele auf der Weboberfläche bleibt das `filename`
erhalten, das ein Ziel in der Datei hat.
