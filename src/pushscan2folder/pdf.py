"""Write JPEG pages into one PDF (stdlib only, images embedded unchanged)."""
from __future__ import annotations

import struct

SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def jpeg_info(data: bytes) -> tuple[int, int, int, tuple[int, int] | None]:
    """Return width, height, components and the JFIF density in dpi (if given)."""
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("not a JPEG")
    dpi = None
    pos = 2
    while pos + 2 <= len(data):
        if data[pos] != 0xFF:
            raise ValueError(f"bad JPEG marker at {pos}")
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:  # standalone, no length
            pos += 2
            continue
        if marker in (0xD9, 0xDA):  # end of image, start of scan: no frame header before
            break
        if pos + 4 > len(data):
            raise ValueError("truncated JPEG")
        (length,) = struct.unpack_from(">H", data, pos + 2)
        if length < 2 or pos + 2 + length > len(data):
            raise ValueError(f"bad JPEG segment length at {pos}")
        seg = data[pos + 4:pos + 2 + length]
        if marker == 0xE0 and seg.startswith(b"JFIF\0") and len(seg) >= 12 and seg[7] == 1:
            dpi = struct.unpack_from(">HH", seg, 8)
        if marker in SOF_MARKERS:
            if len(seg) < 6:
                raise ValueError("truncated JPEG frame header")
            height, width = struct.unpack_from(">HH", seg, 1)
            comps = seg[5]
            if width == 0 or height == 0:
                raise ValueError("JPEG with zero size")
            if comps not in (1, 3, 4):
                raise ValueError(f"unsupported JPEG component count {comps}")
            return width, height, comps, dpi
        pos += 2 + length
    raise ValueError("no JPEG frame header")


def jpegs_to_pdf(pages: list[bytes], default_dpi: int = 300) -> bytes:
    """One page per JPEG; the page size follows the image size and density."""
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    catalog = add(b"")
    tree = add(b"")
    kids = []
    for jpg in pages:
        width, height, comps, dpi = jpeg_info(jpg)
        xdpi, ydpi = dpi if dpi and all(dpi) else (default_dpi, default_dpi)
        space = {1: b"/DeviceGray", 3: b"/DeviceRGB", 4: b"/DeviceCMYK"}[comps]
        img = add(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                  b"/ColorSpace %s /BitsPerComponent 8 /Filter /DCTDecode%s /Length %d >>\n"
                  b"stream\n" % (width, height, space,
                                 b" /Decode [1 0 1 0 1 0 1 0]" if comps == 4 else b"",
                                 len(jpg)) + jpg + b"\nendstream")
        w_pt = width * 72 / xdpi
        h_pt = height * 72 / ydpi
        content = b"q %.2f 0 0 %.2f 0 0 cm /Im0 Do Q" % (w_pt, h_pt)
        cont = add(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] "
                        b"/Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>"
                        % (tree, w_pt, h_pt, img, cont)))
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % tree
    objects[tree - 1] = (b"<< /Type /Pages /Kids [%s] /Count %d >>"
                         % (b" ".join(b"%d 0 R" % k for k in kids), len(kids)))

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, catalog, xref))
    return bytes(out)
