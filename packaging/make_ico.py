"""Build a Windows .ico from PNG files (standard library only).

Usage: python packaging/make_ico.py OUT.ico icon_16.png icon_32.png ...

Each PNG becomes one entry. PNG-compressed entries are valid for every size
since Windows Vista. Sizes come from the PNG headers (256 is stored as 0, as
the ICO format wants)."""
from __future__ import annotations

import struct
import sys

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(data: bytes) -> tuple[int, int]:
    """(width, height) of a PNG. Raises ValueError for anything else."""
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise ValueError("not a PNG file")
    return struct.unpack(">II", data[16:24])


def build_ico(pngs: list[bytes]) -> bytes:
    """ICO file (header, directory, PNG data) for the given PNG images."""
    if not pngs:
        raise ValueError("no images given")
    sizes = [png_size(p) for p in pngs]
    for width, height in sizes:
        if not (1 <= width <= 256 and 1 <= height <= 256):
            raise ValueError(f"size {width}x{height} is not allowed in an ico (1 to 256)")
    header = struct.pack("<HHH", 0, 1, len(pngs))  # reserved, type 1 = icon, count
    offset = len(header) + 16 * len(pngs)
    entries = b""
    for (width, height), data in zip(sizes, pngs):
        # width, height (0 = 256), colours, reserved, planes, bits per pixel, size, offset
        entries += struct.pack("<BBBBHHII", width % 256, height % 256, 0, 0, 1, 32,
                               len(data), offset)
        offset += len(data)
    return header + entries + b"".join(pngs)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    images = []
    for path in argv[2:]:
        with open(path, "rb") as fh:
            images.append(fh.read())
    with open(argv[1], "wb") as fh:
        fh.write(build_ico(images))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
