"""HTTP transport for the CHMP push-scan protocol (stdlib only)."""
from __future__ import annotations

import http.client
import logging

from . import protocol

log = logging.getLogger(__name__)


# CHMP answers are a few hundred bytes.
MAX_CHMP_RESPONSE = 64 * 1024


class ChmpError(RuntimeError):
    pass


def read_body(resp: http.client.HTTPResponse, limit: int, error=RuntimeError) -> bytes:
    """Read a response body of at most `limit` bytes, so a misbehaving
    printer cannot fill the memory. Raises `error` if it is larger."""
    if resp.length is not None and resp.length > limit:
        raise error(f"response of {resp.length} bytes exceeds the limit of {limit}")
    data = resp.read(limit + 1)
    if len(data) > limit:
        raise error(f"response exceeds the limit of {limit} bytes")
    return data


class ChmpClient:
    def __init__(self, printer: str, port: int = 80, timeout: float = 10.0):
        self.printer = printer
        self.port = port
        self.timeout = timeout

    def exchange(self, body: bytes) -> protocol.Response:
        conn = http.client.HTTPConnection(self.printer, self.port, timeout=self.timeout)
        try:
            headers = dict(protocol.HEADERS)
            headers["Content-Length"] = str(len(body))
            log.debug("POST %s body=%s", protocol.PATH, body.hex())
            conn.request("POST", protocol.PATH, body=body, headers=headers)
            resp = conn.getresponse()
            data = read_body(resp, MAX_CHMP_RESPONSE, ChmpError)
            log.debug("HTTP %s %s body=%s", resp.status, resp.reason, data.hex())
            if resp.status != 200:
                raise ChmpError(f"HTTP {resp.status} {resp.reason}")
            return protocol.parse_response(data)
        finally:
            conn.close()

    def register(self, name: str) -> protocol.Response:
        return self.exchange(protocol.build_register(name))

    def poll(self, session: int) -> protocol.Response:
        return self.exchange(protocol.build_poll(session))

    def release(self, session: int) -> protocol.Response:
        return self.exchange(protocol.build_release(session))
