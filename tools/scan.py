#!/usr/bin/env python3
# Probe listed unused command numbers with an empty payload, one at a time, stopping at the first answer.
"""Usage: python3 tools/scan.py TYPE CMD [CMD ...]   (hex or decimal; ranges like 0x05-0x0a)

Unknown commands can do anything, including erase things. Only run the
numbers you mean to, and read each hit before going further.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "py_modules"))

from pixelface import protocol  # noqa: E402
from pixelface.transport import Link  # noqa: E402

KNOWN = {(1, 0x01), (1, 0x02), (1, 0x04), (1, 0x0B), (1, 0x21), (1, 0xF0), (2, 0x02)}


def parse(args):
    out = []
    for arg in args:
        if "-" in arg:
            lo, hi = (int(v, 0) for v in arg.split("-"))
            out += range(lo, hi + 1)
        else:
            out.append(int(arg, 0))
    return out


def healthy(link):
    try:
        return link.command(protocol.power(True), timeout=0.5, retries=2).status == 1
    except Exception:
        return False


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    kind = int(argv[0], 0)
    cmds = [c for c in parse(argv[1:]) if (kind, c) not in KNOWN]
    link = Link(log=lambda m: None).open()
    if not healthy(link):
        print("panel not answering before the scan; stopping")
        return 1
    for cmd in cmds:
        frame = protocol.frame(kind, cmd)
        link.rx.clear()
        link.write(frame)
        got = []
        end = time.monotonic() + 0.4
        while time.monotonic() < end:
            got += link.read_replies(end - time.monotonic())
        raw_junk = bytes(link.rx)
        ok = healthy(link)
        line = "type=%02X cmd=%02X  replies=%s  health=%s" % (kind, cmd, got or "-", "ok" if ok else "FAILED")
        if raw_junk:
            line += "  leftover=%s" % raw_junk.hex(" ")
        print(line, flush=True)
        if not ok:
            print("panel stopped answering; stopping the scan")
            return 1
        if got:
            print("got an answer; stopping here so it can be looked at")
            return 0
    print("no answers")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
