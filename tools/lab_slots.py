#!/usr/bin/env python3
# Find out whether the faceplate keeps more than one GIF (re-selectable without a flash write).
"""Usage: lab_slots.py PORT

Uploads solid GIF A, then solid GIF B, then asks for A again. A 02 reply
for A means the panel still holds A after storing B, so stored GIFs can be
switched without writing flash. Every step is timed and logged to
lab-log.jsonl. Costs at most three flash writes.
"""

import sys
import time

import lab
from lab import protocol
from pixelface import gif

W, H = protocol.WIDTH, protocol.HEIGHT


def solid(r, g, b):
    return gif.encode(W, H, [(r, g, b), (0, 0, 0)], [bytes(W * H)])


def until_reply(port, data, cmd, timeout=2.0):
    """Send one frame, return (reply, seconds) for the first reply to cmd."""
    port.reset_input_buffer()
    start = time.monotonic()
    port.write(data)
    buffer = bytearray()
    while time.monotonic() - start < timeout:
        buffer += port.read(256)
        replies, _ = protocol.parse(buffer)
        for reply in replies:
            lab.log("reply", type=reply.kind, cmd=reply.cmd, payload=reply.payload.hex())
            if reply.cmd == cmd:
                return reply, time.monotonic() - start
    return None, time.monotonic() - start


def begin(port, picture, name):
    lab.exchange(port, protocol.TYPE_CONTROL, protocol.CMD_FACTORY_TEST, b"\x00", wait=0.02)
    reply, took = until_reply(port, protocol.gif_begin(picture), protocol.CMD_GIF_BEGIN)
    status = reply.status if reply else None
    print("begin %s (%d B): status %s in %.0f ms" % (name, len(picture), status, took * 1000))
    lab.log("begin", gif=name, size=len(picture), status=status, ms=round(took * 1000))
    return status


def finish(port, name):
    reply, took = until_reply(port, protocol.gif_end(), protocol.CMD_GIF_END)
    status = reply.status if reply else None
    print("end %s: status %s in %.0f ms" % (name, status, took * 1000))
    lab.log("end", gif=name, status=status, ms=round(took * 1000))
    return status


def upload(port, picture, name):
    status = begin(port, picture, name)
    if status == 0x01:
        for chunk in protocol.gif_chunks(picture):
            time.sleep(0.012)
            reply, _ = until_reply(port, chunk, protocol.CMD_GIF_CHUNK)
            if not reply or reply.status != 0x01:
                raise SystemExit("chunk refused: %r" % (reply,))
    finish(port, name)
    return status


def main(argv):
    port = lab.open_port(argv[1])
    a, b = solid(90, 0, 40), solid(0, 40, 90)
    upload(port, a, "A")
    time.sleep(0.2)
    upload(port, b, "B")
    time.sleep(0.2)
    status = upload(port, a, "A again")
    print("RESULT:", "panel kept A after B (multi-slot)" if status == 0x02
          else "A had to be uploaded again (one slot)")
    print("alive" if lab.ping(port) else "NO ANSWER")


if __name__ == "__main__":
    main(sys.argv)
