#!/usr/bin/env python3
# Test whether small GIFs survive a real power cut (JSAUX: "only GIFs over 20 KB use flash").

"""Usage: python3 tools/flashtest.py HUB PORT CAMERA_URL OUTDIR [case ...]

For each case: upload a GIF of a set size and look, photograph it, cut the
panel's USB power with uhubctl (HUB, PORT), power it back on, photograph what
it shows, then send the same GIF's begin frame again: 02 means the panel still
holds that size+CRC, 01 means it doesn't (and the port is cycled again to drop
the half-open upload). Every case is one flash write, so keep the list short.

Cases are NAME=KIND:BYTES:HUE, KIND = static (one frame) or anim.
"""

import glob
import json
import os
import random
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "py_modules"))

from pixelface import gif, protocol  # noqa: E402
import serial  # noqa: E402  pyserial: sets 1 Mbaud on macOS too, which plain termios can't

W, H = protocol.WIDTH, protocol.HEIGHT
# Dim on purpose: no channel above ~half, so a stored test GIF can't brown out a USB-A port at power-up.
HUES = {"red": (1, 0, 0), "green": (0, 1, 0), "blue": (0, 0, 1), "yellow": (1, 1, 0),
        "magenta": (1, 0, 1), "cyan": (0, 1, 1), "orange": (1, 0.5, 0), "white": (1, 1, 1)}
DEFAULT = ["s1k=static:1000:red", "a5k=anim:5000:green", "a10k=anim:10000:blue", "a15k=anim:15000:yellow",
           "a19k=anim:19000:magenta", "a21k=anim:21000:cyan", "a30k=anim:30000:orange",
           "s5k=static:5000:white"]


def palette(hue, n):
    return [tuple(int(c * (40 + 90 * i / (n - 1))) for c in hue) for i in range(n)]


def make(kind, target, hue, seed):
    """Noise in shades of one hue, grown until the file reaches the target size.
    Static: one frame, size set by the share of noisy pixels and the palette depth.
    Anim: noisy 16-shade frames, the last one partly flat to land on the target."""
    rng = random.Random(seed)
    if kind == "static":
        n = 256 if target > 2400 else 16
        pal = palette(hue, n)
        noise = [rng.randrange(n) for _ in range(W * H)]
        lo, hi = 0, W * H
        while lo < hi:  # fewest noisy pixels that still reach the target
            mid = (lo + hi) // 2
            data = gif.encode(W, H, pal, [noise[:mid] + [n // 2] * (W * H - mid)])
            lo, hi = (mid + 1, hi) if len(data) < target else (lo, mid)
        return gif.encode(W, H, pal, [noise[:lo] + [n // 2] * (W * H - lo)])
    pal = palette(hue, 16)
    frames = []
    while True:
        full = [rng.randrange(16) for _ in range(W * H)]
        lo, hi = 0, W * H
        while lo < hi:
            mid = (lo + hi) // 2
            data = gif.encode(W, H, pal, frames + [full[:mid] + [8] * (W * H - mid)], 20)
            lo, hi = (mid + 1, hi) if len(data) < target else (lo, mid)
        if lo < W * H:
            return gif.encode(W, H, pal, frames + [full[:lo] + [8] * (W * H - lo)], 20)
        frames.append(full)


def snap(url, path):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-rtsp_transport", "tcp", "-y", "-i", url,
                    "-frames:v", "1", path], timeout=30)


def hub(hub_id, port, action):
    subprocess.run(["uhubctl", "-l", hub_id, "-p", port, "-a", action], capture_output=True, timeout=30)


class Link:
    def __init__(self, path):
        self.port = serial.Serial(path, 1_000_000, timeout=0.02)

    def command(self, data, timeout=1.0):
        """Send one frame, return the reply with the same type and cmd (status None on silence)."""
        self.port.reset_input_buffer()
        self.port.write(data)
        buffer, end = bytearray(), time.monotonic() + timeout
        while time.monotonic() < end:
            buffer += self.port.read(64)
            for reply in protocol.parse(buffer)[0]:
                if reply.kind == data[2] and reply.cmd == data[3]:
                    return reply
        return protocol.Reply(data[2], data[3], b"")

    def close(self):
        self.port.close()


def open_link():
    for _ in range(40):
        ports = sorted(glob.glob("/dev/cu.usbserial-*") + glob.glob("/dev/ttyUSB*"))
        if ports:
            try:
                return Link(ports[0])
            except Exception:
                pass
        time.sleep(0.5)
    raise SystemExit("panel did not come back on USB")


def cycle(hub_id, port):
    hub(hub_id, port, "off")
    time.sleep(5)  # long enough for the panel's caps to drain (dark on camera at 4 s)
    hub(hub_id, port, "on")
    time.sleep(8)


def main():
    hub_id, port, url, outdir = sys.argv[1:5]
    cases = sys.argv[5:] or DEFAULT
    os.makedirs(outdir, exist_ok=True)
    log = open(os.path.join(outdir, "results.jsonl"), "a")
    seed = int(time.time())  # fresh CRCs every run, so "already stored" can't fake a result
    for i, case in enumerate(cases):
        name, spec = case.split("=")
        kind, target, hue = spec.split(":")
        data = make(kind, int(target), HUES[hue], seed + i)
        row = {"name": name, "kind": kind, "hue": hue, "bytes": len(data), "frames": data.count(b"\x21\xF9\x04") or 1}
        link = open_link()
        t0 = time.monotonic()
        begin = link.command(protocol.gif_begin(data))
        row["begin"] = begin.status
        if begin.status == 1:
            for chunk in protocol.gif_chunks(data):
                link.command(chunk)
            t1 = time.monotonic()
            end = link.command(protocol.gif_end(), timeout=10)
            row["end"] = end.status
            row["end_ack_ms"] = round((time.monotonic() - t1) * 1000)
            row["total_ms"] = round((time.monotonic() - t0) * 1000)
        link.close()
        time.sleep(3)
        snap(url, os.path.join(outdir, name + "-before.jpg"))
        cycle(hub_id, port)
        snap(url, os.path.join(outdir, name + "-after.jpg"))
        link = open_link()
        row["begin_after_cut"] = link.command(protocol.gif_begin(data)).status
        link.close()
        if row["begin_after_cut"] == 1:
            cycle(hub_id, port)  # drop the upload that probe opened
        row["t"] = time.time()
        print(json.dumps(row), flush=True)
        log.write(json.dumps(row) + "\n")
        log.flush()


if __name__ == "__main__":
    main()
