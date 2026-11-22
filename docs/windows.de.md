# Unter Windows nutzen

pushscan2folder läuft unter Windows 10 und 11 nativ als einzelnes Programm, als Alternative zu Canons eigener Scan-Software. Es meldet einen Namen am Display des Druckers an, fragt den Drucker ab und speichert Scans in einen Ordner. Es muss nichts installiert werden.

Linux und Docker stehen in der README. macOS steht am Ende dieser Seite.

## Download

1. Auf der Releases-Seite des Projekts bei GitHub `pushscan2folder.exe` herunterladen (und bei Bedarf `SHA256SUMS.txt`).
2. In einen eigenen Ordner legen, zum Beispiel `C:\Tools\pushscan2folder\`.
3. Zur Kontrolle in PowerShell `Get-FileHash pushscan2folder.exe` ausführen und mit `SHA256SUMS.txt` vergleichen.

Die exe wird von GitHub Actions aus dem getaggten Quellcode gebaut. Sie ist nicht code-signiert.

## Erster Start und SmartScreen

Weil die exe nicht signiert ist, zeigt Windows SmartScreen beim ersten Start "Der Computer wurde durch Windows geschützt". Auf "Weitere Informationen" und dann auf "Trotzdem ausführen" klicken. Wenn du die Datei im Browser geladen hast, geht es auch über Rechtsklick, Eigenschaften, Haken bei "Zulassen".

PowerShell oder Eingabeaufforderung im Ordner öffnen und mit der IP-Adresse des Druckers starten:

```
.\pushscan2folder.exe --printer 192.168.1.50 run
```

Das Log zeigt die Anmeldung. Am Druckerdisplay erscheint unter "Scannen" und "Computer" ein Name wie `BENUTZER  PCNAME`. Auswählen und Start drücken. Gescannt wird nach `Dokumente\Scans` im Benutzerordner. Mit Strg+C beenden; das Programm gibt den Namen am Drucker vorher frei.

Alle Optionen: `.\pushscan2folder.exe --help`.

## Firewall

Das Programm baut nur ausgehende Verbindungen zum Drucker auf. Für das Scannen braucht die Windows-Firewall deshalb keine Regel.

Anders ist es bei der optionalen Webseite. Mit `--web` lauscht das Programm auf einem Port (Standard 8080) und bindet an alle Adressen, wenn du nichts anderes angibst. Windows fragt dann einmal, ob das Programm in privaten oder öffentlichen Netzwerken erlaubt sein soll. Damit die Seite nur auf diesem PC erreichbar ist:

```
.\pushscan2folder.exe --printer 192.168.1.50 run --web --web-bind 127.0.0.1
```

Dann ist nichts für andere Geräte erreichbar und es ist keine Firewall-Regel nötig. Im Browser http://127.0.0.1:8080 öffnen. Die Webseite braucht ein Passwort, das vor dem Start gesetzt wird, zum Beispiel:

```
$env:PUSHSCAN_WEB_PASSWORD = "ein langes eigenes Passwort"
```

Für den Autostart legst du das Passwort in eine Datei und setzt `PUSHSCAN_WEB_PASSWORD_FILE` auf deren Pfad (siehe Dokumentation der Webseite).

## Wo liegt was

| Was | Ort |
| --- | --- |
| Konfigurationsdatei (optional) | `%APPDATA%\pushscan2folder\config.toml` |
| Scans | `Dokumente\Scans` im Benutzerordner (`C:\Users\NAME\Documents\Scans`), je Ziel ein Unterordner |
| Logdatei | nur mit `--log-file PFAD` |

Das Programm sucht die Konfigurationsdatei selbst. Mit `--config PFAD` nimmst du eine andere. Wenn dein Dokumente-Ordner verschoben ist (zum Beispiel durch OneDrive), setze `output` in der Konfigurationsdatei auf den echten Pfad, denn der Standard ist `Documents` unterhalb des Benutzerordners.

Eine neue Konfigurationsdatei, die die Webseite schreibt, soll privat sein. Unter Windows lässt sich der Dateimodus 0600 nicht setzen; die Datei ist durch deinen Benutzerordner geschützt, den andere Standardbenutzer nicht lesen können.

Ordnernamen für Ziele werden Windows-tauglich gemacht: Zeichen wie `<>:"/\|?*` werden zu `_`, Punkte am Ende fallen weg, und reservierte Gerätenamen (`CON`, `PRN`, `AUX`, `NUL`, `COM1` bis `COM9`, `LPT1` bis `LPT9`) bekommen ein `_` davor. Ein Ziel namens `CON` speichert also nach `_CON`.

## Beispielkonfiguration

Speichern unter `%APPDATA%\pushscan2folder\config.toml`. Windows-Pfade in TOML mit Schrägstrich oder in einfachen Anführungszeichen schreiben, weil ein Backslash in einem normalen String ein Escape-Zeichen ist.

```toml
printer = "192.168.1.50"
output = 'D:\Scans'        # einfache Anführungszeichen: Backslashes bleiben wörtlich

[defaults]
resolution = 300
format = "pdf"

[[target]]
name = "Scan"

[[target]]
name = "Paperless"
output = "paperless/inbox"    # unterhalb des Ausgabeordners
```

Danach genügt `.\pushscan2folder.exe run`. Die übrigen Schlüssel stehen in `config.example.toml`.

## Beim Anmelden starten

```
.\pushscan2folder.exe --config "%APPDATA%\pushscan2folder\config.toml" --log-file "%APPDATA%\pushscan2folder\pushscan2folder.log" --install-autostart
```

(In PowerShell `$env:APPDATA` statt `%APPDATA%` schreiben.)

Das legt den Eintrag `pushscan2folder` in der Run-Liste deines Benutzers an (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`). Dafür sind keine Administratorrechte nötig. Bei jeder Anmeldung startet das Programm minimiert in einem Konsolenfenster, mit genau den Optionen, die du neben `--install-autostart` angegeben hast. Pfade werden absolut gespeichert. Eine Aufgabe in der Aufgabenplanung mit Anmelde-Trigger bräuchte auf den meisten Systemen Administratorrechte, deshalb wird die Run-Liste benutzt.

Nutze `--log-file`, sonst gibt es von einem beim Anmelden gestarteten Programm kein sichtbares Log. Die Datei rotiert bei 1 MB und behält 3 alte Dateien.

Die exe danach nicht verschieben oder umbenennen. Sonst den Befehl vom neuen Ort aus wiederholen.

Entfernen:

```
.\pushscan2folder.exe --remove-autostart
```

Du siehst den Eintrag auch im Task-Manager auf dem Tab "Autostart-Apps" oder unter Einstellungen, Apps, Autostart.

## Deinstallieren

1. `pushscan2folder.exe --remove-autostart` ausführen.
2. Die exe löschen.
3. `%APPDATA%\pushscan2folder\` löschen, wenn Konfiguration und Log weg sollen.
4. Deine Scans in `Dokumente\Scans` bleiben, bis du sie löschst.

## Neben Canon IJ Scan Utility

Beide können gleichzeitig installiert sein. Jedes meldet einen eigenen Eintrag am Druckerdisplay an, du siehst also beide Namen in der Liste und wählst, welches den Scan bekommt. Pro Name sollte nur ein Programm laufen.

## Aus dem Quellcode starten

Wer die exe nicht nutzen will, installiert Python 3.11 oder neuer von python.org und nimmt den Quellcode eines Releases (oder `git clone`):

```
cd pushscan2folder
$env:PYTHONPATH = "src"
python -m pushscan2folder --printer 192.168.1.50 run
```

Es gelten dieselben Optionen. Mit `python -m pushscan2folder --install-autostart ...` richtest du den Autostart für die Python-Variante ein. Tests: `python -m unittest discover -s tests`.

## Grenzen und Hinweise

- Das Projekt wird von GitHub Actions unter Windows getestet (Unit-Tests und Bau der exe). Der Autor nutzt es nicht täglich auf einem echten Windows-Rechner; bitte ein Issue öffnen, wenn etwas nicht klappt.
- Strg+C und Strg+Pause beenden es sauber. Schließen des Konsolenfensters beendet es ebenfalls, Windows gibt dem Programm dann aber nur wenige Sekunden; wird der Name nicht rechtzeitig freigegeben, verwirft ihn der Drucker nach etwa einer Minute.
- In der Konsole werden Zeichen, die die Codepage nicht darstellen kann, durch `?` ersetzt. Die Logdatei ist UTF-8.

## macOS

Nicht paketiert und nicht auf echter Hardware getestet; die Unit-Tests laufen in GitHub Actions auch unter macOS. Python 3.11 oder neuer installieren und aus dem Quellcode starten:

```
cd pushscan2folder
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 run
```

Die Konfiguration liegt in `~/.config/pushscan2folder/config.toml` (oder `$XDG_CONFIG_HOME`), Scans gehen nach `~/Documents/Scans`, wenn du kein `output` setzt. `--install-autostart` gibt es nur für Windows; unter macOS nimmst du für einen Hintergrunddienst einen launchd-Agent. Rückmeldungen von Mac-Nutzern sind willkommen.
