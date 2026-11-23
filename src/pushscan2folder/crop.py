"""Find photos on a platen scan and cut them out.

Used for the panel scan sizes "auto" (one photo: cut away the empty glass) and
"auto multi" (several photos: one file per photo). The printer always sends
the whole glass; the official software does this step on the PC, too.

Needs Pillow (optional). Without it the whole scan is saved.

How it works, on a small copy of the scan (about 38 dpi):
1. Mark every point that is part of an edge (a brightness step) or that has a
   clear colour. The empty glass is smooth and grey or white, with the lid
   closed or open.
2. Close small gaps (grow, then shrink the marked areas).
3. Each connected area that is large enough is one photo; its bounding box,
   scaled back up, is cut out of the full scan.
"""
from __future__ import annotations

import io
import logging

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
except ImportError:  # optional dependency
    Image = None

log = logging.getLogger(__name__)

ANALYSIS_DPI = 38
EDGE_THRESHOLD = 30      # 0..255 brightness step that counts as an edge
COLOUR_THRESHOLD = 60    # 0..255 saturation that counts as colour
CLOSE_SIZE = 5           # odd; gap closing in analysis pixels (~3 mm)
MIN_SIDE_MM = 15         # smaller areas are dust or noise
JPEG_QUALITY = 95

Box = tuple[int, int, int, int]  # left, top, right, bottom in scan pixels


def available() -> bool:
    return Image is not None


def _mask(small):
    """1 (255) where the small RGB image shows an edge or colour."""
    edges = small.convert("L").filter(ImageFilter.FIND_EDGES)
    # The filter marks the image border itself; that is not an edge.
    ImageDraw.Draw(edges).rectangle((0, 0, edges.width - 1, edges.height - 1),
                                    outline=0, width=2)
    mask = edges.point(lambda v: 255 if v > EDGE_THRESHOLD else 0)
    sat = small.convert("HSV").split()[1]
    mask = ImageChops.lighter(mask, sat.point(lambda v: 255 if v > COLOUR_THRESHOLD else 0))
    return (mask.filter(ImageFilter.MaxFilter(CLOSE_SIZE))
                .filter(ImageFilter.MinFilter(CLOSE_SIZE)))


def _areas(mask) -> list[Box]:
    """Bounding boxes of the connected marked areas (4-neighbourhood)."""
    w, h = mask.size
    data = mask.tobytes()
    seen = bytearray(w * h)
    boxes = []
    for start in range(w * h):
        if not data[start] or seen[start]:
            continue
        seen[start] = 1
        stack = [start]
        x0 = x1 = start % w
        y0 = y1 = start // w
        while stack:
            i = stack.pop()
            x, y = i % w, i // w
            x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
            for j, ok in ((i - 1, x > 0), (i + 1, x < w - 1),
                          (i - w, y > 0), (i + w, y < h - 1)):
                if ok and data[j] and not seen[j]:
                    seen[j] = 1
                    stack.append(j)
        boxes.append((x0, y0, x1 + 1, y1 + 1))
    return boxes


def _overlap(a: Box, b: Box) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _merge(boxes: list[Box]) -> list[Box]:
    """Join boxes that overlap (parts of one photo split by a flat region)."""
    boxes = list(boxes)
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if _overlap(boxes[i], boxes[j]):
                    a, b = boxes[i], boxes.pop(j)
                    boxes[i] = (min(a[0], b[0]), min(a[1], b[1]),
                                max(a[2], b[2]), max(a[3], b[3]))
                    merged = True
                    break
            if merged:
                break
    return boxes


def find_photos(image, dpi: int) -> list[Box]:
    """Boxes of the photos on the scan, top to bottom, then left to right."""
    step = max(1, round(dpi / ANALYSIS_DPI))
    w, h = image.size
    small = image.convert("RGB").resize((max(1, w // step), max(1, h // step)),
                                        Image.BOX)
    min_side = MIN_SIDE_MM / 25.4 * dpi / step
    boxes = [b for b in _merge(_areas(_mask(small)))
             if b[2] - b[0] >= min_side and b[3] - b[1] >= min_side]
    boxes.sort(key=lambda b: (b[1], b[0]))
    return [(b[0] * step, b[1] * step, min(w, b[2] * step), min(h, b[3] * step))
            for b in boxes]


def _encode(image, dpi: int) -> bytes:
    out = io.BytesIO()
    image.save(out, "JPEG", quality=JPEG_QUALITY, dpi=(dpi, dpi))
    return out.getvalue()


def cut_out(jpeg: bytes, dpi: int, multi: bool) -> list[bytes]:
    """The photos on a JPEG scan as JPEGs: one per photo (multi) or one with
    all of them (single). The scan unchanged if nothing is found or Pillow is
    missing."""
    if not available():
        return [jpeg]
    try:
        image = Image.open(io.BytesIO(jpeg))
        image.load()
    except (OSError, ValueError) as exc:
        log.warning("cannot read the scan to cut out photos (%s), saving it whole", exc)
        return [jpeg]
    boxes = find_photos(image, dpi)
    if not boxes:
        log.info("no photo found on the glass, saving the whole scan")
        return [jpeg]
    if not multi:
        boxes = [(min(b[0] for b in boxes), min(b[1] for b in boxes),
                  max(b[2] for b in boxes), max(b[3] for b in boxes))]
    log.info("cut out %d photo(s): %s", len(boxes),
             ", ".join(f"{b[2] - b[0]}x{b[3] - b[1]}" for b in boxes))
    return [_encode(image.crop(b), dpi) for b in boxes]
