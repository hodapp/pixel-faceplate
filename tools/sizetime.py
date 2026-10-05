#!/usr/bin/env python3
# Time the GIF-end ACK against GIF size, to tell flash work (grows with size) from fixed overhead.

"""Usage: python3 tools/sizetime.py [--split]

Uploads a handful of test GIFs and times each one. Every upload is a write to
the panel's flash, so don't run it in a loop.
"""

import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "py_modules"))

from pixelface import gif, protocol  # noqa: E402
from pixelface.transport import Link  # noqa: E402

W, H = protocol.WIDTH, protocol.HEIGHT


def noise_gif(frames, seed):
    rng = random.Random(seed)
    return gif.encode(W, H, gif.PALETTE_332, [bytes(rng.randrange(256) for _ in range(W * H)) for _ in range(frames)], 20)


def solid_gif(frames, seed):
    rng = random.Random(seed)
    # Many frames, tiny file: each frame is one flat palette index.
    return gif.encode(W, H, gif.PALETTE_332, [bytes([rng.randrange(256)]) * (W * H) for _ in range(frames)], 20)


def main():
    link = Link().open()
    seed = int(time.time())  # fresh content each run, so the panel never skips it as already stored
    print("frames   bytes  sectors  chunks_ms  end_ack_ms")
    cases = [(n, noise_gif(n, seed + n)) for n in (1, 2, 4, 8, 12)]
    if "--split" in sys.argv:
        # Separate bytes from frames: lots of flat frames vs one big noisy frame.
        cases = [(n, solid_gif(n, seed + 100 + n)) for n in (1, 12, 48)] + [(1, noise_gif(1, seed + 200))]
    for frames, data in cases:
        begin = link.command(protocol.gif_begin(data))
        if begin.status != 1:
            print("begin status", begin)
            continue
        t0 = time.monotonic()
        for chunk in protocol.gif_chunks(data):
            link.command(chunk)
        t1 = time.monotonic()
        end = link.command(protocol.gif_end(), timeout=10)
        t2 = time.monotonic()
        print("%6d %7d %8d %10.0f %11.0f  %r" % (frames, len(data), -(-len(data) // 4096),
                                                (t1 - t0) * 1000, (t2 - t1) * 1000, end))
        time.sleep(0.5)


if __name__ == "__main__":
    main()
