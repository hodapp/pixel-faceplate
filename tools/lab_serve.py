#!/usr/bin/env python3
# Keep the faceplate's port open and run frames read from stdin, so a remote driver needn't reconnect per frame.
"""Usage: lab_serve.py PORT   (then write lines on stdin)

    TYPE CMD [HEX]    send one frame; prints one JSON line: replies, junk, alive
    ping              prints {"alive": true|false}

Uses lab.py's guard and log (PAST_GUARD applies the same way).
"""

import json
import sys

import lab


def main(argv):
    port = lab.open_port(argv[1])
    for line in sys.stdin:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "ping":
            out = {"alive": lab.ping(port)}
        else:
            kind, cmd = int(parts[0], 16), int(parts[1], 16)
            payload = bytes.fromhex(parts[2]) if len(parts) > 2 else b""
            try:
                replies, junk = lab.exchange(port, kind, cmd, payload, wait=0.3)
                out = {"replies": [r.payload.hex() for r in replies], "junk": junk.hex(), "alive": lab.ping(port)}
            except SystemExit as refused:
                out = {"refused": str(refused)}
        print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main(sys.argv)
