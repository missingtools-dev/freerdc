import unittest

from freerdc.freerdp.certs import has_prompt, parse_certificate_prompt

SAMPLE = """[ERROR] something
Certificate details for 127.0.0.1:33892 (RDP-Server):
\tCommon Name: testhost
\tSubject:     CN = testhost
\tIssuer:      CN = testhost
\tValid from:  Oct 15 14:39:23 2026 GMT
\tValid to:    Oct 17 14:39:23 2026 GMT
\tThumbprint:  40:b3:f5:e3:d8:e4:9c:5a:13:26:43:96:60:ac:78:b0:11:f7:44:8a:67:61:9b:d4:3d:ac:eb:24:a7:10:62:c8
The above X.509 certificate could not be verified.
Do you trust the above certificate? (Y/T/N) """


class CertParseTest(unittest.TestCase):
    def test_parse(self):
        self.assertTrue(has_prompt(SAMPLE))
        c = parse_certificate_prompt(SAMPLE)
        self.assertEqual(c.host, "127.0.0.1:33892")
        self.assertEqual(c.common_name, "testhost")
        self.assertEqual(c.valid_to, "Oct 17 14:39:23 2026 GMT")
        self.assertEqual(c.thumbprint, "40b3f5e3d8e49c5a1326439660ac78b011f7448a67619bd43daceb24a71062c8")
        self.assertTrue(c.pinnable)
        self.assertTrue(c.thumbprint_display.startswith("40:B3:F5"))

    def test_no_certificate(self):
        self.assertIsNone(parse_certificate_prompt("connection refused"))

    def test_v2_style_output_without_question_or_dates(self):
        text = ("Certificate details for 10.0.0.1:3389 (RDP-Server):\n\tCommon Name: h\n"
                "\tThumbprint:  " + ":".join(["ab"] * 32) + "\n")
        self.assertFalse(has_prompt(text))
        self.assertTrue(has_prompt(text + "[ERROR] - certificate not trusted, aborting.\n"))
        c = parse_certificate_prompt(text)
        self.assertEqual(c.valid_from, "")
        self.assertTrue(c.pinnable)


if __name__ == "__main__":
    unittest.main()
