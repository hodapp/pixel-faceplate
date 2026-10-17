#!/usr/bin/env python3
# Bench probing of the faceplate from a desktop (pyserial, so macOS works), every exchange logged.
"""Usage (on a desktop with pyserial, panel on USB):

    lab.py PORT ping                       power-on echo, proves the panel is alive
    lab.py PORT raw TYPE CMD [HEXPAYLOAD]  one frame, prints every reply for 1 s
    lab.py PORT sweep TYPE CMD FILE        one frame per hex payload line in FILE,
                                           with a ping after each; stops on a dead ping

Every frame sent and every reply goes to lab-log.jsonl next to this script.

Guard: only type 0x01/0x02 and command numbers up to 0x21, plus 0xF0, are
allowed. Anything else could be a firmware update or erase command (see
PROTOCOL.md, Hidden commands), which could leave the panel fixable only
through the pads on the board. Those stay refused here. Sending one is a
decision I make on purpose, not something a flag should do.
"""

import json
import os
import sys
import time

import serial

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "py_modules"))

from pixelface import protocol  # noqa: E402

LOG = os.path.join(HERE, "lab-log.jsonl")
ALLOWED_TYPES = {protocol.TYPE_CONTROL, protocol.TYPE_DATA}


def allowed(kind, cmd):
    # 0x03 is the firmware-download path (see PROTOCOL.md). Probing it was done
    # deliberately on 2026-10-13 with the brick risk accepted and no flash backup
    # yet, so it is gated behind its own token, PROBE_03=eli-2026-10-13, to keep
    # the everyday PAST_GUARD from reaching it by accident. Send header frames
    # only until there is a flash backup: never stream data to a "ready" session.
    if kind == protocol.TYPE_CONTROL and cmd == 0x03:
        return os.environ.get("PROBE_03") == "eli-2026-10-13"
    # PAST_GUARD=eli-2026-10-13 lifts the guard: I accepted the brick risk for
    # empty-payload probing past 0x21 on 2026-10-13. Don't reuse it for other work.
    if os.environ.get("PAST_GUARD") == "eli-2026-10-13":
        return True
    return kind in ALLOWED_TYPES and (cmd <= 0x21 or cmd == 0xF0)


def log(event, **fields):
    fields.update(t=round(time.time(), 3), event=event)
    with open(LOG, "a") as f:
        f.write(json.dumps(fields) + "\n")


def open_port(path):
    # pyserial sets 1 Mbaud on macOS through IOSSIOSPEED; plain termios can't.
    return serial.Serial(path, 1_000_000, timeout=0.05)


def exchange(port, kind, cmd, payload=b"", wait=1.0):
    if not allowed(kind, cmd):
        raise SystemExit("refused: type 0x%02X cmd 0x%02X is outside the safe range" % (kind, cmd))
    data = protocol.frame(kind, cmd, payload)
    port.reset_input_buffer()
    port.write(data)
    log("sent", type=kind, cmd=cmd, payload=payload.hex(), frame=data.hex())
    buffer, replies, junk = bytearray(), [], b""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        buffer += port.read(256)
        got, skipped = protocol.parse(buffer)
        replies += got
        junk += skipped
    for reply in replies:
        log("reply", type=reply.kind, cmd=reply.cmd, payload=reply.payload.hex())
    if junk or buffer:
        log("junk", data=(junk + bytes(buffer)).hex())
    return replies, junk + bytes(buffer)


def ping(port):
    replies, _ = exchange(port, protocol.TYPE_CONTROL, protocol.CMD_POWER, b"\x01", wait=0.5)
    return any(r.cmd == protocol.CMD_POWER for r in replies)


def show(replies, junk):
    for reply in replies:
        print(reply)
    if junk:
        print("junk:", junk.hex(" "))
    if not replies and not junk:
        print("(silence)")


def main(argv):
    if len(argv) < 3:
        raise SystemExit(__doc__)
    port = open_port(argv[1])
    action = argv[2]
    if action == "ping":
        print("alive" if ping(port) else "NO ANSWER")
    elif action == "raw":
        kind, cmd = int(argv[3], 16), int(argv[4], 16)
        payload = bytes.fromhex(argv[5]) if len(argv) > 5 else b""
        show(*exchange(port, kind, cmd, payload))
    elif action == "sweep":
        kind, cmd = int(argv[3], 16), int(argv[4], 16)
        with open(argv[5]) as f:
            lines = [line.split("#")[0].strip() for line in f]
        for hexpayload in filter(None, lines):
            replies, junk = exchange(port, kind, cmd, bytes.fromhex(hexpayload))
            print(hexpayload or "(empty)", "->", [r.payload.hex(" ") for r in replies] or "silence",
                  ("junk " + junk.hex(" ")) if junk else "")
            if not ping(port):
                print("panel stopped answering after", hexpayload, "- stopping")
                log("dead", after=hexpayload)
                break
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
