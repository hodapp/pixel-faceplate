#!/usr/bin/env python3
# Make dim, easy-to-recognize numbered test GIFs (64x54) at set sizes for the U22 flash tests.
"""Usage: testgifs.py OUTDIR    (needs Pillow; run with `uv run --with pillow`)

Writes digit1.gif (small, static), digit2.gif (~6 KB static) and digit3.gif
(~100 KB animated). Each shows its digit big enough to read across the room.
Noise in the background pads the file to the target size. Kept dim (no channel
over ~120) so a USB port won't brown out powering it.
"""
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 64, 54
FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def frame(digit, fg, bg, noise, rng, label=""):
    im = Image.new("RGB", (W, H), bg)
    px = im.load()
    for _ in range(noise):
        x, y = rng.randrange(W), rng.randrange(H)
        px[x, y] = tuple(min(120, c + rng.randrange(40)) for c in bg)
    d = ImageDraw.Draw(im)
    d.text((W // 2, H // 2), digit, fill=fg, font=ImageFont.truetype(FONT, 50), anchor="mm")
    if label:
        d.text((2, 0), label, fill=fg, font=ImageFont.truetype(FONT, 9))
    return im


def save(path, frames, duration=100):
    # No loop block, and no delay on a single frame: the panel then decodes the GIF once and
    # stops touching U22. A looping GIF makes it re-read U22 every frame, which collides with
    # the clip and garbles in-circuit reads (seen 2026-10-17: 5 reads, 5 different hashes).
    if len(frames) == 1:
        frames[0].save(path, optimize=False)
    else:
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=duration, optimize=False)
    return os.path.getsize(path)


def static_to(path, digit, fg, bg, target, seed):
    lo, hi = 0, W * H * 3
    while lo < hi:  # fewest noise pixels that reach the target size
        mid = (lo + hi) // 2
        size = save(path, [frame(digit, fg, bg, mid, random.Random(seed))])
        lo, hi = (mid + 1, hi) if size < target else (lo, mid)
    return save(path, [frame(digit, fg, bg, lo, random.Random(seed))])


def main(out):
    os.makedirs(out, exist_ok=True)
    print("digit1", save(os.path.join(out, "digit1.gif"), [frame("1", (110, 110, 110), (0, 0, 60), 0, random.Random(1))]))
    print("digit2", static_to(os.path.join(out, "digit2.gif"), "2", (120, 100, 0), (0, 40, 0), 6000, 2))
    rng = random.Random(3)
    frames = []
    colors = [(120, 0, 0), (0, 0, 120), (0, 90, 90), (90, 0, 90)]
    while True:  # add noisy numbered frames until ~100 KB
        i = len(frames)
        frames.append(frame("3", (120, 120, 120), colors[i % 4], 2500, rng, label=str(i + 1)))
        size = save(os.path.join(out, "digit3.gif"), frames)
        if size >= 100_000:
            break
    print("digit3", size, len(frames), "frames")


if __name__ == "__main__":
    main(sys.argv[1])
