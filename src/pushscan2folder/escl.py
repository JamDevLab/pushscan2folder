"""Minimal eSCL (AirScan) client, stdlib only."""
from __future__ import annotations

import http.client
import logging
import re
import time
import urllib.parse
from dataclasses import dataclass

from .client import read_body

log = logging.getLogger(__name__)

NS_SCAN = "http://schemas.hp.com/imaging/escl/2011/05/03"
NS_PWG = "http://www.pwg.org/schemas/2010/12/sm"

FORMATS = {"pdf": "application/pdf", "jpeg": "image/jpeg"}
EXTENSIONS = {"application/pdf": "pdf", "image/jpeg": "jpg"}
COLOR_MODES = {"color": "RGB24", "gray": "Grayscale8"}
SOURCES = {"platen": "Platen", "adf": "Feeder"}

# Bounds for what the printer sends, so a misbehaving device cannot fill
# memory or disk: all documents of one job are held in memory before saving.
MAX_RESPONSE = 1024 * 1024            # status, job creation, error bodies
MAX_DOCUMENT_BYTES = 512 * 1024 * 1024
MAX_JOB_BYTES = 1024 * 1024 * 1024
MAX_DOCUMENTS = 500
CLEANUP_TIMEOUT = 3.0                 # seconds for the best-effort job DELETE
# Total time for one document: an ADF PDF with all pages can stream for long.
DOCUMENT_DEADLINE = 2 * 3600.0

# A4 at 300 dpi in eSCL units (1/300 inch); the printer clamps to its maximum.
A4_WIDTH = 2480
A4_HEIGHT = 3508


class EsclError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScanSettings:
    source: str = "platen"        # platen | adf
    color: str = "color"          # color | gray
    resolution: int = 300
    fmt: str = "pdf"              # pdf | jpeg
    width: int = A4_WIDTH
    height: int = A4_HEIGHT
    x_offset: int = 0             # 1/300 inch, from the left glass edge
    y_offset: int = 0             # 1/300 inch, from the top glass edge


def build_scan_settings(s: ScanSettings) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<scan:ScanSettings xmlns:scan="{NS_SCAN}" xmlns:pwg="{NS_PWG}">'
        "<pwg:Version>2.0</pwg:Version>"
        "<pwg:ScanRegions><pwg:ScanRegion>"
        f"<pwg:Height>{s.height}</pwg:Height>"
        f"<pwg:Width>{s.width}</pwg:Width>"
        f"<pwg:XOffset>{s.x_offset}</pwg:XOffset><pwg:YOffset>{s.y_offset}</pwg:YOffset>"
        "<pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits>"
        "</pwg:ScanRegion></pwg:ScanRegions>"
        f"<pwg:InputSource>{SOURCES[s.source]}</pwg:InputSource>"
        f"<scan:ColorMode>{COLOR_MODES[s.color]}</scan:ColorMode>"
        f"<scan:XResolution>{s.resolution}</scan:XResolution>"
        f"<scan:YResolution>{s.resolution}</scan:YResolution>"
        f"<pwg:DocumentFormat>{FORMATS[s.fmt]}</pwg:DocumentFormat>"
        f"<scan:DocumentFormatExt>{FORMATS[s.fmt]}</scan:DocumentFormatExt>"
        "</scan:ScanSettings>"
    )


def parse_status(xml: str) -> dict[str, str]:
    """Extract scanner state and ADF state from a ScannerStatus document."""
    out = {}
    m = re.search(r"<pwg:State>([^<]+)</pwg:State>", xml)
    if m:
        out["state"] = m.group(1)
    m = re.search(r"<scan:AdfState>([^<]+)</scan:AdfState>", xml)
    if m:
        out["adf"] = m.group(1)
    return out


def job_path(location: str) -> str:
    """ScanJobs answers with an absolute or relative Location; keep only the path."""
    return urllib.parse.urlsplit(location).path.rstrip("/")


class EsclClient:
    def __init__(self, printer: str, port: int = 80, timeout: float = 120.0):
        self.printer = printer
        self.port = port
        self.timeout = timeout

    def _request(self, method: str, path: str, body: bytes | None = None,
                 headers: dict | None = None, limit: int = MAX_RESPONSE,
                 timeout: float | None = None, deadline: float | None = None):
        conn = http.client.HTTPConnection(self.printer, self.port,
                                          timeout=self.timeout if timeout is None else timeout)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, dict(resp.getheaders()), read_body(resp, limit, EsclError, deadline)
        finally:
            conn.close()

    def status(self) -> dict[str, str]:
        code, _, body = self._request("GET", "/eSCL/ScannerStatus")
        if code != 200:
            raise EsclError(f"ScannerStatus: HTTP {code}")
        return parse_status(body.decode("utf-8", "replace"))

    def adf_loaded(self) -> bool:
        return self.status().get("adf") == "ScannerAdfLoaded"

    def _cancel(self, path: str) -> None:
        """Best effort: tell the printer to drop a job that did not end normally."""
        try:
            code, _, _ = self._request("DELETE", path, timeout=CLEANUP_TIMEOUT)
            log.debug("DELETE %s -> HTTP %d", path, code)
        except Exception as exc:   # never hide the original problem
            log.debug("DELETE %s failed: %s", path, exc)

    def scan(self, settings: ScanSettings) -> list[bytes]:
        """Run a scan job and return all documents (one per page for JPEG/ADF)."""
        body = build_scan_settings(settings).encode()
        code, headers, data = self._request(
            "POST", "/eSCL/ScanJobs", body, {"Content-Type": "text/xml"})
        if code != 201:
            raise EsclError(f"ScanJobs: HTTP {code} {data[:200]!r}")
        location = next((v for k, v in headers.items() if k.lower() == "location"), None)
        if not location:
            raise EsclError("ScanJobs: no Location header")
        path = job_path(location)
        log.info("scan job %s", path)
        docs = []
        total = 0
        clean_end = False   # the printer ended the job itself (404 after documents)
        try:
            while True:
                if len(docs) >= MAX_DOCUMENTS or total >= MAX_JOB_BYTES:
                    log.warning("stopping after %d documents (size or count limit)", len(docs))
                    break
                started = time.monotonic()
                try:
                    code, _, data = self._request(
                        "GET", f"{path}/NextDocument",
                        limit=min(MAX_DOCUMENT_BYTES, MAX_JOB_BYTES - total),
                        deadline=DOCUMENT_DEADLINE)
                except (OSError, EsclError) as exc:   # EsclError: over the limit
                    if not docs:
                        raise
                    # Keep what we already have if waiting for a further page fails.
                    log.warning("NextDocument after %d document(s) failed: %s", len(docs), exc)
                    break
                log.debug("NextDocument -> HTTP %d after %.1fs", code, time.monotonic() - started)
                if code == 200:
                    if not data:
                        if docs:
                            log.warning("empty document after %d document(s), stopping", len(docs))
                            break
                        raise EsclError("NextDocument: empty document")
                    docs.append(data)
                    total += len(data)
                    log.info("received document %d (%d bytes)", len(docs), len(data))
                    continue
                if code == 404 and docs:
                    clean_end = True
                    break
                raise EsclError(f"NextDocument: HTTP {code}")
        finally:
            if not clean_end:
                self._cancel(path)
        return docs
