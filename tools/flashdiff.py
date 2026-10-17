#!/usr/bin/env python3
# Upload one known GIF over the normal path, and diff two U22 flash dumps sector by sector.
"""Usage:
  flashdiff.py upload OUTDIR NAME [static:BYTES:HUE]   upload one test GIF, keep a copy in OUTDIR
  flashdiff.py send FILE.gif [N] [badcrc]              upload a GIF file; N = stop after N chunks (no end); badcrc = announce a wrong CRC
  flashdiff.py cmd brightness|builtin|power ARG        send one control command
  flashdiff.py busy V1 V2 ...                          brightness changes, each followed by a timed ping
  flashdiff.py diff A.bin B.bin [GIF ...]              which 4 KB sectors changed, and where each GIF sits

Upload only uses the GIF path (04 begin, 02 02 chunks, 0B end), never 0x03.
Run it with the panel on USB and the SOIC clip's 3.3 V lead off, so the
panel has one power source.
"""
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "py_modules"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
SECTOR = 4096


def upload(outdir, name, spec="static:1000:red"):
    # Here, not at the top, so diff runs on a machine without pyserial.
    from flashtest import HUES, make
    kind, target, hue = spec.split(":")
    data = make(kind, int(target), HUES[hue], int(time.time()))
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, name + ".gif"), "wb") as f:
        f.write(data)
    send_gif(name, data)


def send_gif(name, data, stop_after=None, bad_crc=False):
    """Upload over the normal GIF path. stop_after=N sends only N chunks and no end frame.
    bad_crc announces the wrong CRC32 in the begin frame (the data itself is untouched)."""
    import zlib
    from pixelface import protocol
    link = _link()
    t0 = time.monotonic()
    begin_frame = protocol.gif_begin(data)
    if bad_crc:
        crc = (zlib.crc32(data) ^ 1) & 0xFFFFFFFF
        begin_frame = protocol.frame(protocol.TYPE_CONTROL, protocol.CMD_GIF_BEGIN,
                                     len(data).to_bytes(4, "big") + crc.to_bytes(4, "big"))
        print(f"announcing CRC {crc:#010x} instead of {zlib.crc32(data):#010x}")
    begin = link.command(begin_frame)
    print(f"{name}: {len(data)} bytes, begin -> {begin.status}")
    if begin.status == 1:
        chunks = list(protocol.gif_chunks(data))
        for i, chunk in enumerate(chunks[:stop_after]):
            reply = link.command(chunk)
            if i == 0 or reply.status != 1:
                print(f"chunk {i} -> {reply.status}")
        if stop_after is not None:
            print(f"stopped after {min(stop_after, len(chunks))} of {len(chunks)} chunks, no end frame")
        else:
            t1 = time.monotonic()
            end = link.command(protocol.gif_end(), timeout=10)
            print(f"end -> {end.status}, end ACK {round((time.monotonic() - t1) * 1000)} ms, "
                  f"total {round((time.monotonic() - t0) * 1000)} ms")
    link.close()


def send_cmd(hexframe_or_name, arg=None):
    """One control command: brightness N, builtin N, power 0|1."""
    from pixelface import protocol
    data = {"brightness": lambda: protocol.brightness(int(arg)), "builtin": lambda: protocol.builtin(int(arg)),
            "power": lambda: protocol.power(arg == "1")}[hexframe_or_name]()
    link = _link()
    reply = link.command(data)
    print(f"{hexframe_or_name} {arg}: sent {data.hex()} -> status {reply.status}")
    link.close()


LOG = os.path.expanduser("~/dumps/panel-log.jsonl")


def busy_probe(values):
    """Time a harmless screen-on ping right after each brightness value, against pings with no change.
    An erase keeps the MCU busy for ~40 ms, so a slower ping after a brightness change means it wrote."""
    from pixelface import protocol
    link = _link()
    ping = protocol.power(True)

    def timed():
        t = time.monotonic()
        status = link.command(ping).status
        return round((time.monotonic() - t) * 1000, 1), status

    base = [timed() for _ in range(5)]
    print("baseline ping ms:", base)
    for v in values:
        # "on" = the screen-on command, which writes nothing (t7): the control for back-to-back frames.
        # "N@D" = brightness N, then wait D ms before the ping.
        cmd, _, delay = v.partition("@")
        link.port.write(protocol.power(True) if cmd == "on" else protocol.brightness(int(cmd)))
        time.sleep(int(delay or 0) / 1000)
        print(f"{v} then ping ms:", timed(), " later ping:", timed())
        time.sleep(0.5)
    link.close()


def _link():
    from flashtest import Link

    class Logged(Link):
        # Every frame sent and its reply, timestamped, so each step can be checked later.
        def command(self, data, timeout=1.0):
            reply = super().command(data, timeout)
            os.makedirs(os.path.dirname(LOG), exist_ok=True)
            with open(LOG, "a") as f:
                f.write(json.dumps({"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                    "sent": data.hex() if len(data) <= 32 else data[:16].hex() + f"...({len(data)} B)",
                                    "reply_status": reply.status}) + "\n")
            return reply

    ports = sorted(glob.glob("/dev/cu.usbserial-*") + glob.glob("/dev/ttyUSB*"))
    if not ports:
        raise SystemExit("no panel on USB")
    return Logged(ports[0])


def diff(a_path, b_path, gifs):
    a, b = open(a_path, "rb").read(), open(b_path, "rb").read()
    changed = [i for i in range(len(a) // SECTOR) if a[i * SECTOR:(i + 1) * SECTOR] != b[i * SECTOR:(i + 1) * SECTOR]]
    print(f"{len(changed)} of {len(a) // SECTOR} sectors differ")
    runs = []
    for i in changed:
        if runs and runs[-1][1] == i - 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    for lo, hi in runs:
        sa, sb = a[lo * SECTOR:(hi + 1) * SECTOR], b[lo * SECTOR:(hi + 1) * SECTOR]
        ua, ub = len(sa.rstrip(b"\xff")), len(sb.rstrip(b"\xff"))
        # NOR programming can only clear bits (1 -> 0); any 0 -> 1 bit means the sector was erased.
        up = sum(bin(~x & y & 0xFF).count("1") for x, y in zip(sa, sb))
        down = sum(bin(x & ~y & 0xFF).count("1") for x, y in zip(sa, sb))
        print(f"  0x{lo * SECTOR:06x}-0x{(hi + 1) * SECTOR:06x} ({hi - lo + 1} sectors): "
              f"used before {ua} B, after {ub} B, "
              f"{sum(x != y for x, y in zip(sa, sb))} bytes changed, bits 0->1 {up} (erase), 1->0 {down}")
        for s in range(lo, hi + 1):
            one = b[s * SECTOR:(s + 1) * SECTOR]
            ups = sum(bin(~x & y & 0xFF).count("1") for x, y in zip(a[s * SECTOR:(s + 1) * SECTOR], one))
            print(f"    sector 0x{s * SECTOR:06x}: 0->1 bits {ups}")
    for path in gifs:
        g = open(path, "rb").read()
        print(f"{os.path.basename(path)}: in A at {[hex(i) for i in _find(a, g)]}, in B at {[hex(i) for i in _find(b, g)]}")


def _find(hay, needle):
    out, i = [], hay.find(needle)
    while i >= 0:
        out.append(i)
        i = hay.find(needle, i + 1)
    return out


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "upload":
        upload(*sys.argv[2:5])
    elif len(sys.argv) >= 3 and sys.argv[1] == "send":
        extra = sys.argv[3:]
        send_gif(os.path.basename(sys.argv[2]), open(sys.argv[2], "rb").read(),
                 int(extra[0]) if extra and extra[0].isdigit() else None, "badcrc" in extra)
    elif len(sys.argv) >= 3 and sys.argv[1] == "busy":
        busy_probe(sys.argv[2:])
    elif len(sys.argv) == 4 and sys.argv[1] == "cmd":
        send_cmd(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 4 and sys.argv[1] == "diff":
        diff(sys.argv[2], sys.argv[3], sys.argv[4:])
    else:
        raise SystemExit(__doc__)
