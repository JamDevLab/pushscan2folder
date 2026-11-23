# Konfiguration

[English](configuration.md) | Deutsch

Zurück zur [README](../README.de.md).

- [Unterbefehle](#unterbefehle)
- [Optionen](#optionen)
- [Konfigurationsdatei](#konfigurationsdatei)
- [Was das Bedienfeld entscheidet](#was-das-bedienfeld-entscheidet)
- [Schlüssel](#schlüssel)
- [Dialog für die nächste Seite](#dialog-für-die-nächste-seite)
- [Ordner](#ordner)
- [Datumsfelder in Ordnern](#datumsfelder-in-ordnern)
- [Dokumenttyp Auto](#dokumenttyp-auto)
- [Rand abschneiden](#rand-abschneiden)
- [Die Datei prüfen](#die-datei-prüfen)
- [Vorrang](#vorrang)
- [Datei im laufenden Betrieb ändern](#datei-im-laufenden-betrieb-ändern)
- [Einstellungen vom Bedienfeld](#einstellungen-vom-bedienfeld)
- [Einzugsfach (ADF)](#einzugsfach-adf)
- [Mehrere Ziele](#mehrere-ziele)
- [Namen auf dem Bedienfeld](#namen-auf-dem-bedienfeld)
- [Dateinamen](#dateinamen)

## Unterbefehle

Ohne Unterbefehl wird `run` genommen: `pushscan2folder --printer 192.168.1.50`
entspricht `pushscan2folder --printer 192.168.1.50 run`. Globale Optionen
(`--config`, `--printer`, `--name`, `--log-file`, `--verbose`) stehen vor dem
Unterbefehl; Optionen von `run` wie `--folder` gehen auch ohne ihn.

Dienst starten:

```sh
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 run --folder ./scans
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

Die Konfigurationsdatei prüfen, ohne den Dienst zu starten (siehe
[Die Datei prüfen](#die-datei-prüfen)):

```sh
PYTHONPATH=src python3 -m pushscan2folder check
```

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
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 scan --folder ./scans
```

## Optionen

Globale Optionen stehen vor dem Unterbefehl. Die Kommandozeile hat Vorrang vor
der Umgebung, und die Umgebung hat Vorrang vor der
[Konfigurationsdatei](#konfigurationsdatei). Mehr unter [Vorrang](#vorrang).
Außer beim Debug-Befehl `scan` gibt es keine Optionen für Scan-Einstellungen
wie Format, Auflösung, Farbe und Quelle. Sie kommen vom Bedienfeld und aus der
Konfigurationsdatei, siehe
[Was das Bedienfeld entscheidet](#was-das-bedienfeld-entscheidet).

| Option         | Umgebungsvariable  | Standard            | Gilt für      | Beschreibung |
|----------------|--------------------|---------------------|---------------|--------------|
| `--config`     | `PUSHSCAN_CONFIG`     | `~/.config/pushscan2folder/config.toml` falls vorhanden | alle | TOML-Konfigurationsdatei, siehe [Konfigurationsdatei](#konfigurationsdatei) |
| `--printer`    | `PUSHSCAN_PRINTER`    | (erforderlich)      | alle          | IP oder Hostname des Druckers |
| `--name`       | `PUSHSCAN_NAME`       | `USER  HOSTNAME`    | alle          | Name auf dem Bedienfeld, siehe [Namen auf dem Bedienfeld](#namen-auf-dem-bedienfeld). Wird genommen, wenn die Konfigurationsdatei kein `[[target]]` hat. Der Standard ersetzt Zeichen, die das Bedienfeld nicht anzeigen kann, durch `-` |
| `-v/--verbose` | `PUSHSCAN_VERBOSE`    | aus                 | alle          | Debug-Protokoll. Die Variable schaltet es mit `1`, `true` oder `yes` ein |
| `--folder`     | `PUSHSCAN_FOLDER`     | `folder` der Datei, sonst `./scans` | run, start, scan | Basisordner aller Ziele (wird angelegt, falls er fehlt) |
| `--heartbeat-file` | `PUSHSCAN_HEARTBEAT_FILE` | -          | run, start, health | Datei, die `run` nach jedem erfolgreichen Kontakt mit dem Drucker berührt und die `health` prüft. Das Docker-Image setzt sie, siehe [Docker](docker.de.md#healthcheck) |
| `--max-age`    | -                  | `120`               | health        | Sekunden, nach denen `health` die Heartbeat-Datei für zu alt hält |
| `--no-pause`   | `PUSHSCAN_NO_PAUSE`   | aus                 | alle          | Windows: nie auf Enter warten, bevor sich ein für dieses Programm geöffnetes Konsolenfenster schließt. Der Autostart-Eintrag setzt sie |
| `--web`        | `PUSHSCAN_WEB`        | aus                 | run, start    | Die [Weboberfläche](web.de.md) bereitstellen. Variable: `1`, `true` oder `yes` |
| `--web-port`   | `PUSHSCAN_WEB_PORT`   | `8737`              | run, start    | Port der Weboberfläche |
| `--web-bind`   | `PUSHSCAN_WEB_BIND`   | siehe `[web]` `bind` | run, start   | Adresse der Weboberfläche |
| -              | `PUSHSCAN_WEB_PASSWORD` / `PUSHSCAN_WEB_PASSWORD_FILE` | (erforderlich mit `--web`, außer die Bind-Adresse ist Loopback) | run | Passwort der Weboberfläche (mind. 8 Zeichen) oder eine Datei damit. Umgebung, oder `[web] password_file` der Konfigurationsdatei. Nie das Passwort selbst in der Konfigurationsdatei |
| `--keep`       | -                  | aus                 | probe         | Die Sitzung nicht freigeben |

Der Unterbefehl `scan` (ein Scan über eSCL ohne Bedienfeld) hat eigene
Optionen: `--folder`, `--format` (`pdf` oder `jpeg`, Standard `pdf`), `--color`
(`color` oder `gray`, Standard `color`), `--resolution` (Standard 300) und
`--source` (`auto`, `platen` oder `adf`, Standard `auto`). Er nutzt dafür keine
Einstellungen der Konfigurationsdatei.

## Konfigurationsdatei

Statt einer langen Kommandozeile hältst du die Einstellungen in einer TOML-Datei
(dafür braucht es Python 3.11 wegen `tomllib`). Ein kommentiertes Beispiel steht
in [config.example.toml](../config.example.toml). Jeder Schlüssel ist optional.

Ort: `--config PFAD` / `PUSHSCAN_CONFIG`; ohne Angabe wird
`$XDG_CONFIG_HOME/pushscan2folder/config.toml` (Standard
`~/.config/pushscan2folder/config.toml`) genommen, falls es existiert. Ein
ausdrücklich angegebener Pfad muss existieren, sonst endet das Programm mit
einem Fehler.

Unbekannte Schlüssel, falsche Typen und ungültige Werte werden mit einer
Meldung abgelehnt, die Datei und Schlüssel nennt, damit Tippfehler auffallen.
Schlüssel früherer Versionen werden nicht mehr gelesen, die Umbenennungen
stehen im [Changelog](../CHANGELOG.md).

Eine kleine Datei mit zwei Zielen:

```toml
printer = "192.168.1.50"
folder = "/scans"

[[target]]
name = "Scans"

[[target]]
name = "Paperless"
next_page = ["document", "auto"]
```

Tabellen in geschweiften Klammern wie `auto = { ... }` und `trim = { ... }`
müssen in einer Zeile stehen. TOML erlaubt darin keinen Zeilenumbruch.

## Was das Bedienfeld entscheidet

Das Bedienfeld des Druckers schickt seine Auswahl mit jeder Scan-Anfrage mit,
und das Programm folgt ihr:

- Die Farbe ist die Starttaste, die du drückst (Farbe oder Schwarzweiß).
- Die Quelle ist das Einzugsfach, wenn Papier darin liegt, sonst das
  Vorlagenglas.
- Bei den Dokumenttypen *Dokument* und *Foto* schickt das Bedienfeld außerdem
  Größe, Format und Auflösung.

Für diese beiden Typen gibt es in der Konfigurationsdatei also keine Schlüssel
für Farbe, Quelle, Größe, Format oder Auflösung. Die Datei bestimmt, was das
Bedienfeld nicht schickt:

- die Ordner, die Dateinamen und ob eine fertige Datei geöffnet wird,
- welche Dokumenttypen den [Dialog für die nächste Seite](#dialog-für-die-nächste-seite)
  bekommen, auf dem Glas und auf Wunsch nach dem Einzug,
- die Einstellungen des Dokumenttyps *Auto*, bei dem das Bedienfeld weder
  Größe noch Format noch Auflösung schickt ([Dokumenttyp Auto](#dokumenttyp-auto)),
- den abgeschnittenen Rand ([Rand abschneiden](#rand-abschneiden)).

## Schlüssel

Oberste Ebene:

| Schlüssel | Typ | Standard | Bedeutung |
|-----------|-----|----------|-----------|
| `printer` | Text | keiner (erforderlich, hier oder per `--printer`) | IP oder Hostname des Druckers |
| `folder` | Text | `./scans`, unter Windows und macOS `Documents/Scans` | Basisordner; relative Zielordner beziehen sich darauf, siehe [Ordner](#ordner) |
| `filename` | Text | `scan_{now:%Y%m%d_%H%M%S}` | Vorlage des Dateinamens ohne Endung, siehe [Dateinamen](#dateinamen) |
| `next_page` | Liste aus `"document"`, `"auto"`, `"photo"` | `["document"]` | Dokumenttypen, die auf dem Vorlagenglas den Dialog für die nächste Seite bekommen, siehe [Dialog für die nächste Seite](#dialog-für-die-nächste-seite). `[]` heißt keiner |
| `feeder_next_page` | Liste aus `"document"`, `"auto"`, `"photo"` | `[]` | Dokumenttypen, die nach einem Scan aus dem Einzug den Dialog für die nächste Seite bekommen, siehe [Dialog nach dem Einzug](#dialog-nach-dem-einzug). `[]` heißt keiner |
| `auto` | Inline-Tabelle | `{ resolution = 300, format = "pdf", size = "a4" }` | Einstellungen für den Dokumenttyp *Auto*, siehe [Dokumenttyp Auto](#dokumenttyp-auto) |
| `open_after_scan` | `true` / `false` | `false` | nur Desktop-PC: nach dem Speichern eines Auftrags den Ordner öffnen (Windows: Explorer mit markierter neuer Datei), einmal pro Auftrag. Unter Linux braucht es `DISPLAY` oder `WAYLAND_DISPLAY`. Ein Fehler erzeugt nur eine Warnung. Docker hat keinen Desktop, lass es `false` (sonst eine Warnung beim ersten Auftrag) |

`[advanced]`, selten nötig:

| Schlüssel | Typ | Standard | Bedeutung |
|-----------|-----|----------|-----------|
| `interval` | Zahl | `4` | Sekunden zwischen den Abfragen |
| `verbose` | `true` / `false` | `false` | Debug-Protokoll, braucht einen Neustart |
| `trim` | Inline-Tabelle | keine | Rand, der bei Scans vom Vorlagenglas abgeschnitten wird, Schlüssel `left`, `top`, `right`, `bottom`, mm, 0 bis 50, siehe [Rand abschneiden](#rand-abschneiden) |
| `adf_trim` | Inline-Tabelle | keine | dasselbe für Scans aus dem Einzugsfach |

`[web]`, siehe [Weboberfläche](web.de.md):

| Schlüssel | Typ | Standard | Bedeutung |
|-----------|-----|----------|-----------|
| `enabled` | `true` / `false` | `false` | die Weboberfläche bereitstellen |
| `bind` | Text | `0.0.0.0`, wenn ein Passwort gesetzt ist, sonst `127.0.0.1` (nur dieser PC) | Adresse der Weboberfläche. Bei einer Loopback-Adresse (`127.0.0.1`, `::1`, `localhost`) braucht es kein Passwort |
| `port` | 1 bis 65535 | `8737` | Port der Weboberfläche |
| `password_file` | Text | keine | Datei mit dem Passwort, relativ zur Konfigurationsdatei. Das Passwort selbst ist nie ein Schlüssel |

`[[target]]`, ein Block pro Eintrag auf dem Bedienfeld:

| Schlüssel | Typ | Standard | Bedeutung |
|-----------|-----|----------|-----------|
| `name` | Text | erforderlich | Name auf dem Bedienfeld, höchstens 31 Zeichen, eindeutig, siehe [Namen auf dem Bedienfeld](#namen-auf-dem-bedienfeld) |
| `folder` | Text | der Name des Ziels | Ordner der Scans; `"."` ist der Basisordner selbst. Datumsfelder sind erlaubt, siehe [Ordner](#ordner) |
| `document_folder`, `auto_folder`, `photo_folder` | Text | `folder` | anderer Ordner für Scans eines Dokumenttyps |
| `filename` | Text | `filename` der obersten Ebene | Vorlage des Dateinamens für dieses Ziel |
| `next_page` | Liste | `next_page` der obersten Ebene | ersetzt die globale Liste für dieses Ziel |
| `feeder_next_page` | Liste | `feeder_next_page` der obersten Ebene | ersetzt die globale Liste für dieses Ziel |
| `auto` | Inline-Tabelle | `auto` der obersten Ebene | hier gesetzte Schlüssel gelten vor dem globalen `auto`, die anderen bleiben |
| `open_after_scan` | `true` / `false` | Wert der obersten Ebene | für dieses Ziel, zum Beispiel `false` für einen Archivordner |

## Dialog für die nächste Seite

Bei Scans vom Vorlagenglas kann der Drucker nach jeder Seite einen Dialog
zeigen: *Stopp*, *Schwarzweiß*, *Farbe* und *Fertig*. Lege die nächste Seite auf
das Glas und drücke *Farbe* oder *Schwarzweiß*, um sie zu scannen (jede Seite
kann ihren eigenen Farbmodus haben), oder *Fertig*, um zu beenden. Alle Seiten
werden als ein PDF gespeichert (bei Format JPEG: eine Datei pro Seite).

Dafür wird Canons eigenes Scanner-Protokoll (`/canon/ij/command2/port3`) statt
eSCL benutzt, denn nur dieses Protokoll kennt die Frage nach der nächsten Seite.
Der Drucker liefert jede Seite als JPEG; das PDF bettet die JPEGs unverändert
ein.

`next_page` listet die Dokumenttypen, die den Dialog bekommen. Der Standard ist
`["document"]`, wie bei der offiziellen Software. Ein Ziel kann eine eigene
Liste setzen, und `next_page = []` schaltet den Dialog aus.

```toml
next_page = ["document", "auto"]       # auch bei Auto fragen
```

Das Einzugsfach scannt standardmäßig alle Seiten in einem Rutsch über eSCL, ohne
Dialog. Einen optionalen Dialog nach dem Einzug beschreibt der nächste Abschnitt.

Bei *Foto* erscheint der Dialog nur für feste Fotogrößen. Bei den Größen *Auto
Scan* und *Auto Multi Scan* schickt der Drucker das ganze Glas, und die Fotos
werden stattdessen am PC ausgeschnitten (siehe [Fotos](#fotos)). `"photo"` in
der Liste wirkt bei diesen beiden Größen deshalb nicht.

Geprüft mit A4 bei 300 dpi; andere Auflösungen und Größen nutzen dieselben
Parameter, sind aber noch nicht getestet. Bei *Auto* schickt das Bedienfeld
weder Auflösung noch Format, es gelten also die `auto`-Einstellungen. Der
Drucker kann den Dokumenttyp nach einem Scan auf *Auto* zurücksetzen, prüfe ihn
also vor dem nächsten mehrseitigen Scan.

### Dialog nach dem Einzug

Der Einzug zieht manchmal zwei Blätter auf einmal ein. Mit `feeder_next_page`
zeigt das Bedienfeld nach dem Scan aus dem Einzug denselben Dialog, sodass du die
Seitenzahl prüfen und ein Blatt neu einlegen kannst, bevor die Datei gespeichert
wird. Der Schlüssel hat dieselbe Form wie `next_page`: eine Liste von
Dokumenttypen aus `"document"`, `"auto"` und `"photo"`. Der Standard ist `[]`
(aus). Die Liste eines Ziels ersetzt die globale.

```toml
feeder_next_page = ["document"]
```

Liegt Papier im Einzug und der Dokumenttyp steht in der Liste, scannt das
Programm den Einzug über eSCL und zeigt dann den Dialog. Für weitere Blätter
legst du sie zuerst in den Einzug und drückst dann *Farbe* oder *Schwarzweiß*.
Der Einzug wird in dieser Farbe erneut gescannt. *Fertig* beendet den Auftrag.
Alle Seiten landen in einem PDF (Format PDF) oder in einzelnen JPEG-Dateien.

Der Drucker zeigt den Dialog nur, nachdem eine Seite mit Canons nativem
Protokoll gescannt wurde. Deshalb scannt das Programm vor jedem Dialog einen
winzigen Blindbereich (1 x 1 Zoll bei 150 dpi) vom Glas und wirft ihn weg. Das
kostet etwa 10 Sekunden pro Runde, und der Scankopf bewegt sich kurz. Was auf dem
Glas liegt, spielt keine Rolle.

Ist der Einzug leer, wenn du mehr wählst, schreibt das Programm eine Warnung ins
Log und fragt erneut. Nach 3 Runden in Folge ohne Seite beendet es den Auftrag.
Stoppst du eine Einzugsrunde am Bedienfeld, endet der Auftrag sofort. Die bisher
gescannten Seiten bleiben immer erhalten.

### Fotos

Beim Dokumenttyp *Foto* bietet das Bedienfeld die Größen *Auto Scan* und *Auto
Multi Scan* an. Der Drucker schickt immer das ganze Glas, und pushscan2folder
schneidet die Fotos am PC aus:

- *Auto Scan* speichert eine Datei mit dem Bereich des Fotos oder der Fotos.
- *Auto Multi Scan* speichert eine Datei pro Foto, geordnet von oben nach unten
  und dann von links nach rechts.

Das geht mit offenem und geschlossenem Deckel und nur auf dem Glas (nicht im
ADF). Schräge Fotos bleiben schräg, weil der Schnitt ein Rechteck ohne
Geraderichten ist. Beim Bedienfeld-Format PDF scannt das Programm als JPEG,
schneidet die Fotos aus und schreibt ein PDF pro Foto.

Das Ausschneiden braucht das optionale Python-Paket Pillow. Die Windows-exe und
das Docker-Image enthalten es. Beim Start aus dem Quellcode installierst du es
mit `pip install -r requirements.txt`. Ohne Pillow funktioniert alles wie
bisher und das ganze Glas wird gespeichert; das Protokoll sagt dann "install
Pillow to cut the photos out of the scan".

## Ordner

`folder` auf der obersten Ebene ist der Basisordner. Jedes `[[target]]` speichert
darunter:

- Ohne `folder` speichert das Ziel in einem Unterordner mit seinem Namen. Zeichen
  außer Buchstaben, Ziffern, `.`, `_` und `-` werden zu `_`.
- Ein relativer `folder` bezieht sich auf den Basisordner, ein absoluter wird
  unverändert benutzt, und `"."` ist der Basisordner selbst.
- `document_folder`, `auto_folder` und `photo_folder` geben einem Dokumenttyp
  einen anderen Ordner, mit denselben Regeln. Ohne sie nimmt der Typ `folder`.

```toml
folder = "/scans"

[[target]]
name = "Paperless"                # /scans/Paperless
photo_folder = "Photos"           # Fotos landen in /scans/Photos

[[target]]
name = "Archive"
folder = "Archive/{now:%Y}"       # /scans/Archive/2026
```

Zwei Ziele dürfen sich keinen Ordner teilen (`a b` und `a_b` ergeben zum
Beispiel beide `a_b`). Das Docker-Image setzt `PUSHSCAN_FOLDER=/scans`, siehe
[Vorrang](#vorrang).

## Datumsfelder in Ordnern

Die Ordner eines Ziels (`folder` und die drei Typ-Ordner) dürfen dieselben Felder
enthalten wie die [Dateinamen](#dateinamen): `{name}` (der Zielname), `{date}`
(`2026-11-22`), `{time}` (`183005`) und `{now:FORMAT}` mit Python-`strftime`-Codes.
Die Felder werden beim Speichern eines Scans ausgefüllt, so kann der Ordner nach
Jahr oder Monat wechseln, ohne dass du die Datei änderst.

```toml
folder = "Archive/{now:%Y}/{now:%m}"    # Archive/2026/11
```

Der Wert eines Felds ist immer ein einzelner Teil des Ordnernamens. Ein Feld
fügt nie einen Pfadtrenner oder `..` ein: ein Format wie `{now:%d/%m}` ergibt
`03_11` statt zwei Ordnern. Die Schrägstriche, die du zwischen die Felder
schreibst, sind der einzige Weg zu Unterordnern. Ein falsches Feld wie
`{now.year}` oder `{}` wird beim Lesen der Datei abgelehnt.

## Dokumenttyp Auto

Beim Dokumenttyp *Auto* schickt das Bedienfeld nur Typ, Farbe und Quelle. Die
Tabelle `auto` bestimmt den Rest:

```toml
auto = { resolution = 300, format = "pdf", size = "a4" }
```

| Schlüssel | Werte | Standard |
|-----------|-------|----------|
| `resolution` | `75`, `150`, `300`, `600` | `300` |
| `format` | `"pdf"`, `"jpeg"` | `"pdf"` |
| `size` | `"a4"`, `"letter"`, `"legal"`, `"10x15"`, `"13x18"` | `"a4"` |

Du kannst auch nur einzelne Schlüssel setzen. Ein `[[target]]` kann ein eigenes
`auto` haben; seine Schlüssel gelten vor der globalen Tabelle und die übrigen
bleiben, mit `auto = { format = "jpeg" }` in einem Ziel bleiben also globale
Auflösung und Größe erhalten.

## Rand abschneiden

Manche Scanner erfassen am Rand des Glases einen dünnen Streifen. Beim TR8550
zeigten Tests, dass 1 mm rechts und 2 mm unten ihn entfernen. Mit der Tabelle
`trim` in `[advanced]` fordert das Programm vom Drucker einen kleineren
Scanbereich an, der Rand wird also nie gescannt. Es gibt keine Bildbearbeitung.

```toml
[advanced]
trim = { right = 1, bottom = 2 }     # Vorlagenglas
adf_trim = { }                       # Einzugsfach, standardmäßig 0
```

Die Schlüssel sind `left`, `top`, `right` und `bottom`, in mm von 0 bis 50. Nicht
genannte Seiten bleiben 0. `trim` gilt nur für das Vorlagenglas. Scans aus dem
Einzugsfach haben die eigene Tabelle `adf_trim`, standardmäßig 0. Der TR8550
beachtet den kleineren Bereich auch im Einzugsfach. Das Einzugsfach zieht eine
Seite manchmal leicht schief ein, ein Trim kann dort also ein Stück der Seite
abschneiden; lass die Tabelle leer, solange dich der Rand nicht stört. Bliebe in
einer Richtung weniger als 1 Zoll übrig, wird der Trim übersprungen und eine
Warnung protokolliert. Die Einstellung gilt global, nicht pro Ziel.

## Die Datei prüfen

`pushscan2folder check` liest die Konfigurationsdatei wie `run`, meldet einen
Fehler mit dem betroffenen Schlüssel oder zeigt, was die Datei bewirkt:
Basisordner, Dateinamen, die Einstellungen für *Auto*, den Trim und für jedes
Ziel seine Ordner mit dem heutigen Datum. Es nimmt keinen Kontakt zum Drucker
auf. Führe es nach jeder Änderung der Datei aus. Die Ausgabe für
[config.example.toml](../config.example.toml):

```
$ pushscan2folder --config config.example.toml check
config file: config.example.toml
printer: 192.168.1.50
base folder: /scans
file names: scan_{now:%Y-%m-%d_%H-%M-%S}
next page dialog: document
next page dialog after the feeder: none
document type Auto: 300 dpi, pdf, a4
trim: glass right 1 mm, bottom 2 mm; feeder none
open after scan: no
poll interval: 4 s
target 'Scans':
  folder: /scans/Scans
target 'Paperless':
  folder: /scans/Paperless
  photo scans: /scans/Photos
  next page dialog: document, auto
target 'Archive':
  folder: /scans/Archive/2026
  next page dialog: none
  next page dialog after the feeder: document
  document type Auto: 600 dpi, jpeg, a4
OK
```

Der Exit-Code ist 0, wenn die Datei benutzt werden kann, sonst 2, auch wenn kein
Drucker gesetzt ist.

## Vorrang

Kommandozeile > Umgebungsvariable > Konfigurationsdatei > eingebauter Standard.

Von den Schlüsseln der Datei lassen sich nur `printer` und `folder` so
überschreiben (durch `--printer` / `PUSHSCAN_PRINTER` und `--folder` /
`PUSHSCAN_FOLDER`), dazu die Web-Optionen aus `[web]` und `verbose`. Alles
andere wird nur in der Datei gesetzt.

- Das Docker-Image setzt `PUSHSCAN_FOLDER=/scans`, daher wird im Container der
  Schlüssel `folder` der Datei überschrieben. Binde deine Ordner unterhalb von
  `/scans` ein oder nimm absolute Zielordner (siehe [Docker](docker.de.md)).
- Für den Scan selbst hat das Bedienfeld Vorrang, die Tabelle `auto` füllt nur
  beim Dokumenttyp *Auto* auf, siehe
  [Einstellungen vom Bedienfeld](#einstellungen-vom-bedienfeld).

## Datei im laufenden Betrieb ändern

Vor jedem Abfragezyklus, nie während eines Scans, prüft `run` Änderungszeit und
Größe der Konfigurationsdatei. Hat sie sich geändert, wird sie wie beim Start
neu gelesen. Kommandozeilen-Optionen und die Variablen `PUSHSCAN_FOLDER` und
`PUSHSCAN_PRINTER` haben weiter Vorrang vor der Datei. Das gilt auch für
Änderungen auf der [Weboberfläche](web.de.md).

Sofort übernommen werden: `folder`, `filename`, `next_page`, `feeder_next_page`, `auto`,
`open_after_scan`, `interval`, `trim` und `adf_trim`, die Ziele und `printer`.
Ziele, deren Namen bleiben, behalten ihre Anmeldung am Bedienfeld. Ändert sich
der Drucker, werden die Namen am alten Drucker freigegeben und am neuen
angemeldet.

Einen Neustart brauchen: die Weboberfläche an oder aus, ihre Bind-Adresse, Port
und Passwortdatei, die Protokolldatei, das Debug-Protokoll (`verbose` in
`[advanced]`) und die Heartbeat-Datei. Ändert die Datei eines davon, zeigt das
Protokoll eine Warnung, die es nennt.

Eine ungültige Datei oder eine ungültige Dateinamen-Vorlage wird einmal als
Fehler protokolliert, und die laufenden Einstellungen bleiben. Eine gelöschte
Datei ändert nichts. In Docker klappt das, wenn du `./config/config.toml` auf dem
Host bearbeitest.

## Einstellungen vom Bedienfeld

Der Drucker schickt mit jeder Scan-Anfrage 32 Bytes: Dokumenttyp, Farbe, Quelle,
Größe, Format, Auflösung, Durchscheinen, Entrastern und Unscharfmaske. Das
Programm übersetzt sie nach eSCL, der Scan folgt also deiner Auswahl am
Bedienfeld. Nur beim Dokumenttyp *Auto* liefert die
[Tabelle `auto`](#dokumenttyp-auto) Größe, Format und Auflösung.

- Durchscheinen, Entrastern und Unscharfmaske haben kein eSCL-Gegenstück und
  werden ignoriert (siehe [Fehlersuche](troubleshooting.de.md#einschränkungen)).
- "Kompaktes PDF" wird als normales PDF mit 300 dpi gescannt.
- TIFF wird nicht unterstützt, weil weder eSCL noch das native Protokoll es
  liefert. Solche Scans werden als JPEG gespeichert.
- Die Größe "Auto" scannt die volle Glasbreite in A4-Höhe (ohne automatisches
  Zuschneiden).
- Die Bedienfeld-Auflösungen 75/150/300/600 dpi funktionieren alle über eSCL,
  obwohl die eSCL-Fähigkeiten nur 75, 100, 150, 200, 600 und 1200 nennen.
- Bricht man einen Scan am Bedienfeld ab, bleibt ein abgeschnittenes Dokument.
  Das Programm erkennt das und verwirft es, es wird also nichts gespeichert.

## Einzugsfach (ADF)

Der Drucker erkennt die Quelle mit seinem Papiersensor; das Bedienfeld bietet
keine Quellenwahl. Legal-Größe gibt es nur aus dem ADF. Das ADF scannt nur
einseitig. Das Programm nimmt das Einzugsfach, wenn Papier darin liegt, sonst
das Vorlagenglas.

## Mehrere Ziele

Eine Instanz kann mehrere Namen am Drucker anmelden. Jeder Name erscheint als
eigener Computer am Bedienfeld, und seine Scans landen in einem eigenen Ordner.
Du legst sie als `[[target]]`-Blöcke in der Konfigurationsdatei fest (oder auf
der [Weboberfläche](web.de.md)):

```toml
folder = "/scans"

[[target]]
name = "Scans"

[[target]]
name = "Paperless"
folder = "consume"

[[target]]
name = "Archive"
folder = "/data/archive"
```

Wie die Ordner aufgelöst werden, steht unter [Ordner](#ordner). Namen müssen
eindeutig sein und die [Regeln für Bedienfeld-Namen](#namen-auf-dem-bedienfeld)
einhalten. Alle Namen teilen sich eine Abfrageschleife, das Intervall gilt also
für die ganze Liste. Ohne `[[target]]` meldet das Programm einen Namen an,
`--name` oder `USER  HOSTNAME`, und speichert im Basisordner.

Für paperless-ngx bindest du dessen Consume-Ordner innerhalb des Basisordners
ein, in Docker zum Beispiel `- /path/to/paperless/consume:/scans/Paperless`
(siehe [Docker](docker.de.md#paperless-ngx)), und nimmst ein Ziel namens
`Paperless`. Ein Ordner innerhalb des Basisordners lässt sich auch auf der
[Weboberfläche](web.de.md) wählen; ein absoluter wie `/consume` geht ebenfalls,
aber nur in der Konfigurationsdatei.

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

## Dateinamen

Die Vorlage für den Namen einer Scan-Datei legst du mit `filename` auf der
obersten Ebene der Konfigurationsdatei fest. Ein `filename` in einem
`[[target]]` gilt nur für dieses Ziel und hat Vorrang vor dem globalen. Auf der
[Weboberfläche](web.de.md#seiten) hat die Einstellungsseite ein Feld "File name".

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
filename = "{name}_{date}_{time}"     # My_PC_2026-11-22_183005.pdf

[[target]]
name = "Paperless"
filename = "scan_{now:%Y%m%d_%H%M%S}"   # dieses Ziel behält den Standardstil
```

Weitere Felder gibt es nicht. Attributzugriff wie `{now.year}` und
Positionsfelder wie `{}` werden abgelehnt, ebenso eine Vorlage, die einen
leeren Namen ergibt. Das Programm prüft die Vorlage beim Start, ein Fehler
stoppt es also mit einer Meldung, statt mitten in einem Scan zu scheitern.

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
