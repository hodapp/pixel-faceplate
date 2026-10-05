#!/usr/bin/env python3
# Hold the panel at a sequence of brightness values, checking it still answers, to find its power limit.
"""Usage: python3 tools/steptest.py SECONDS LEVEL [LEVEL ...]

Each level is held for SECONDS while screen power is pinged once a second.
The first missed answer stops the run (the panel probably browned out).
The run always ends by setting brightness 100 if the panel is still there.

This is meant to find the point where the panel browns out, so expect it to.
When it does, anything else on the same USB supply can drop too (my Steam
Controller dongle did), and the panel may get stuck restarting. Have
tools/rescue.py ready and a USB-C port to move the panel to.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "py_modules"))

from pixelface import protocol  # noqa: E402
from pixelface.transport import Link, find_port  # noqa: E402


def alive(link):
    try:
        return link.command(protocol.power(True), timeout=0.4, retries=2).status == 1
    except Exception:
        return False


def main(argv):
    hold = float(argv[0])
    levels = [int(v) for v in argv[1:]]
    link = Link(log=lambda m: None).open()
    started = time.monotonic()
    try:
        for level in levels:
            link.write(bytes(protocol.frame(protocol.TYPE_CONTROL, protocol.CMD_BRIGHTNESS, bytes([level & 0xFF]))))
            print("%5.1fs brightness %d" % (time.monotonic() - started, level), flush=True)
            end = time.monotonic() + hold
            while time.monotonic() < end:
                if not find_port() or not alive(link):
                    print("%5.1fs panel stopped answering at brightness %d" % (time.monotonic() - started, level), flush=True)
                    return 1
                time.sleep(0.6)
        return 0
    finally:
        try:
            if find_port():
                link.write(protocol.brightness(100))
                print("back to 100", flush=True)
        except Exception:
            pass
        link.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
