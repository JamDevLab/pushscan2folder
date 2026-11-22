"""Decode the 32 bytes of interrupt data the printer sends with a scan request.

The layout was determined on a Canon TR8550 by changing one panel setting per
scan and comparing the bytes (see docs/PROTOCOL.md):

  offset  field              values
  0-3     -                  always 0
  4, 5    -                  always 1
  6       document type      1 document, 2 photo, 3 auto scan
  7       colour             1 colour, 2 black and white
  8       source             1 platen, 2 ADF
  10      size               1 A4, 2 Letter, 3 Legal, 8 10x15cm, 9 13x18cm, 0x0b auto
  11      format             1 JPEG, 2 TIFF, 3 PDF, 4 compact PDF
  12      resolution         1 75, 2 150, 3 300, 4 600 dpi (0 with compact PDF)
  13      reduce bleed-through  1 off, 2 on
  14      descreen (moire)   1 off, 2 on
  15      unsharp mask       1 off, 2 on
  16      ADF orientation?   1 when scanning from the ADF, else 0 (unconfirmed)

With "auto scan" only the type, colour and source fields are set, the printer
leaves the rest to the PC. Fields that are 0 or unknown are returned as None.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .escl import ScanSettings

log = logging.getLogger(__name__)

DOC_TYPES = {1: "document", 2: "photo", 3: "auto"}
COLORS = {1: "color", 2: "gray"}
SOURCES = {1: "platen", 2: "adf"}
SIZES = {1: "a4", 2: "letter", 3: "legal", 8: "10x15", 9: "13x18", 0x0B: "auto"}
FORMATS = {1: "jpeg", 2: "tiff", 3: "pdf", 4: "pdf-compact"}
RESOLUTIONS = {1: 75, 2: 150, 3: 300, 4: 600}

# Scan regions in 1/300 inch (eSCL ThreeHundredthsOfInches), portrait.
REGIONS = {
    "a4": (2480, 3508),
    "letter": (2550, 3300),
    "legal": (2550, 4200),
    "10x15": (1181, 1772),
    "13x18": (1535, 2126),
}
# "auto" has no eSCL equivalent: scan the full platen width at A4 height.
AUTO_REGION = (2550, 3508)
# Compact PDF carries no resolution; use a moderate one.
COMPACT_RESOLUTION = 300


def _flag(value: int) -> bool | None:
    return {1: False, 2: True}.get(value)


@dataclass(frozen=True)
class PanelSettings:
    doc_type: str | None
    color: str | None
    source: str | None
    size: str | None
    fmt: str | None
    resolution: int | None
    bleed_through: bool | None
    descreen: bool | None
    unsharp_mask: bool | None
    raw: bytes

    def describe(self) -> str:
        parts = [f"{k}={v}" for k, v in (
            ("type", self.doc_type), ("color", self.color), ("source", self.source),
            ("size", self.size), ("format", self.fmt), ("dpi", self.resolution),
            ("bleed_through", self.bleed_through), ("descreen", self.descreen),
            ("unsharp_mask", self.unsharp_mask)) if v is not None]
        return " ".join(parts) or "no settings"


def decode(data: bytes) -> PanelSettings:
    b = bytes(data).ljust(32, b"\0")
    return PanelSettings(
        doc_type=DOC_TYPES.get(b[6]),
        color=COLORS.get(b[7]),
        source=SOURCES.get(b[8]),
        size=SIZES.get(b[10]),
        fmt=FORMATS.get(b[11]),
        resolution=RESOLUTIONS.get(b[12]),
        # Possible future addition: apply these three on the PC (image processing).
        bleed_through=_flag(b[13]),
        descreen=_flag(b[14]),
        unsharp_mask=_flag(b[15]),
        raw=bytes(data),
    )


def apply(panel: PanelSettings, fallback: ScanSettings) -> ScanSettings:
    """Combine panel settings with the configured defaults.

    Every field the panel does not set (e.g. in "auto scan" mode) keeps the
    fallback value. Bleed-through, descreen and unsharp mask have no eSCL
    counterpart and are ignored.
    """
    width, height = fallback.width, fallback.height
    if panel.size == "auto":
        width, height = AUTO_REGION
    elif panel.size in REGIONS:
        width, height = REGIONS[panel.size]

    fmt = fallback.fmt
    resolution = panel.resolution or fallback.resolution
    if panel.fmt == "pdf-compact":
        fmt = "pdf"
        resolution = panel.resolution or COMPACT_RESOLUTION
    elif panel.fmt in ("pdf", "jpeg"):
        fmt = panel.fmt
    elif panel.fmt == "tiff":
        # Neither eSCL nor the native protocol (so far) delivers TIFF; JPEG is
        # the closest format (one image file per page).
        log.info("TIFF is not supported, saving JPEG instead")
        fmt = "jpeg"

    return ScanSettings(
        source=panel.source or fallback.source,
        color=panel.color or fallback.color,
        resolution=resolution,
        fmt=fmt,
        width=width,
        height=height,
    )
