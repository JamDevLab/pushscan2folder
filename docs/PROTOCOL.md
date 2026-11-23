# Canon IJ push-scan protocol (CHMP / BJNPNotify)

This document describes what pushscan2folder knows about the "scan to PC"
notification protocol of Canon IJ printers. It is based on observing the
network traffic and behaviour of a Canon PIXMA TR8550 (TR8550 series) and on what an
independent program needed to interoperate with it. Values marked
*unconfirmed* are guesses. Please report observations from other models (see
[CONTRIBUTING.md](../CONTRIBUTING.md)).

## Overview

The printer never connects to the PC. Instead the PC

1. registers a name, which then appears on the printer panel under
   *Scan*, then *Computer*,
2. polls the printer every few seconds,
3. receives a scan request in a poll answer when the user picks that name
   and presses start,
4. performs the scan itself, over [eSCL](#scanning-escl) or Canon's
   [native scanner protocol](#scanning-native-protocol-multi-page),
5. releases the registration when it shuts down.

All connections go from the PC to the printer, so no inbound ports are needed
and the protocol works in containers.

## Transport

Every message is one HTTP/1.1 request on port 80:

```
POST /canon/ij/command1/port2 HTTP/1.1
Host: <printer>
Content-Type: application/octet-stream
Content-Length: 104
X-CHMP-Version: 1.0
X-CHMP-CommandType: BJNPNotify
X-CHMP-EventType: PuScan

<104 byte request body>
```

The response is `200 OK` with a binary body (52 bytes on the TR8550).

`/canon/ij/command2/port3` carries the [native scanner
protocol](#scanning-native-protocol-multi-page). Other paths seen in the same
family (`/canon/ij/command1/port1`, `/canon/ij/command2/port1`, `port2`,
`port4`, `port5`) and the optional header `X-CHMP-Timeout: <seconds>` are not
used by pushscan2folder, and their purpose is unknown.

## Request body (104 bytes, big endian)

| Offset | Type     | Field      | Notes                                         |
|--------|----------|------------|-----------------------------------------------|
| 0x00   | u16      | type       | 1 = register, 2 = poll, 4 = release           |
| 0x02   | u16      | reserved   | 0                                             |
| 0x04   | u32      | session id | from the register answer; 0 for register      |
| 0x08   | 64 bytes | name       | register only: UTF-16BE, NUL padded, ≤ 31 chars |
| 0x48   | u32      | reserved   | 0                                             |
| 0x4c   | …        | reserved   | 0 up to 0x68                                  |

The Windows software uses the name format `USER  COMPUTER` (two spaces) and
cuts it to 31 UTF-16 code units. Observed on the TR8550 panel:

- Every name is accepted, but only A-Z, a-z, 0-9, space, `-`, `_` and `@`
  are displayed; every other character (including `.`, `&`, `/`, umlauts,
  accents, emoji and CJK) is shown as a blank.
- About 25 characters are visible, longer names end in `...`.
- 20 names at once were listed (scrollable), ordered by registration time.

## Response body (big endian)

| Offset | Type     | Field          | Notes                                    |
|--------|----------|----------------|------------------------------------------|
| 0x00   | u16      | -              | 0                                        |
| 0x02   | u16      | status         | see below                                |
| 0x04   | u32      | session id     | new id for register, echoed otherwise    |
| 0x08   | u32      | unknown        | always 0x24 on the TR8550                |
| 0x0c   | u32      | event id       | with status 0x8000; differs per request  |
| 0x10   | 32 bytes | interrupt data | with status 0x8000, [panel settings](#interrupt-data-panel-settings) |
| 0x8c   | u32      | unknown        | not present in 52 byte answers           |

### Status values

| Status   | Meaning                                                              |
|----------|----------------------------------------------------------------------|
| `0x0000` | nothing to do                                                        |
| `0x8000` | the user selected this name and started a scan                       |
| `0x0001` | the session is no longer known; register again                       |

## Session lifetime

- Session ids are counters that increase with every registration.
- Several sessions from the same IP address are accepted at the same time;
  each one appears as its own entry on the panel.
- The printer drops a session after roughly 60 seconds without a poll and
  answers `0x0001` afterwards. The entry vanishes from the panel at that point.
- After a printer restart all sessions are gone; connection errors occur while
  it boots, then registering again works.
- Selecting a name on the panel without pressing start sends nothing.
- The official Windows software polls about every 4 seconds and keeps polling
  while a scan runs.

## Interrupt data (panel settings)

The 32 bytes describe what the user chose on the panel. They were determined on
the TR8550 by changing one setting per scan:

| Offset | Field               | Values |
|--------|---------------------|--------|
| 0–3    | -                   | always 0 |
| 4, 5   | -                   | always 1 |
| 6      | document type       | 1 document, 2 photo, 3 auto scan |
| 7      | colour              | 1 colour, 2 black and white |
| 8      | source              | 1 platen, 2 ADF (chosen by the printer's paper sensor) |
| 9      | -                   | 0 |
| 10     | size                | 1 A4, 2 Letter, 3 Legal (ADF only), 8 10×15 cm, 9 13×18 cm, 0x0b auto scan (photo), 0x0c auto multi scan (photo) |
| 11     | format              | 1 JPEG, 2 TIFF, 3 PDF, 4 compact PDF |
| 12     | resolution          | 1 = 75, 2 = 150, 3 = 300, 4 = 600 dpi; 0 with compact PDF |
| 13     | reduce bleed-through| 1 off, 2 on |
| 14     | descreen (moiré)    | 1 off, 2 on |
| 15     | unsharp mask        | 1 off, 2 on |
| 16     | ADF option          | 1 when scanning from the ADF in document mode, else 0 (*unconfirmed*, perhaps orientation) |
| 17–31  | -                   | 0 |

With document type auto scan only offsets 6 to 8 are set (plus offset 20 = 1
when the ADF is used, *unconfirmed*), and the PC decides the rest.

With photo the printer preselects 10×15 cm, JPEG and 300 dpi. Bleed-through
and descreen are 0 (not applicable). With the sizes auto scan (0x0b) and auto
multi scan (0x0c) the printer sends the whole glass. The PC cuts out the photos
(see [Photos](configuration.md#photos)).

The printer enforces some panel restrictions, not the protocol: compact PDF
cannot be combined with unsharp mask or bleed-through reduction, and the panel
shows a warning until the unsharp mask is switched off.

The ADF orientation setting (portrait / landscape) did not change the data
when scanning from the platen.

### Open questions

- Other size codes (B5, A5?) were not seen; other models may offer them.
- Meaning of offset 16 and offset 20 when scanning from the ADF.
- Whether the event id has any use.

## Scanning (eSCL)

The notification protocol tells the PC that a scan was requested and with which
settings. The scan itself uses eSCL (AirScan), an open HTTP protocol:

1. `POST /eSCL/ScanJobs` with a `ScanSettings` XML document returns `201 Created`
   with a `Location` header.
2. `GET <Location>/NextDocument` until `404`. The platen delivers one
   document; the ADF delivers one PDF with all pages.
3. If the job does not end with that `404` (an error, a size limit, an empty
   document), the program sends `DELETE <Location>` (the eSCL way to cancel
   a job) and ignores its answer. Not yet observed on the TR8550.
4. `GET /eSCL/ScannerStatus` reports `ScannerAdfLoaded` when paper is in the
   feeder.

Notes for the TR8550:

- 300 dpi works although `ScannerCapabilities` lists only 75, 100, 150, 200,
  600 and 1200.
- Cancelling on the panel during a scan ends the transfer early. The received
  document is truncated (PDF without `%%EOF`) and should be discarded.
- A 3 page ADF scan at 300 dpi takes about 60 seconds, long enough for the
  printer to drop other sessions (see [session lifetime](#session-lifetime)).

## Scanning (native protocol, multi-page)

eSCL cannot scan several pages from the platen. The official software uses
Canon's own scanner protocol instead, and only that protocol makes the panel
ask for further pages. The following was observed on the TR8550 with the
official software (document type *Document*, A4, 300 dpi, colour).

### Transport

Each exchange is two HTTP requests on the same keep-alive connection:

```
POST /canon/ij/command2/port3 HTTP/1.1      (request body)
Content-Type: application/octet-stream
X-CHMP-Version: 1.0

GET /canon/ij/command2/port3 HTTP/1.1       (answer, chunked)
X-CHMP-Version: 1.0
```

The POST answer is `200 OK` with an empty body, and the GET returns the answer
to the request. Bodies are either XML (job control) or binary scanner commands.

### Job control (XML)

```xml
<?xml version="1.0" encoding="utf-8" ?><cmd xmlns:ivec="http://www.canon.com/ns/cmd/2008/07/common/"><ivec:contents><ivec:operation>StartJob</ivec:operation><ivec:param_set servicetype="scan"><ivec:jobID>00000001</ivec:jobID><ivec:bidi>1</ivec:bidi></ivec:param_set></ivec:contents></cmd>
```

| Operation | Parameters | Notes |
|-----------|------------|-------|
| `VendorCmd` | `vcn:ijoperation` `ModeShift`, `vcn:ijmode` `1`, `ivec:jobID` | needs the extra namespace `xmlns:vcn="http://www.canon.com/ns/cmd/2008/07/canon/"`; sent before and after `StartJob` |
| `StartJob` | `ivec:jobID`, `ivec:bidi` `1` | |
| `EndJob` | `ivec:jobID` | |

Answers are `<Operation>Response` documents containing
`<ivec:response>OK</ivec:response>`.

### Binary commands

Request: 16 byte header (big endian), optionally followed by data:

| Offset | Type | Field |
|--------|------|-------|
| 0x00 | u16 | opcode |
| 0x02 | u16 | argument |
| 0x04 | 8 bytes | 0 |
| 0x0c | u32 | length: size of the data that follows, or of the data expected back |

Data blocks end with a checksum byte: all data bytes sum to 0 (mod 256).

Answer: u16 status (`0x0606` = ok), 6 bytes 0, then the data (again with a
checksum byte where applicable). Pressing *Stop* on the panel while a page is
being scanned makes the next command answer `0x1515` (cancelled).

| Opcode | Argument / length | Purpose (as observed) |
|--------|-------------------|------------------------|
| `0xdb20` | arg 2 | start session |
| `0xf320` | len 0x10 | status (16 bytes) |
| `0xd820` | 56 data bytes | scan parameters, see below |
| `0xd920` | arg 1 | start scanning |
| `0xda20` | len 8 | scanner state; repeat until the first byte is 3 (1 and 4 seen while waiting) |
| `0xdc20` | len 8 | unknown, sent once before reading |
| `0xd420` | len 0x00100008 | read image data |
| `0xe120` | len 0x100 | image information after the page |
| `0xec20` | len 8 | next page? shows the panel dialog, see below |
| `0xef20` | - | end session |

### Scan parameters (`0xd820`)

Offsets in the 56 data bytes. Values not listed were constant.

| Offset | Value |
|--------|-------|
| 0x00 | source: 1 platen |
| 0x01, 0x02, 0x06 | 1 |
| 0x08, 0x0a | x and y resolution as `0x8000 + dpi` (u16) |
| 0x0c, 0x10 | x and y offset (u32, pixels) |
| 0x14, 0x18 | width and height (u32, pixels); A4 at 300 dpi: 2480 × 3507 |
| 0x1c, 0x1d | colour `0x08 0x18`, black and white `0x04 0x08` |
| 0x1f 0x20 0x21 0x23 0x24 | `01 ff 82 02 01` |
| 0x26 | 4 ASCII digits: local time `HHMM` |
| 0x30 | 3 |
| 0x37 | checksum |

### Image data (`0xd420`)

Each answer's data starts with 8 bytes: flags (byte 0) and the chunk size
(u32 at byte 4), followed by up to 16 KiB of image data. Chunks of size 0 mean
"not ready yet, ask again". Flag `0x20` marks the last data chunk (and stays
set), flag `0x08` (seen as `0x28`) means the page is complete. The data of one
page is a baseline JPEG with JFIF density set to the resolution; in black and
white mode it is still a 3 component JPEG with grey content.

### Next page dialog (`0xec20`)

After a page the PC sends `0xec20` repeatedly (about every 0.5 s). The panel
then shows *Stop*, *Black and white*, *Colour* and *Finish*. The first data
byte of the answer is:

| Value | Meaning |
|-------|---------|
| `0x00` | no decision yet |
| `0x01` | *Colour*: scan another page in colour |
| `0x02` | *Black and white*: scan another page in black and white |
| `0xff` | *Finish* or *Stop* (identical answer `ff 00 00 00 00 00 00 01`) |

For another page the PC sends `0xf320`, `0xd820`, `0xd920` again and reads
the next image; to finish it sends `0xef20` and `EndJob`.

### Sequence of a two-page scan

```
VendorCmd ModeShift (jobID " "), 0xf320
StartJob, VendorCmd ModeShift (jobID), 0xdb20 (arg 2)
  0xf320, 0xd820, 0xd920, 0xda20 … until ready, 0xdc20, 0xd420 … page 1, 0xe120
  0xec20 … until 0x01
  0xf320, 0xd820, 0xd920, 0xda20 … until ready, 0xdc20, 0xd420 … page 2, 0xe120
  0xec20 … until 0xff
0xef20, EndJob
```

### Open questions

- Meaning of `0xdc20`, the `0xe120` data and the constant parameter bytes.
- Whether the dialog also works for scans not started from the panel.
