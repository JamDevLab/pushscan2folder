# Konfiguration

[English](configuration.md) | Deutsch

Zurück zur [README](../README.de.md).

- [Unterbefehle](#unterbefehle)
- [Optionen](#optionen)
- [Konfigurationsdatei](#konfigurationsdatei)
- [Vorrang](#vorrang)
- [Einstellungen vom Bedienfeld](#einstellungen-vom-bedienfeld)
- [Rand abschneiden](#rand-abschneiden)
- [Mehrseitige Scans vom Vorlagenglas](#mehrseitige-scans-vom-vorlagenglas)
- [Einzugsfach (ADF)](#einzugsfach-adf)
- [Mehrere Ziele](#mehrere-ziele)
- [Namen auf dem Bedienfeld](#namen-auf-dem-bedienfeld)
- [Voreinstellungen pro Ziel](#voreinstellungen-pro-ziel)

## Unterbefehle

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
| `--trim`       | `PUSHSCAN_TRIM`       | keiner              | run           | Rand abschneiden, indem ein kleinerer Bereich gescannt wird, z. B. `right=3,bottom=2` (Schlüssel `left`, `top`, `right`, `bottom`, in mm, 0 bis 50). Nur Vorlagenglas. Ersetzt die `trim_*`-Werte der Konfigurationsdatei als Ganzes, siehe [Rand abschneiden](#rand-abschneiden) |
| `--targets`    | `PUSHSCAN_TARGETS`    | -                   | run           | Mehrere Einträge auf dem Bedienfeld, jeder mit eigenem Ordner und optionaler Voreinstellung, siehe [Mehrere Ziele](#mehrere-ziele). Ersetzt `--name` für `run` |
| `--ignore-panel` | `PUSHSCAN_IGNORE_PANEL` | aus             | run           | Ignoriert die Einstellungen vom Bedienfeld und nutzt immer die vier Optionen oben (`--format`, `--color`, `--resolution`, `--source`). Umgebungsvariable: `1`, `true` oder `yes`. Deaktiviert auch mehrseitige Scans |
| `--multipage`  | `PUSHSCAN_MULTIPAGE`  | `document`          | run           | `document`, `auto`, `both` oder `off`, siehe [Mehrseitige Scans](#mehrseitige-scans-vom-vorlagenglas) |
| `--web`        | `PUSHSCAN_WEB`        | aus                 | run           | Stellt die [Weboberfläche](web.de.md) bereit. Umgebungsvariable: `1`, `true` oder `yes` |
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
TR8550 zeigt anscheinend etwa 3 mm rechts und 2 mm unten (noch zu prüfen). Mit
`--trim right=3,bottom=2` (oder `PUSHSCAN_TRIM`, oder den `trim_*`-Schlüsseln in
der Konfigurationsdatei) fordert das Tool beim Drucker einen kleineren
Scanbereich an, sodass der Rand gar nicht erst gescannt wird. Es gibt keine
Bildverarbeitung. Der Zuschnitt gilt nur für das Vorlagenglas, ADF-Scans werden
nicht zugeschnitten. Bliebe in einer Richtung weniger als 1 Zoll übrig, wird der
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
  aufgelöst, ein absolutes unverändert verwendet.

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
