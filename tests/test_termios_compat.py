"""Decky 3.3's bundled Python has no termios: the plugin must load and drive a port without it."""

import importlib
import os
import sys
import termios as real
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from pixelface import termios_compat as shim  # noqa: E402


class ShimTest(unittest.TestCase):
    def setUp(self):
        self.master, self.slave = os.openpty()

    def tearDown(self):
        os.close(self.master)
        os.close(self.slave)

    def test_same_constants_as_termios(self):
        for name in ("TCSANOW", "TCIOFLUSH", "CS8", "CREAD", "CLOCAL", "B115200", "B1000000", "VTIME", "VMIN"):
            self.assertEqual(getattr(shim, name), getattr(real, name), name)

    def test_reads_what_termios_reads(self):
        ours, theirs = shim.tcgetattr(self.slave), real.tcgetattr(self.slave)
        self.assertEqual(ours[:6], theirs[:6])

    def test_sets_what_termios_sees(self):
        cc = shim.tcgetattr(self.slave)[6]
        cc[shim.VMIN] = cc[shim.VTIME] = 0
        shim.tcsetattr(self.slave, shim.TCSANOW,
                       [0, 0, shim.CS8 | shim.CREAD | shim.CLOCAL, 0, shim.B1000000, shim.B1000000, cc])
        attrs = real.tcgetattr(self.slave)
        self.assertEqual(attrs[4], real.B1000000)
        self.assertEqual(attrs[2] & ~real.CBAUD, real.CS8 | real.CREAD | real.CLOCAL)
        self.assertEqual((attrs[0], attrs[1], attrs[3]), (0, 0, 0))


class WithoutTermiosTest(unittest.TestCase):
    def test_transport_loads_and_talks_without_termios(self):
        with mock.patch.dict(sys.modules, {"termios": None}):  # import termios raises ImportError
            sys.modules.pop("pixelface.transport", None)
            transport = importlib.import_module("pixelface.transport")
            self.assertIs(transport.termios, shim)
            master, slave = os.openpty()
            try:
                link = transport.Link(port=os.ttyname(slave)).open()
                link.write(b"DY ping")
                self.assertEqual(os.read(master, 64), b"DY ping")
                link.close()
            finally:
                os.close(master)
                os.close(slave)
        sys.modules.pop("pixelface.transport", None)
        importlib.import_module("pixelface.transport")


if __name__ == "__main__":
    unittest.main()
