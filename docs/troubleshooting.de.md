# Fehlersuche und Einschränkungen

[English](troubleshooting.md) | Deutsch

Zurück zur [README](../README.de.md).

## Ein Problem melden

Starte das Tool mit `--verbose` (oder `PUSHSCAN_VERBOSE=1`) und hänge das Log
an das Issue an. Entferne vorher IP-Adressen und Namen, wenn du möchtest. Die
Issue-Formulare auf GitHub fragen die Details ab. Um ein neues Druckermodell zu
melden, siehe [CONTRIBUTING.md](../CONTRIBUTING.md) (auf Englisch).

## Einschränkungen

- Nur mit einem Canon PIXMA TR8550 getestet. Andere IJ-Modelle funktionieren
  vielleicht, vielleicht auch nicht.
- Die Bedienfeld-Einstellungen "Durchscheinen reduzieren", "Entrasterung" und
  "Unscharfmaskierung" werden gelesen, aber noch nicht angewendet. eSCL kennt
  keine Entsprechung, und die offizielle Software wendet sie wahrscheinlich auf
  dem PC an. Dafür bräuchte es Bildverarbeitung auf deinem Rechner. Das kommt
  vielleicht später dazu, zum Beispiel als optionales Extra.
- Protokolldetails und offene Fragen stehen in [PROTOCOL.md](PROTOCOL.md)
  (auf Englisch).
- Namen auf dem Bedienfeld: 31 Zeichen, etwa 25 sichtbar, nur ASCII-Buchstaben,
  Ziffern, Leerzeichen, `-`, `_`, `@`. Siehe
  [Namen auf dem Bedienfeld](configuration.de.md#namen-auf-dem-bedienfeld).
- Das Tool kontaktiert nur den Drucker. Nur `pushscan2folder setup` sucht im
  Netz (mDNS), und das nur, um eine Adresse vorzuschlagen. Für `run` musst du
  die Adresse des Druckers angeben.

## Bekanntes Verhalten

- TIFF wird nicht unterstützt. Solche Scans werden als JPEG gespeichert.
  "Kompaktes PDF" wird als normales PDF mit 300 dpi gescannt.
- Die Größe "Auto" scannt die volle Breite des Vorlagenglases bei A4-Höhe (kein
  automatischer Zuschnitt).
- Wird ein Scan am Bedienfeld abgebrochen, bleibt ein unvollständiges Dokument
  zurück. Das Tool erkennt das und verwirft es, es wird also nichts gespeichert.
- Der Drucker setzt den Dokumenttyp nach einem Scan unter Umständen auf
  *Automatisch* zurück. Prüfe ihn daher vor dem nächsten mehrseitigen Scan.
- Mehrseitige Scans sind mit A4 bei 300 dpi geprüft. Andere Auflösungen und
  Größen nutzen dieselben Parameter, sind aber noch nicht getestet.
- Die Zuschnittwerte für den TR8550 (3 mm rechts, 2 mm unten) sind noch zu
  prüfen.
- Wählst du am Bedienfeld einen Namen aus, ohne einen Scan zu starten, passiert
  nichts.
- Der Drucker verwirft eine Registrierung nach etwa 60 s ohne Abfrage. Das Tool
  fragt bei langen Scans alle 5 s ab und registriert sich automatisch neu, siehe
  [So funktioniert es](how-it-works.de.md#registrierung-und-lange-scans).
- Nach einer geänderten Reihenfolge der Ziele auf der Weboberfläche
  verschwinden die Namen kurz vom Bedienfeld, während sie neu registriert
  werden.

## Häufige Probleme

- Das Setup findet keinen Drucker: Die Suche nutzt mDNS (Bonjour), das eine
  Firewall, ein VPN, ein Gastnetz oder eine Router-Einstellung blockieren kann,
  und sie funktioniert nur im selben Netz. Gib die IP-Adresse ein, sie steht in
  den Netzwerkeinstellungen am Bedienfeld des Druckers. Unter Windows fragt die
  Firewall eventuell einmal, ob das Programm erlaubt sein soll, siehe
  [Den Drucker finden](windows.de.md#den-drucker-finden).
- Die "Search the network"-Suche der Weboberfläche findet keinen Drucker: Sie
  braucht Multicast, das Dockers Standard-Bridge-Netz nicht weitergibt, und
  auch eine Firewall oder ein VPN kann es blockieren. Trage die Adresse in der
  Konfigurationsdatei oder in `PUSHSCAN_PRINTER` ein. Solange `PUSHSCAN_PRINTER`
  oder `--printer` gesetzt ist, gibt es keinen Knopf.
- Eine geänderte Konfigurationsdatei wirkt nicht: Das Log nennt den Grund. Eine
  ungültige Datei wird einmal als Fehler geloggt, und die laufenden
  Einstellungen bleiben. Die `[web]`-Optionen, die Logdatei, das Debug-Log und
  die Heartbeat-Datei brauchen einen Neustart, siehe
  [Datei im laufenden Betrieb ändern](configuration.de.md#datei-im-laufenden-betrieb-ändern).
- `pushscan2folder stop` scheint zu hängen: Ein Scan läuft. Es wartet bis zu 10
  Minuten, bis der Scan fertig und gespeichert ist, und sagt das auch.
- Der Container zeigt in `docker ps` `unhealthy`: Der Drucker war 2 Minuten lang
  nicht erreichbar, zum Beispiel weil er ausgeschaltet ist oder das Netzwerk
  ausgefallen ist. Siehe [Healthcheck](docker.de.md#healthcheck).
- Ein `run` im Vordergrund startet nicht, weil die Hintergrundinstanz läuft:
  Beide würden dieselben Namen am Bedienfeld anmelden. Führe zuerst
  `pushscan2folder stop` aus, siehe
  [Im Hintergrund laufen](windows.de.md#im-hintergrund-laufen).
- Das Log zeigt in Docker für Web-Anmeldungen eine Adresse wie `172.x.x.1`:
  siehe [Client-Adresse im Log](docker.de.md#client-adresse-im-log).
- Der Scan hat einen unerwarteten Dateinamen: siehe
  [Dateinamen](configuration.de.md#dateinamen). Das `filename` eines Ziels hat
  Vorrang vor `[defaults]`, und `PUSHSCAN_FILENAME` oder `--filename` haben
  Vorrang vor der Konfigurationsdatei.
- Der Name erscheint nicht auf dem Bedienfeld: Namen mit anderen Zeichen als
  Buchstaben, Ziffern, Leerzeichen, `-`, `_` und `@` werden abgelehnt, siehe
  [Namen auf dem Bedienfeld](configuration.de.md#namen-auf-dem-bedienfeld).
  Nach einem Neustart des Druckers erscheinen die Namen nach etwa 10 s wieder.
- Eine Voreinstellung hat keine Farbe: Die Farbe kommt immer vom Bedienfeld,
  siehe [Voreinstellungen pro Ziel](configuration.de.md#voreinstellungen-pro-ziel).
- Der Dialog für mehrseitige Scans erscheint nicht: Er wird nur bei Scans vom
  Vorlagenglas gezeigt, standardmäßig nur für den Dokumenttyp *Dokument*, und
  nicht mit `--ignore-panel`. Siehe
  [Mehrseitige Scans](configuration.de.md#mehrseitige-scans-vom-vorlagenglas).
- Scans lassen sich in Docker nicht schreiben: Das Ausgabeverzeichnis muss für
  den Container-Benutzer beschreibbar sein, siehe
  [Benutzer, UID und GID](docker.de.md#benutzer-uid-und-gid).
- Die Weboberfläche startet nicht: siehe
  [Passwort-Optionen](web.de.md#passwort-optionen). Formulare, die hinter einem
  Reverse-Proxy mit "Origin does not match Host" abgelehnt werden: siehe
  [HTTPS](web.de.md#https-hinter-einem-reverse-proxy).
- Die Ziele lassen sich auf der Weboberfläche nicht bearbeiten: Das Bearbeiten
  ist abgeschaltet, wenn sie aus `PUSHSCAN_TARGETS` / `--targets` kommen, siehe
  [Ziele und Ordner bearbeiten](web.de.md#ziele-und-ordner-bearbeiten).
