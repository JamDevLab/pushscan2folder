import unittest

from pushscan2folder import panel
from pushscan2folder.escl import ScanSettings
from pushscan2folder.service import is_complete


def sample(tail: str) -> bytes:
    """Interrupt data as captured: 4 zero bytes, then the given hex, zero padded."""
    return bytes.fromhex("00000000" + tail).ljust(32, b"\0")


# Captured on a TR8550, one panel setting changed per scan.
BASE = sample("0101010101000103030101020000")         # document, colour, A4, PDF, 300 dpi
GRAY = sample("0101010201000103030101020000")
DPI_75 = sample("0101010101000103010101020000")
DPI_600 = sample("0101010101000103040101020000")
LETTER = sample("0101010101000203040101020000")
SIZE_AUTO = sample("0101010101000b03040101020000")
# Photo, auto scan and auto multi scan (several photos on the glass).
PHOTO_AUTO = sample("0101020101000b01030000020000")
PHOTO_MULTI = sample("0101020101000c01030000020000")
JPEG = sample("0101010101000b01040101020000")
COMPACT = sample("0101010101000b04000101010000")
BLEED_MOIRE = sample("0101010101000103030202020000")
PHOTO = sample("0101020101000801030000020000")
AUTO_SCAN = sample("0101030101000000000000000000")
ADF_LEGAL = sample("01010101020003030301010201")
ADF_AUTO = sample("01010301020000000000000000000000000001")


class DecodeTests(unittest.TestCase):
    def test_unknown_values(self):
        self.assertEqual(panel.unknown_values(BASE), [])
        self.assertEqual(panel.unknown_values(PHOTO_MULTI), [])
        self.assertEqual(panel.unknown_values(sample("0101070101000d01030000020000")),
                         ["document type 0x07", "size 0x0d"])

    def test_auto_multi_scans_the_whole_glass(self):
        s = panel.apply(panel.decode(PHOTO_MULTI), ScanSettings())
        self.assertEqual((s.width, s.height), panel.AUTO_REGION)

    def test_base(self):
        p = panel.decode(BASE)
        self.assertEqual((p.doc_type, p.color, p.source, p.size, p.fmt, p.resolution),
                         ("document", "color", "platen", "a4", "pdf", 300))
        self.assertEqual((p.bleed_through, p.descreen, p.unsharp_mask), (False, False, True))

    def test_single_changes(self):
        self.assertEqual(panel.decode(GRAY).color, "gray")
        self.assertEqual(panel.decode(DPI_75).resolution, 75)
        self.assertEqual(panel.decode(DPI_600).resolution, 600)
        self.assertEqual(panel.decode(LETTER).size, "letter")
        self.assertEqual(panel.decode(SIZE_AUTO).size, "auto")
        self.assertEqual(panel.decode(PHOTO_AUTO).size, "auto")
        self.assertEqual(panel.decode(PHOTO_MULTI).size, "auto-multi")
        self.assertEqual(panel.decode(JPEG).fmt, "jpeg")
        p = panel.decode(COMPACT)
        self.assertEqual((p.fmt, p.resolution, p.unsharp_mask), ("pdf-compact", None, False))
        p = panel.decode(BLEED_MOIRE)
        self.assertEqual((p.bleed_through, p.descreen), (True, True))

    def test_tiff_is_saved_as_jpeg(self):
        # Observed: document, colour, platen, A4, TIFF, 300 dpi.
        tiff = bytes.fromhex("0000000001010101010001020301010200000000000000000000000000000000")
        p = panel.decode(tiff)
        self.assertEqual(p.fmt, "tiff")
        self.assertEqual(panel.apply(p, ScanSettings(fmt="pdf")).fmt, "jpeg")

    def test_photo_and_auto(self):
        p = panel.decode(PHOTO)
        self.assertEqual((p.doc_type, p.size, p.fmt, p.resolution), ("photo", "10x15", "jpeg", 300))
        p = panel.decode(AUTO_SCAN)
        self.assertEqual((p.doc_type, p.size, p.fmt, p.resolution), ("auto", None, None, None))

    def test_adf(self):
        self.assertEqual(panel.decode(ADF_LEGAL).source, "adf")
        self.assertEqual(panel.decode(ADF_LEGAL).size, "legal")
        self.assertEqual(panel.decode(ADF_AUTO).source, "adf")

    def test_short_or_empty(self):
        p = panel.decode(b"")
        self.assertIsNone(p.doc_type)
        self.assertEqual(p.describe(), "no settings")


class ApplyTests(unittest.TestCase):
    FALLBACK = ScanSettings(source="platen", color="color", resolution=200, fmt="pdf")

    def test_document_settings_win(self):
        s = panel.apply(panel.decode(GRAY), self.FALLBACK)
        self.assertEqual((s.color, s.resolution, s.fmt, s.width, s.height),
                         ("gray", 300, "pdf", 2480, 3508))

    def test_auto_scan_keeps_fallback(self):
        s = panel.apply(panel.decode(AUTO_SCAN), self.FALLBACK)
        self.assertEqual(s, self.FALLBACK)

    def test_legal_from_adf(self):
        s = panel.apply(panel.decode(ADF_LEGAL), self.FALLBACK)
        self.assertEqual((s.source, s.width, s.height), ("adf", 2550, 4200))

    def test_compact_pdf(self):
        s = panel.apply(panel.decode(COMPACT), self.FALLBACK)
        self.assertEqual((s.fmt, s.resolution), ("pdf", panel.COMPACT_RESOLUTION))

    def test_photo_jpeg(self):
        s = panel.apply(panel.decode(PHOTO), self.FALLBACK)
        self.assertEqual((s.fmt, s.width, s.height), ("jpeg", 1181, 1772))


class CompletenessTests(unittest.TestCase):
    def test_pdf(self):
        self.assertTrue(is_complete(b"%PDF-1.3 ... %%EOF\n", "pdf"))
        self.assertFalse(is_complete(b"%PDF-1.3 ... truncated", "pdf"))

    def test_jpeg(self):
        self.assertTrue(is_complete(b"\xff\xd8 data \xff\xd9", "jpeg"))
        self.assertFalse(is_complete(b"\xff\xd8 data", "jpeg"))


if __name__ == "__main__":
    unittest.main()
