# So funktioniert es

[English](how-it-works.md) | Deutsch

Zurück zur [README](../README.de.md).

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
   Scans vom Vorlagenglas, siehe
   [Konfiguration](configuration.de.md#mehrseitige-scans-vom-vorlagenglas)) oder über eSCL. Es schreibt
   `scan_YYYYmmdd_HHMMSS[_NN].pdf|jpg` in das Ausgabeverzeichnis und
   überschreibt nie vorhandene Dateien. Wählst du am Bedienfeld einen Namen aus,
   ohne einen Scan zu starten, passiert nichts.
4. Freigeben. Bei SIGINT/SIGTERM gibt das Tool die Sitzung frei.

Das Tool braucht Python >= 3.11 und nur die Standardbibliothek. Es baut nur ausgehende Verbindungen zum Drucker auf (TCP 80). Eingehende Ports sind nicht nötig (außer für die optionale Weboberfläche), daher funktioniert Dockers Standard-Bridge-Netzwerk.

## Registrierung und lange Scans

Der Drucker verwirft eine Registrierung nach etwa 60 s ohne Abfrage (Status
`0x1`). Während ein Scan läuft (mehrseitige Scans vom Vorlagenglas ebenso wie
lange eSCL-Scans, z. B. mit 600 dpi oder mehreren Seiten aus dem Einzugsfach),
fragt das Tool alle 5 s weiter ab, damit die Namen auf dem Bedienfeld bleiben.
Wird eine Registrierung trotzdem verworfen, registriert sich das Tool
automatisch neu.

## Protokollübersicht

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
[PROTOCOL.md](PROTOCOL.md) (auf Englisch).
