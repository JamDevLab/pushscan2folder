import struct
import unittest

from pushscan2folder import protocol

# Real responses captured from a Canon TR8550.
REGISTER_RESPONSE = bytes.fromhex(
    "00000000000002db00000024" + "00" * 40)
SCAN_REQUEST_RESPONSE = bytes.fromhex(
    "00008000000002db00000024c5f16de8000000000101030101000000"
    "000000000000000000000000000000000000000000000000")


class RequestTests(unittest.TestCase):
    def test_register_layout(self):
        body = protocol.build_register("LINUX  CANON-SCANNER")
        self.assertEqual(len(body), protocol.REQUEST_SIZE)
        self.assertEqual(body[:8], bytes.fromhex("0001000000000000"))
        self.assertEqual(body[8:8 + 10], "LINUX".encode("utf-16-be"))
        self.assertEqual(body[0x48:], b"\0" * (protocol.REQUEST_SIZE - 0x48))

    def test_register_matches_capture(self):
        captured = bytes.fromhex(
            "0001000000000000004c0049004e005500580020002000430041004e004f004e002d"
            "005300430041004e004e0045005200")
        body = protocol.build_register("LINUX  CANON-SCANNER")
        self.assertEqual(body[:len(captured)], captured)

    def test_poll_and_release(self):
        self.assertEqual(protocol.build_poll(0x2DB)[:8], bytes.fromhex("00020000000002db"))
        self.assertEqual(protocol.build_release(0x2DB)[:8], bytes.fromhex("00040000000002db"))
        self.assertEqual(protocol.build_poll(1)[8:], b"\0" * (protocol.REQUEST_SIZE - 8))

    def test_name_is_truncated_and_terminated(self):
        raw = protocol.encode_name("X" * 50)
        self.assertEqual(len(raw), protocol.NAME_BYTES)
        self.assertEqual(raw[-2:], b"\0\0")
        self.assertEqual(raw[:62].decode("utf-16-be"), "X" * 31)

    def test_default_name(self):
        self.assertEqual(protocol.default_name("anna", "pc1"), "anna  pc1")


class ResponseTests(unittest.TestCase):
    def test_register_response(self):
        r = protocol.parse_response(REGISTER_RESPONSE)
        self.assertEqual(r.status, 0)
        self.assertEqual(r.session, 0x2DB)
        self.assertFalse(r.scan_requested)
        self.assertEqual(r.raw, REGISTER_RESPONSE)

    def test_scan_request_response(self):
        r = protocol.parse_response(SCAN_REQUEST_RESPONSE)
        self.assertTrue(r.scan_requested)
        self.assertEqual(r.event, 0xC5F16DE8)
        self.assertEqual(r.interrupt[:10], bytes.fromhex("00000000010103010100"))
        self.assertEqual(len(r.interrupt), 32)

    def test_full_size_response(self):
        data = bytearray(protocol.RESPONSE_SIZE)
        struct.pack_into(">H", data, 2, 0x8000)
        struct.pack_into(">I", data, 0x8C, 7)
        self.assertEqual(protocol.parse_response(bytes(data)).unknown8c, 7)

    def test_too_short(self):
        with self.assertRaises(ValueError):
            protocol.parse_response(b"\0" * 4)


class NameTests(unittest.TestCase):
    """Observed on a TR8550: the panel shows only A-Z, a-z, 0-9, space, - _ @."""

    def test_allowed(self):
        for name in ("scan1", "Mein Ordner", "Office  PC", "a-b_c@d", "x" * 31):
            protocol.check_name(name)

    def test_rejected(self):
        for name in ("A.B", "A&B", "Müller", "Café", "Emoji 📄", "日本語", "a/b", "", "  ", "x" * 32):
            with self.assertRaises(ValueError, msg=name):
                protocol.check_name(name)

    def test_error_names_the_characters(self):
        with self.assertRaises(ValueError) as cm:
            protocol.check_name("Ä.Ä.b")
        self.assertIn("'Ä' '.'", str(cm.exception))

    def test_panel_safe(self):
        self.assertEqual(protocol.panel_safe("jürgen  my.host"), "j-rgen  my-host")
        self.assertEqual(len(protocol.panel_safe("y" * 40)), 31)


if __name__ == "__main__":
    unittest.main()
