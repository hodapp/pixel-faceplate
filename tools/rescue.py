#!/usr/bin/env python3
# Break a power-starved boot loop: the instant the panel enumerates, blank it and store black.
"""Full white at brightness 100 draws more than the Steam Machine's port gives
(seen: the panel and a Steam Controller dongle dropped off USB together, then
the panel kept resetting because it boots straight into its stored picture).
Run this, then plug the panel in. It waits for the CH340, turns the screen off
before anything else, drops brightness, replaces the stored picture with black
and turns the screen back on.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "py_modules"))

from pixelface import gif, protocol  # noqa: E402
from pixelface.transport import Link, find_port  # noqa: E402

BLACK = gif.encode(protocol.WIDTH, protocol.HEIGHT, [(0, 0, 0), (0, 0, 0)], [bytes(protocol.WIDTH * protocol.HEIGHT)])


def attempt():
    link = Link(log=lambda m: print("  " + m, flush=True)).open()
    try:
        # No waiting for ACKs on the first two: every millisecond lit is current drawn.
        link.write(protocol.power(False))
        link.write(protocol.brightness(20))
        time.sleep(0.05)
        print("screen off, brightness 20", flush=True)
        print("black stored:", link.send_gif(BLACK), flush=True)
        print("power on:", link.command(protocol.power(True)), flush=True)
        link.write(protocol.brightness(20))
        return True
    finally:
        link.close()


def main():
    deadline = time.monotonic() + float(sys.argv[1] if len(sys.argv) > 1 else 300)
    print("waiting for the faceplate; plug it in", flush=True)
    while time.monotonic() < deadline:
        if find_port() and os.access(find_port(), os.R_OK | os.W_OK):
            try:
                if attempt():
                    print("done", flush=True)
                    return 0
            except Exception as error:  # it may drop mid-way; keep trying
                print("attempt failed: %s" % error, flush=True)
        time.sleep(0.01)
    print("gave up waiting", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
