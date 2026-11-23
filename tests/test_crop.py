import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pushscan2folder import crop, protocol
from pushscan2folder.client import ChmpClient
from pushscan2folder.escl import EsclClient, ScanSettings
from pushscan2folder.service import PushScanService, Target

try:
    from PIL import Image
except ImportError:
    Image = None

from test_panel import PHOTO_AUTO, PHOTO_MULTI, BASE

DPI = 300


def glass(background, photos):
    """A scan of the whole glass at 300 dpi with noisy "photos" at the boxes."""
    image = Image.new("RGB", (2550, 3508), background)
    for box in photos:
        w, h = box[2] - box[0], box[3] - box[1]
        noise = Image.effect_noise((w, h), 80).convert("RGB")
        image.paste(noise, box[:2])
    out = io.BytesIO()
    image.save(out, "JPEG", quality=90, dpi=(DPI, DPI))
    return out.getvalue()


def size_of(jpeg):
    return Image.open(io.BytesIO(jpeg)).size


PHOTO_A = (100, 100, 1300, 1900)       # 10x15 cm, upright
PHOTO_B = (200, 2100, 2000, 3300)      # 15x10 cm, across


@unittest.skipIf(Image is None, "Pillow is not installed")
class CutOutTests(unittest.TestCase):
    def assertNear(self, box, expected, tolerance=24):   # 2 mm
        for got, want in zip(box, expected):
            self.assertLessEqual(abs(got - want), tolerance, (box, expected))

    def test_two_photos_lid_closed(self):
        boxes = crop.find_photos(Image.open(io.BytesIO(glass("white", [PHOTO_B, PHOTO_A]))), DPI)
        self.assertEqual(len(boxes), 2)
        self.assertNear(boxes[0], PHOTO_A)   # top first
        self.assertNear(boxes[1], PHOTO_B)

    def test_two_photos_lid_open(self):
        boxes = crop.find_photos(Image.open(io.BytesIO(glass((150, 150, 150),
                                                             [PHOTO_A, PHOTO_B]))), DPI)
        self.assertEqual(len(boxes), 2)

    def test_single_keeps_everything_in_one_picture(self):
        out = crop.cut_out(glass("white", [PHOTO_A, PHOTO_B]), DPI, multi=False)
        self.assertEqual(len(out), 1)
        w, h = size_of(out[0])
        self.assertLess(abs(w - 1900), 50)
        self.assertLess(abs(h - 3200), 50)

    def test_multi_gives_one_file_per_photo(self):
        out = crop.cut_out(glass("white", [PHOTO_A, PHOTO_B]), DPI, multi=True)
        self.assertEqual(len(out), 2)
        self.assertEqual(Image.open(io.BytesIO(out[0])).info["dpi"][0], DPI)

    def test_empty_glass_keeps_the_scan(self):
        data = glass("white", [])
        self.assertEqual(crop.cut_out(data, DPI, multi=True), [data])

    def test_dust_is_ignored(self):
        boxes = crop.find_photos(Image.open(io.BytesIO(
            glass("white", [PHOTO_A, (2200, 200, 2240, 240)]))), DPI)
        self.assertEqual(len(boxes), 1)

    def test_broken_jpeg_is_saved_whole(self):
        self.assertEqual(crop.cut_out(b"\xff\xd8broken", DPI, multi=True), [b"\xff\xd8broken"])


class WithoutPillowTests(unittest.TestCase):
    def test_scan_unchanged(self):
        with mock.patch.object(crop, "Image", None):
            self.assertEqual(crop.cut_out(b"jpeg", DPI, multi=True), [b"jpeg"])

    def test_merge_joins_overlapping_boxes(self):
        self.assertEqual(sorted(crop._merge([(0, 0, 10, 10), (5, 5, 20, 20), (30, 30, 40, 40)])),
                         [(0, 0, 20, 20), (30, 30, 40, 40)])


class CutModeTests(unittest.TestCase):
    def setUp(self):
        self.service = PushScanService(ChmpClient("127.0.0.1", 9), EsclClient("127.0.0.1", 9),
                                       [], ScanSettings())

    def mode(self, interrupt, source="platen"):
        with mock.patch.object(crop, "available", return_value=True):
            return self.service.cut_mode(ScanSettings(source=source), interrupt)

    def test_modes(self):
        self.assertEqual(self.mode(PHOTO_AUTO), "single")
        self.assertEqual(self.mode(PHOTO_MULTI), "multi")
        self.assertIsNone(self.mode(BASE))
        self.assertIsNone(self.mode(PHOTO_MULTI, source="adf"))
        self.assertIsNone(self.mode(b""))

    def test_without_pillow(self):
        with mock.patch.object(crop, "available", return_value=False):
            self.assertIsNone(self.service.cut_mode(ScanSettings(), PHOTO_MULTI))


@unittest.skipIf(Image is None, "Pillow is not installed")
class ServiceCutTests(unittest.TestCase):
    """A whole request against the fake printer: the photos land as files."""

    def setUp(self):
        from test_service import FakePrinter
        from http.server import ThreadingHTTPServer
        import threading
        self.printer = FakePrinter
        FakePrinter.state = {"pending": True, "document": glass("white", [PHOTO_A, PHOTO_B])}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakePrinter)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        port = self.server.server_address[1]
        self.service = PushScanService(ChmpClient("127.0.0.1", port),
                                       EsclClient("127.0.0.1", port),
                                       [Target("TEST", Path(self.tmp.name))],
                                       ScanSettings(), interval=0.01)

    def files(self):
        return sorted(Path(self.tmp.name).iterdir())

    def test_multi_jpeg(self):
        self.printer.state["interrupt"] = PHOTO_MULTI
        self.service.step()
        self.assertIn("image/jpeg", self.printer.state["settings"])
        self.assertEqual([f.suffix for f in self.files()], [".jpg", ".jpg"])

    def test_multi_pdf_gives_one_pdf_per_photo(self):
        self.printer.state["interrupt"] = PHOTO_MULTI[:11] + bytes([3]) + PHOTO_MULTI[12:]
        self.service.step()
        self.assertIn("image/jpeg", self.printer.state["settings"])   # asked as JPEG
        files = self.files()
        self.assertEqual([f.suffix for f in files], [".pdf", ".pdf"])
        self.assertTrue(files[0].read_bytes().startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
