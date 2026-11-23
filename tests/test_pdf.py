import struct
import unittest

from pushscan2folder.pdf import jpeg_info, jpegs_to_pdf


def jpeg(width=10, height=20, comps=3, extra=b""):
    sof = struct.pack(">BHHB", 8, height, width, comps) + b"\x01\x11\x00" * comps
    return (b"\xff\xd8" + extra + b"\xff\xc0" + struct.pack(">H", len(sof) + 2) + sof
            + b"\xff\xd9")


class JpegInfoTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(jpeg_info(jpeg(10, 20, 3)), (10, 20, 3, None))
        self.assertTrue(jpegs_to_pdf([jpeg(10, 20, 1)]).startswith(b"%PDF"))

    def test_standalone_markers_are_skipped(self):
        self.assertEqual(jpeg_info(jpeg(extra=b"\xff\xd0\xff\x01"))[:2], (10, 20))

    def test_malformed_raises_value_error(self):
        good = jpeg()
        bad = [
            good[:12],                              # truncated SOF
            good[:6],                               # length cut off
            jpeg(width=0), jpeg(height=0),
            jpeg(comps=2), jpeg(comps=0),
            b"\xff\xd8\xff\xe0\x00\x01" + good[2:],  # length < 2
            b"\xff\xd8\xff\xc0\x00\x04\x08\x00",   # SOF too short
            b"\xff\xd8",
            b"\xff\xd8\x00\x00\x00\x00",
        ]
        for data in bad:
            with self.assertRaises(ValueError, msg=data.hex()):
                jpeg_info(data)
            with self.assertRaises(ValueError, msg=data.hex()):
                jpegs_to_pdf([data])


if __name__ == "__main__":
    unittest.main()
