# How it works

English | [Deutsch](how-it-works.de.md)

Back to the [README](../README.md).

1. Register. The tool announces itself to the printer with Canon's CHMP
   push-scan notification protocol (HTTP POST to `/canon/ij/command1/port2`). The name you chose appears on the panel.
2. Poll. Like the official software, the tool polls the printer every 4
   seconds (configurable). If the printer is unreachable, it registers again with exponential back-off, capped
   at 10 s, so the names reappear within about 10 s after a printer restart.
3. Scan. When the user starts a scan to this host on the panel, the poll
   answer has status `0x8000` ("scan requested") and carries 32 bytes of panel
   settings. The tool scans with these settings, using either Canon's own
   scanner protocol (multi-page platen scans, see
   [Configuration](configuration.md#multi-page-scans-from-the-platen)) or
   eSCL. It writes `scan_YYYYmmdd_HHMMSS[_NN].pdf|jpg` into the output
   directory and never overwrites existing files. Selecting a name on the
   panel without starting a scan triggers nothing.
4. Release. On SIGINT/SIGTERM the tool releases the session.

The tool needs Python >= 3.11 and the standard library only. It makes only
outbound connections to the printer (TCP 80). No inbound ports are needed
(except for the optional web page), so Docker's default bridge networking
works.

## Registration and long scans

The printer drops a registration after roughly 60 s without polls (status
`0x1`). While a scan runs (multi-page platen scans as well as long eSCL scans,
e.g. 600 dpi or several ADF pages) the tool keeps polling every 5 s, so the
names stay on the panel. If a registration is dropped anyway, the tool
registers again automatically.

## Protocol summary

Transport: HTTP POST to `http://<printer>:80/canon/ij/command1/port2` with the
headers `Content-Type: application/octet-stream`, `X-CHMP-Version: 1.0`,
`X-CHMP-CommandType: BJNPNotify`, `X-CHMP-EventType: PuScan`.

Request body, 0x68 bytes, big endian:

| Offset | Size     | Field        | Notes                                      |
|--------|----------|--------------|--------------------------------------------|
| +0x00  | u16      | type         | 1 = register, 2 = poll, 4 = release        |
| +0x02  | u16      | reserved     |                                            |
| +0x04  | u32      | session id   | poll / release                             |
| +0x08  | 64 bytes | host name    | UTF-16BE, NUL padded (register only)       |
| +0x48  | u32      | reserved     |                                            |
| +0x60  | u32      | reserved     |                                            |

Response body, 0x110 bytes, big endian:

| Offset | Size     | Field          | Notes                                    |
|--------|----------|----------------|------------------------------------------|
| +0x02  | u16      | status         | 0x8000 = scan requested (poll)           |
| +0x04  | u32      | session id     | register                                 |
| +0x08  | u32      | unknown        |                                          |
| +0x0c  | u32      | event value    | poll, status 0x8000                      |
| +0x10  | 32 bytes | interrupt data | poll, status 0x8000                      |
| +0x8c  | u32      | unknown        |                                          |

The layout of the 32 interrupt bytes and the open questions are in
[PROTOCOL.md](PROTOCOL.md).
