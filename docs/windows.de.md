# Unter Windows nutzen

pushscan2folder läuft unter Windows 10 und 11 nativ als einzelnes Programm, als Alternative zu Canons eigener Scan-Software. Es meldet einen Namen am Display des Druckers an, fragt den Drucker ab und speichert Scans in einen Ordner. Es gibt einen Installer, der keine Administratorrechte braucht.

Linux und Docker stehen in der README. macOS steht am Ende dieser Seite.

## Installieren

1. Auf der Releases-Seite des Projekts bei GitHub `pushscan2folder-VERSION-windows-setup.exe` herunterladen (und bei Bedarf `SHA256SUMS.txt`).
2. Zur Kontrolle in PowerShell `Get-FileHash pushscan2folder-VERSION-windows-setup.exe` ausführen und mit `SHA256SUMS.txt` vergleichen.
3. Den Installer starten. Er fragt nach seiner Sprache (Englisch oder Deutsch). Er installiert nur für deinen Benutzer, braucht keine Administratorrechte und legt das Programm in `%LOCALAPPDATA%\Programs\pushscan2folder` ab.

Der Installer legt im Startmenü einen Ordner "pushscan2folder" mit drei Einträgen an:

- "pushscan2folder" startet das Programm normal,
- "pushscan2folder einrichten" führt die Setup-Fragen aus (`setup`),
- "pushscan2folder beenden" beendet die Hintergrundinstanz (`stop`).

Ein Desktop-Symbol ist optional und standardmäßig nicht angehakt. Am Ende bietet der Installer "Set up and start pushscan2folder" an. Das öffnet das Konsolenfenster mit den Setup-Fragen (siehe unten).

Installer und Programm werden von GitHub Actions aus dem getaggten Quellcode gebaut. Der Installer entsteht mit Inno Setup um einen PyInstaller-Ordner-Build. Er ist nicht code-signiert.

Zum Aktualisieren startest du den neueren Installer. Läuft die Hintergrundinstanz, beendet der Installer sie, ersetzt die Dateien und startet sie wieder. Deine Einstellungen bleiben erhalten.

### Warnungen von Virenscannern

Mit PyInstaller gepackte Programme werden manchmal von Virenscannern gemeldet, etwa von Microsoft Defender als `Trojan:Win32/Bearfoos.A!ml`. Das `!ml` steht für eine Vermutung des Machine-Learning-Modells, nicht für eine bekannte Signatur. Damit das selten passiert, ist das installierte Programm ein Ordner-Build (beim Start wird nichts entpackt) mit einem Starter, den der Build selbst kompiliert. Passiert es trotzdem: Prüfsumme des Installers kontrollieren, die Datei im Schutzverlauf wiederherstellen und den Fehlalarm bei Bedarf unter https://www.microsoft.com/wdsi/filesubmission melden. Bitte auch ein Issue öffnen, damit er für das Release gemeldet werden kann.

## Erster Start und SmartScreen

Weil der Installer nicht signiert ist, zeigt Windows SmartScreen beim Start eventuell "Der Computer wurde durch Windows geschützt". Auf "Weitere Informationen" und dann auf "Trotzdem ausführen" klicken. Wenn du die Datei im Browser geladen hast, geht es auch über Rechtsklick, Eigenschaften, Haken bei "Zulassen".

"pushscan2folder" im Startmenü starten (oder das Desktop-Symbol, oder `pushscan2folder.exe` im Programmordner). Es öffnet sich ein Konsolenfenster. Gibt es noch keine Konfigurationsdatei, begrüßt dich das Programm und stellt ein paar Fragen (das ist der Befehl `setup`):

- IP-Adresse oder Hostname des Druckers (wird sofort geprüft; du kannst neu eingeben oder trotzdem weitermachen),
- der Name, der am Druckerdisplay erscheint (Standard `BENUTZER  PCNAME`),
- der Ordner für Scans (Standard `Dokumente\Scans`; die Scans landen direkt in diesem Ordner, nicht in einem Unterordner),
- ob die Weboberfläche an sein soll (Standard nein; wenn ja: Port, Bind-Adresse und ein Passwort, zweimal eingegeben),
- ob nach jedem Scan der Ordner geöffnet werden soll (Standard ja, siehe [Ordner nach dem Scan öffnen](#ordner-nach-dem-scan-öffnen)),
- ob das Programm beim Anmelden automatisch starten soll (Standard ja).

Danach schreibt es `%APPDATA%\pushscan2folder\config.toml`, zeigt, wo alles liegt, und fragt "Run in the background now?" (Standard ja, siehe unten). Bei nein fragt es "Start now?" und läuft im Konsolenfenster. Das Webpasswort steht nicht in `config.toml`, sondern in `web_password.txt` daneben. `%APPDATA%` gehört nur deinem Benutzerkonto.

Beim nächsten Start per Doppelklick oder aus dem Startmenü findet das Programm die Konfigurationsdatei und zeigt die aktuellen Einstellungen: den Drucker, jeden Namen mit seinem Ordner und ob die Weboberfläche an ist. Dann fragt es:

- `1` diese Einstellungen verwenden (Standard),
- `2` sie ändern (die Setup-Fragen, deine Namen und Ordner bleiben erhalten),
- `3` neu anfangen mit einer neuen Konfiguration. Die alte Datei bleibt als `config.toml.bak` erhalten.

Ist die Konfigurationsdatei defekt, sagt das Programm das und bietet an, neu anzufangen, ebenfalls mit der `.bak`-Kopie. Läuft das Programm schon im Hintergrund, sagt es das und verweist dich auf `pushscan2folder stop`, bevor du die Einstellungen ändern kannst.

Diese Frage kommt nur bei einem Doppelklick. In einer Eingabeaufforderung mit Argumenten läuft das Programm einfach los, ebenso unter Linux und macOS.

Bei `1` läuft das Programm. Es zeigt eine kurze Zusammenfassung (Version, Drucker, Konfigurationsdatei, Name und Ordner, Weboberfläche, Logdatei) und "Press Ctrl+C to stop." Das Schließen dieses Fensters beendet das Programm; die Zusammenfassung sagt das auch. Das Log zeigt die Anmeldung. Am Druckerdisplay erscheint unter "Scannen" und "Computer" ein Name wie `BENUTZER  PCNAME`. Auswählen und Start drücken. Mit Strg+C beenden; das Programm gibt den Namen am Drucker vorher frei.

Wurde das Konsolenfenster nur für dieses Programm geöffnet, wartet es vor dem Schließen auf Enter, damit du die letzte Meldung lesen kannst. Das passiert nicht in einem Fenster, das du selbst geöffnet hast, nicht bei nicht interaktiver Eingabe und nicht beim Start über den Anmelde-Eintrag. `--no-pause` (oder `PUSHSCAN_NO_PAUSE=1`) schaltet es ab.

Einstellungen später ändern: Konfigurationsdatei bearbeiten oder die Fragen erneut stellen lassen (auch im Startmenü als "pushscan2folder einrichten"). Hat die Datei schon `[[target]]`-Einträge, bleiben deine Namen und Ordner beim Setup unverändert:

```
.\pushscan2folder.exe setup
```

Die Kommandozeile geht auch ohne Fragen. Der Unterbefehl `run` ist der Standard und kann entfallen:

```
.\pushscan2folder.exe --printer 192.168.1.50
```

Alle Optionen: `.\pushscan2folder.exe --help`.

## Im Hintergrund laufen

Ein per Doppelklick gestartetes Programm lebt in seinem Konsolenfenster, und mit dem Fenster ist es beendet. Ohne Fenster dauerhaft laufen lassen:

```
.\pushscan2folder.exe start
```

`start` startet das Programm abgekoppelt im Hintergrund mit der aktuellen Konfiguration und kehrt sofort zurück. Es nimmt dieselben Optionen wie `run` (zum Beispiel `--config PFAD`, `--web`). Der Hintergrundprozess hat kein Konsolenfenster und läuft weiter, wenn du das Fenster schließt, aus dem du ihn gestartet hast. Sein Log geht nach `%LOCALAPPDATA%\pushscan2folder\pushscan2folder.log`, sofern du nicht `--log-file PFAD` angibst. Läuft schon eine Instanz, lehnt `start` ab und sagt es.

```
.\pushscan2folder.exe status
.\pushscan2folder.exe stop
```

- `status` sagt, ob die Hintergrundinstanz läuft, nennt PID und Logdatei und zeigt die letzten Logzeilen. Der Exit-Code ist 0, wenn sie läuft, sonst 1.
- `stop` bittet die Instanz, sich zu beenden. Sie verlässt ihre Schleife nach wenigen Sekunden (ein laufender Scan wird noch fertig) und gibt ihre Namen am Drucker frei, sie verschwinden also vom Display. Ein abgekoppelter Prozess bekommt kein Strg+C, deshalb schreibt `stop` eine Stopp-Anforderungsdatei, die die Instanz etwa einmal pro Sekunde prüft. Ist die Instanz nach 30 Sekunden nicht beendet, wird sie abgebrochen; der Drucker verwirft die Namen dann nach etwa einer Minute.

Die Instanz hält eine Lock-Datei, eine PID-Datei und die Stopp-Anforderungsdatei in `%LOCALAPPDATA%\pushscan2folder\`. Das Lock hält der laufende Prozess, und Windows gibt es frei, wenn er endet. Eine übrig gebliebene Datei nach einem Absturz oder Neustart blockiert den nächsten `start` deshalb nie.

Ein `run` im Vordergrund gehört nicht dazu. Es nutzt das Lock nicht, `stop` beendet es nicht, und `start` bemerkt es nicht. Beides nicht für denselben Namen gleichzeitig starten.

## Ordner nach dem Scan öffnen

Mit `open_after_scan = "folder"` in `[defaults]` (oder `--open-after-scan folder`, `PUSHSCAN_OPEN_AFTER_SCAN=folder`) öffnet der Explorer nach jedem Scan den Ordner mit markierter neuer Datei. Bei `"file"` öffnet sich der Scan selbst im PDF-Programm. Standard ist `"off"`. Das Setup fragt "Open the folder after each scan?" und schreibt bei ja `"folder"`. Ein Scan mit mehreren Seiten oder Dateien öffnet nur einmal. Schlägt das Öffnen fehl, steht eine Warnung im Log und der Scan bleibt trotzdem erhalten. Die Option steht auch auf der Einstellungsseite der Weboberfläche. Sie braucht einen angemeldeten Desktop-Benutzer und ist daher für einen PC gedacht, nicht für einen Server.

## Firewall

Das Programm baut nur ausgehende Verbindungen zum Drucker auf. Für das Scannen braucht die Windows-Firewall deshalb keine Regel.

Anders ist es bei der optionalen Webseite. Mit `--web` (oder `enabled = true` in der Tabelle `[web]` der Konfigurationsdatei) lauscht das Programm auf einem Port (Standard 8080) und bindet an alle Adressen, wenn du nichts anderes angibst. Die Setup-Fragen schlagen `127.0.0.1` vor. Windows fragt dann einmal, ob das Programm in privaten oder öffentlichen Netzwerken erlaubt sein soll. Damit die Seite nur auf diesem PC erreichbar ist:

```
.\pushscan2folder.exe --printer 192.168.1.50 --web --web-bind 127.0.0.1
```

Dann ist nichts für andere Geräte erreichbar und es ist keine Firewall-Regel nötig. Im Browser http://127.0.0.1:8080 öffnen. Die Webseite braucht ein Passwort, das vor dem Start gesetzt wird, zum Beispiel:

```
$env:PUSHSCAN_WEB_PASSWORD = "ein langes eigenes Passwort"
```

Das Setup legt das Passwort in `web_password.txt` neben der Konfigurationsdatei ab und trägt die Datei in `[web] password_file` ein, was der Autostart braucht. Von Hand nutzt du eine Datei und setzt `PUSHSCAN_WEB_PASSWORD_FILE` oder `password_file` (siehe Dokumentation der Webseite).

## Wo liegt was

| Was | Ort |
| --- | --- |
| Konfigurationsdatei (vom Setup geschrieben) | `%APPDATA%\pushscan2folder\config.toml` |
| Webpasswort (wenn die Weboberfläche an ist) | `%APPDATA%\pushscan2folder\web_password.txt` |
| Programm | `%LOCALAPPDATA%\Programs\pushscan2folder` |
| Scans | `Dokumente\Scans` im Benutzerordner (`C:\Users\NAME\Documents\Scans`). Das Setup legt ein Ziel an, das direkt dort speichert. |
| Logdatei | `%LOCALAPPDATA%\pushscan2folder\pushscan2folder.log` für die Hintergrundinstanz und den Autostart; mit `--log-file PFAD` woanders |
| Dateien der Hintergrundinstanz (Lock, PID, Stopp-Anforderung) | `%LOCALAPPDATA%\pushscan2folder\` |

Das Programm sucht die Konfigurationsdatei selbst. Mit `--config PFAD` nimmst du eine andere. Wenn dein Dokumente-Ordner verschoben ist (zum Beispiel durch OneDrive), setze `output` in der Konfigurationsdatei auf den echten Pfad, denn der Standard ist `Documents` unterhalb des Benutzerordners.

Eine neue Konfigurationsdatei, die die Webseite schreibt, soll privat sein. Unter Windows lässt sich der Dateimodus 0600 nicht setzen; die Datei ist durch deinen Benutzerordner geschützt, den andere Standardbenutzer nicht lesen können.

Ein Ziel mit `output = "."` speichert direkt im Ausgabeordner, ohne Unterordner. Das schreiben die Setup-Fragen. Ohne `output` speichert ein Ziel in `<output>/<name>`.

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

Danach genügt `.\pushscan2folder.exe`. Die übrigen Schlüssel stehen in `config.example.toml`.

## Beim Anmelden starten

Die Fragen des Setups bieten das an und führen den folgenden Befehl für dich aus. Von Hand:

```
.\pushscan2folder.exe --config "%APPDATA%\pushscan2folder\config.toml" --log-file "%APPDATA%\pushscan2folder\pushscan2folder.log" --install-autostart
```

(In PowerShell `$env:APPDATA` statt `%APPDATA%` schreiben.)

Das legt den Eintrag `pushscan2folder` in der Run-Liste deines Benutzers an (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`). Dafür sind keine Administratorrechte nötig. Bei jeder Anmeldung führt der Eintrag `pushscan2folder start` aus, mit genau den Optionen, die du neben `--install-autostart` angegeben hast, plus `--no-pause`. Das startet die Hintergrundinstanz (siehe oben), es bleibt also kein Fenster offen. Das Konsolenfenster des kurzen `start`-Aufrufs kann kurz aufblitzen. Läuft schon eine Instanz, tut der Eintrag nichts. Pfade werden absolut gespeichert. Eine Aufgabe in der Aufgabenplanung mit Anmelde-Trigger bräuchte auf den meisten Systemen Administratorrechte, deshalb wird die Run-Liste benutzt.

Nutze `--log-file`; die Hintergrundinstanz hat keine sichtbare Konsole. Ohne die Option geht das Log in den oben genannten Standardpfad. Die Datei rotiert bei 1 MB und behält 3 alte Dateien.

Die exe danach nicht verschieben oder umbenennen. Sonst den Befehl vom neuen Ort aus wiederholen. Beim Aktualisieren mit dem Installer ist das nicht nötig.

Entfernen:

```
.\pushscan2folder.exe --remove-autostart
```

Du siehst den Eintrag auch im Task-Manager auf dem Tab "Autostart-Apps" oder unter Einstellungen, Apps, Autostart.

## Deinstallieren

Über Windows-Einstellungen, Apps, pushscan2folder. Der Deinstaller beendet die Hintergrundinstanz (die Namen verschwinden vom Display), entfernt den Autostart-Eintrag und fragt, ob auch die Einstellungen und das Log gelöscht werden sollen (Standard nein). Deine Scans werden nie gelöscht.

`pushscan2folder uninstall` räumt von der Kommandozeile aus genauso auf. Es beendet die Hintergrundinstanz, entfernt den Autostart-Eintrag und listet dann den Konfigurationsordner (`%APPDATA%\pushscan2folder\`, mit `config.toml` und `web_password.txt`) sowie den Log- und Statusordner (`%LOCALAPPDATA%\pushscan2folder\`) auf. Es fragt, ob sie gelöscht werden sollen, Standard nein. Deine Scans werden nie gelöscht, und ein Ordner, der deinen Scan-Ordner enthält, bleibt erhalten. Bei einer installierten Kopie endet es mit dem Hinweis, das Programm unter Einstellungen, Apps zu entfernen. Bei einer Kopie ohne Installer (zum Beispiel von pip oder aus dem Quellcode) erinnert es dich, das Programm selbst zu entfernen, denn Windows kann ein laufendes Programm nicht löschen.

Für Skripte: `uninstall --yes` fragt nicht und behält Konfiguration und Log; `uninstall --yes --purge` löscht sie. Ordner, die über `--config PFAD` angegeben sind, werden nicht angefasst.

Unter Linux und macOS macht der Befehl dasselbe, nur ohne Autostart-Eintrag (das Programm selbst entfernst du so, wie du es installiert hast, zum Beispiel `pip uninstall pushscan2folder`). Von Hand unter Windows: `--remove-autostart`, den Programmordner löschen, die beiden Datenordner löschen.

## Neben Canon IJ Scan Utility

Beide können gleichzeitig installiert sein. Jedes meldet einen eigenen Eintrag am Druckerdisplay an, du siehst also beide Namen in der Liste und wählst, welches den Scan bekommt. Pro Name sollte nur ein Programm laufen.

## Aus dem Quellcode starten

Wer den Installer nicht nutzen will, installiert Python 3.11 oder neuer von python.org und nimmt den Quellcode eines Releases (oder `git clone`):

```
cd pushscan2folder
$env:PYTHONPATH = "src"
python -m pushscan2folder --printer 192.168.1.50
```

Es gelten dieselben Optionen. Mit `python -m pushscan2folder --install-autostart ...` richtest du den Autostart für die Python-Variante ein. Tests: `python -m unittest discover -s tests`.

## Grenzen und Hinweise

- Das Projekt wird von GitHub Actions unter Windows getestet (Unit-Tests und Bau der exe). Der Autor nutzt es nicht täglich auf einem echten Windows-Rechner; bitte ein Issue öffnen, wenn etwas nicht klappt.
- Mit `start` läuft es ohne Fenster weiter. In einem Vordergrundfenster beenden Strg+C und Strg+Pause es sauber. Schließen des Konsolenfensters beendet es ebenfalls, Windows gibt dem Programm dann aber nur wenige Sekunden; wird der Name nicht rechtzeitig freigegeben, verwirft ihn der Drucker nach etwa einer Minute.
- In der Konsole werden Zeichen, die die Codepage nicht darstellen kann, durch `?` ersetzt. Die Logdatei ist UTF-8.

## macOS

Nicht paketiert und nicht auf echter Hardware getestet; die Unit-Tests laufen in GitHub Actions auch unter macOS. Python 3.11 oder neuer installieren und aus dem Quellcode starten:

```
cd pushscan2folder
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50
```

Die Konfiguration liegt in `~/.config/pushscan2folder/config.toml` (oder `$XDG_CONFIG_HOME`), Scans gehen nach `~/Documents/Scans`, wenn du kein `output` setzt. `--install-autostart` gibt es nur für Windows; unter macOS nimmst du für einen Hintergrunddienst einen launchd-Agent. Rückmeldungen von Mac-Nutzern sind willkommen.
