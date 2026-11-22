# Weboberfläche

[English](web.md) | Deutsch

Zurück zur [README](../README.de.md).

- [Überblick](#überblick)
- [Einschalten](#einschalten)
- [Passwort-Optionen](#passwort-optionen)
- [Seiten](#seiten)
- [Ziele und Ordner bearbeiten](#ziele-und-ordner-bearbeiten)
- [Sicherheitsmodell](#sicherheitsmodell)
- [HTTPS hinter einem Reverse-Proxy](#https-hinter-einem-reverse-proxy)
- [Docker](#docker)

## Überblick

Eine kleine Weboberfläche für den lokalen Gebrauch (LAN, NAS) mit aktuellem
Status, letzten Scans, dem Log, einem Editor für die Ziele, einem
Einstellungsformular und einem Rohtext-Editor für die Konfigurationsdatei. Sie
ist standardmäßig aus und braucht keine zusätzlichen Pakete. Sie funktioniert
ohne JavaScript. Ein kleines Skript (`/app.js`, vom Programm selbst
ausgeliefert, keine Inline-Skripte) aktualisiert Status und Log ohne
sichtbares Neuladen, warnt auf den Bearbeitungsseiten vor ungespeicherten
Änderungen und fügt im Rohtext-Editor mit der Tab-Taste zwei Leerzeichen ein.
Ohne JavaScript laden Status und Log alle 10 s neu.

In der mitgelieferten `docker-compose.yml` sind die Web-Zeilen auskommentiert,
die Oberfläche ist dort also ebenfalls aus, bis du sie einkommentierst.

## Einschalten

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
| `[web] password_file` | Schlüssel der Konfigurationsdatei, wie oben; wird genutzt, wenn beide Variablen fehlen. Relative Pfade gelten relativ zur Konfigurationsdatei |
| `PUSHSCAN_WEB_SECURE_COOKIE=1` | nur hinter einem HTTPS-Reverse-Proxy: `Secure`-Cookie siehe [HTTPS](#https-hinter-einem-reverse-proxy) |
| `PUSHSCAN_WEB_PASSWORD_CHECK=0` | Passwortregeln überspringen siehe [Passwort-Optionen](#passwort-optionen) |
| `PUSHSCAN_WEB_AUTH=0` | gar keine Anmeldung siehe [Passwort-Optionen](#passwort-optionen) |

Die Konfigurationsdatei kann eine Tabelle `[web]` mit `enabled`, `bind`, `port`
und `password_file` enthalten (siehe [Konfiguration](configuration.de.md));
`pushscan2folder setup` schreibt sie und legt das Passwort in `web_password.txt`
neben der Konfigurationsdatei ab. Kommandozeile und Umgebung haben Vorrang vor der
Tabelle. Die Einstellungsseite zeigt die Tabelle nur an: Die Anmeldung lässt sich
nicht über die Weboberfläche ändern.

Ohne gültiges Passwort startet das Programm nicht (Exit-Code 2). Es liest das
Passwort selbst nie aus der Konfigurationsdatei und schreibt oder zeigt es nie.

## Passwort-Optionen

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

## Seiten

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
  Der Editor hat kein Feld für die Dateinamen-Vorlage eines Ziels. Ein
  `filename`, das ein Ziel in der Konfigurationsdatei hat, bleibt beim Speichern
  erhalten.
- Einstellungen (`/settings`) bearbeitet `resolution`, `color`, `format`,
  `source`, `size`, `open_after_scan`, `filename` (angezeigt als "File name",
  siehe [Dateinamen](configuration.de.md#dateinamen)) und die vier
  `trim_*`-Werte aus `[defaults]` sowie `multipage`, `ignore_panel` und
  `interval`, jeweils mit kurzer Erklärung. Die
  Werte werden mit denselben Regeln wie die Konfigurationsdatei geprüft; ein
  leeres Feld entfernt den Schlüssel. Der Basis-Ausgabeordner `output` wird nur
  angezeigt. Der Abschnitt "Fixed" zeigt den `printer` mit einem Knopf "Search
  the network", siehe unten. Überschreibt eine Umgebungsvariable oder
  Kommandozeilenoption einen Wert (etwa `PUSHSCAN_INTERVAL` oder
  `PUSHSCAN_TRIM`), weist die Seite darauf hin und zeigt den verwendeten Wert;
  der gespeicherte Wert wirkt nicht, solange die Überschreibung besteht. Die
  Einstellungen werden in die Datei geschrieben, und der laufende Dienst
  übernimmt sie innerhalb eines Abfragezyklus, siehe
  [Datei im laufenden Betrieb ändern](configuration.de.md#datei-im-laufenden-betrieb-ändern).
  Nur die `[web]`-Optionen brauchen einen Neustart.
  Die Druckersuche führt dieselbe mDNS-Suche wie das Setup aus (etwa 5
  Sekunden) und listet Adresse und Modell jedes gefundenen Scanners, jeweils mit
  einem Knopf "Use". Der verwendete Drucker ist mit "in use" markiert. "Use"
  schreibt `printer` in die Konfigurationsdatei und lässt alles andere
  unverändert; der neue Drucker gilt ab dem nächsten Abfragezyklus. Setzt
  `PUSHSCAN_PRINTER` oder `--printer` den Drucker (die mitgelieferte
  Docker-Compose-Datei tut das), gibt es keinen Suchknopf, und die Seite nennt,
  was ihn überschreibt. In Docker mit dem Standard-Bridge-Netz erreicht
  Multicast das LAN nicht, die Suche findet dort also nichts. Setze die Adresse
  dann in der Konfigurationsdatei oder der Umgebung.
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
  angezeigt. Der laufende Dienst übernimmt die Änderungen innerhalb eines
  Abfragezyklus, außer den `[web]`-Optionen, die einen Neustart brauchen. Die
  Größengrenze ist 64 KB.

## Ziele und Ordner bearbeiten

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
einfachen relativen Pfad ein, etwa `Paperless` oder `buero/rechnungen`, oder `.` für den Ausgabeordner
selbst. Absolute Pfade, `..`, Backslashes und Symlinks, die aus dem Ausgabeordner
herausführen, lehnt die Seite ab, sie kann also nirgendwo anders schreiben.
Ein Ziel mit einem Ordner außerhalb des Ausgabeordners (zum Beispiel
`output = "/consume"`) lässt sich nur in der Konfigurationsdatei ändern. Die
Weboberfläche zeigt es schreibgeschützt an und behält es beim Speichern bei;
löschen kannst du es dort trotzdem.

Der Rohtext-Editor lehnt außerdem Änderungen an `output`, `printer` und am
Abschnitt `[web]` ab. Den Drucker kannst du nur auf der Einstellungsseite mit
der Netzwerksuche ändern. `[web]` legt fest, wer die Seite erreicht und wo das
Passwort liegt; das lässt sich nur in der Datei selbst oder mit
`pushscan2folder setup` ändern.

## Sicherheitsmodell

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
- Die Druckersuche akzeptiert nur eine Adresse aus ihrem eigenen letzten
  Suchergebnis, niemand kann den Dienst also über die Weboberfläche auf einen
  anderen Rechner richten. Es läuft nur eine Suche gleichzeitig, und das
  Formular braucht den CSRF-Token wie jedes andere. Der Rohtext-Editor kann
  `printer` weiterhin nicht ändern.
- Browser schicken Cookies an jeden Dienst auf demselben Host, egal auf welchem
  Port. Laufen weitere Weboberflächen auf dem NAS, rufe diese Seite besser über
  einen eigenen Hostnamen auf.

## HTTPS hinter einem Reverse-Proxy

Stelle einen TLS-Reverse-Proxy (Caddy, nginx, Traefik) davor und setze
`PUSHSCAN_WEB_SECURE_COOKIE=1`. Das Cookie heißt dann `__Host-p2f_session` und
ist als `Secure` markiert, die Seite funktioniert dann nur noch über HTTPS. Der
Proxy muss den ursprünglichen `Host`-Header weitergeben (nginx:
`proxy_set_header Host $host;`), sonst werden Formulare mit "Origin does not
match Host" abgelehnt. Binde den Dienst an eine interne Adresse
(`PUSHSCAN_WEB_BIND`), damit man den Proxy nicht umgehen kann.

## Docker

Die mitgelieferte `docker-compose.yml` ist für die Weboberfläche
vorbereitet (`./config:/config`, `PUSHSCAN_CONFIG: /config/config.toml`); zum
Einschalten die Web-Zeilen und den Port einkommentieren. Binde für die
Konfiguration ein Verzeichnis ein, keine einzelne Datei: Eine einzeln
eingebundene Datei lässt sich nicht atomar ersetzen, dann schreibt das Programm
sie direkt neu. Das Verzeichnis muss für den Benutzer
aus `user:` beschreibbar sein. Setze `PUSHSCAN_TARGETS` nicht, wenn du die
Ziele auf der Weboberfläche bearbeitest. Hinter Docker kann das Log das Gateway
des Docker-Netzwerks als Client-Adresse zeigen, siehe
[Client-Adresse im Log](docker.de.md#client-adresse-im-log). Mehr unter
[Docker](docker.de.md).
