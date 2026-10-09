#!/usr/bin/env python3
# Poke the JSAUX PIXEL faceplate by hand: raw frames, power, brightness, solid colors, GIFs.
"""Usage (on the Steam Machine, from the plugin folder):

    python3 tools/probe.py power on|off
    python3 tools/probe.py bright 0-100
    python3 tools/probe.py builtin N
    python3 tools/probe.py raw TYPE CMD [HEXPAYLOAD]
    python3 tools/probe.py solid R G B
    python3 tools/probe.py bars
    python3 tools/probe.py gif FILE

solid, bars and gif each write one picture to the panel's flash.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "py_modules"))

from pixelface import gif, protocol  # noqa: E402
from pixelface.service import frame_load, safe_brightness  # noqa: E402
from pixelface.transport import Link  # noqa: E402

W, H = protocol.WIDTH, protocol.HEIGHT


def log(message):
    print("  " + message, file=sys.stderr)


def show(reply):
    print(reply)


def solid_gif(r, g, b):
    return gif.encode(W, H, [(r, g, b), (0, 0, 0)], [bytes(W * H)])


def bars_gif():
    colors = [(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0),
               (255, 0, 255), (255, 0, 0), (0, 0, 255), (0, 0, 0)]
    frame = bytes((x * 8 // W) for y in range(H) for x in range(W))
    return gif.encode(W, H, colors, [frame])


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    op, args = argv[0], argv[1:]
    with Link(log=log) as link:
        print("port", link.port)
        if op == "power":
            show(link.command(protocol.power(args[0] == "on")))
        elif op == "bright":
            show(link.command(protocol.brightness(int(args[0]))))
        elif op == "builtin":
            show(link.command(protocol.builtin(int(args[0], 0))))
        elif op == "raw":
            payload = bytes.fromhex(args[2]) if len(args) > 2 else b""
            show(link.command(protocol.frame(int(args[0], 0), int(args[1], 0), payload), retries=1))
        elif op in ("solid", "bars", "gif"):
            if op == "solid":
                rgb = [int(v) for v in args[:3]]
                data = solid_gif(*rgb)
                # Same power guard as the plugin: solid white at 100 boot-looped the panel.
                cap = safe_brightness(100, frame_load(bytes(rgb)))
                if cap < 100:
                    link.write(protocol.brightness(cap))
                    print("brightness capped at %d for this color" % cap)
            elif op == "bars":
                data = bars_gif()
            else:
                with open(args[0], "rb") as handle:
                    data = handle.read()
            started = time.monotonic()
            wrote = link.send_gif(data)
            print("%s: %d bytes in %.0f ms" % ("written" if wrote else "panel already had it",
                                              len(data), (time.monotonic() - started) * 1000))
        else:
            print(__doc__)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
