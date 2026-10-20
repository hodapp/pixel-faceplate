# Check the termios stand-in against the real termios on a Linux pty.

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from pixelface import termios_compat as compat  # noqa: E402

try:
    import termios
except ImportError:
    termios = None


@unittest.skipUnless(sys.platform.startswith("linux") and termios, "needs Linux with the real termios to compare")
class TermiosCompatTest(unittest.TestCase):
    def setUp(self):
        self.master, self.slave = os.openpty()

    def tearDown(self):
        os.close(self.master)
        os.close(self.slave)

    def test_constants_match(self):
        for name in ("TCSANOW", "TCIOFLUSH", "CS8", "CREAD", "CLOCAL", "B115200", "B1000000",
                     "VMIN", "VTIME", "CBAUD"):
            self.assertEqual(getattr(compat, name), getattr(termios, name), name)

    def test_get_matches(self):
        real = termios.tcgetattr(self.slave)
        ours = compat.tcgetattr(self.slave)
        self.assertEqual(ours[:4], real[:4])
        self.assertEqual(ours[4], real[4])
        self.assertEqual(ours[6][:compat.NCCS], real[6][:compat.NCCS])

    def test_set_like_transport_then_read_with_real(self):
        cc = compat.tcgetattr(self.slave)[6]
        cc[compat.VMIN] = 0
        cc[compat.VTIME] = 0
        cflag = compat.CS8 | compat.CREAD | compat.CLOCAL
        compat.tcsetattr(self.slave, compat.TCSANOW, [0, 0, cflag, 0, compat.B1000000, compat.B1000000, cc])
        compat.tcflush(self.slave, compat.TCIOFLUSH)
        iflag, oflag, got_cflag, lflag, ispeed, ospeed, got_cc = termios.tcgetattr(self.slave)
        self.assertEqual((iflag, oflag, lflag), (0, 0, 0))
        self.assertEqual(got_cflag & ~termios.CBAUD, cflag)
        self.assertEqual((ispeed, ospeed), (termios.B1000000, termios.B1000000))
        self.assertEqual(got_cc[termios.VMIN], 0)
        self.assertEqual(got_cc[termios.VTIME], 0)

    def test_drain_returns(self):
        os.write(self.slave, b"x")
        compat.tcdrain(self.slave)


if __name__ == "__main__":
    unittest.main()
