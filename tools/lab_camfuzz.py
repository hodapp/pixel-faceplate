#!/usr/bin/env python3
# Send frames to the faceplate over ssh and flag any that visibly change the screen, using a camera.
"""Usage (on the machine that can see the camera):

    LAB_CAMERA=rtsp://... lab_camfuzz.py SSH_HOST PORT PLAN [SHOTDIR]

PLAN has one frame per line: "TYPE CMD [HEX]" (# comments allowed). A line
starting with "baseline " is sent first to put a still picture up (repeat it
to restore after a change). The camera URL comes from LAB_CAMERA so it never
lands in git. Each frame: send, wait, compare a 64x36 grey camera frame with
the baseline; a mean difference over THRESHOLD is reported with a JPEG.
"""

import json
import os
import subprocess
import sys
import threading
import time

W, H = 128, 96
GX, GY = 16, 12  # scoring grid: the score is the busiest cell, so a small change can't average away
# Panel region in the camera frame as fractions "left,top,width,height"; whole frame if unset.
CROP = os.environ.get("LAB_CROP", "0,0,1,1")
THRESHOLD = float(os.environ.get("LAB_THRESHOLD", "6"))
SETTLE = float(os.environ.get("LAB_SETTLE", "1.2"))
FFMPEG = os.environ.get("FFMPEG", "/opt/homebrew/bin/ffmpeg")


class Camera:
    """Keeps one ffmpeg reading the stream; latest() is the newest grey frame."""

    def __init__(self, url):
        x, y, w, h = CROP.split(",")
        crop = "crop=iw*%s:ih*%s:iw*%s:ih*%s" % (w, h, x, y)
        self.proc = subprocess.Popen(
            [FFMPEG, "-loglevel", "error", "-rtsp_transport", "tcp", "-i", url,
             "-vf", "fps=4,%s,scale=%d:%d" % (crop, W, H), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            stdout=subprocess.PIPE)
        self.frame, self.stamp = None, 0.0
        self.recent = []  # (stamp, frame), last few seconds
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while True:
            data = self.proc.stdout.read(W * H)
            if len(data) < W * H:
                return
            now = time.monotonic()
            self.frame, self.stamp = data, now
            self.recent = [(t, f) for t, f in self.recent if now - t < 5] + [(now, data)]

    def latest(self, after):
        while self.stamp <= after:
            time.sleep(0.05)
        return self.frame

    def averaged(self, seconds):
        """Average of the frames from the last `seconds` (a blinking colon averages out)."""
        cutoff = time.monotonic() - seconds
        frames = [f for t, f in self.recent if t >= cutoff] or [self.frame]
        return [sum(col) / len(frames) for col in zip(*frames)]


def diff(a, b):
    """Mean absolute difference of the most-changed grid cell."""
    cw, ch = W // GX, H // GY
    worst = 0.0
    for gy in range(GY):
        for gx in range(GX):
            total = 0
            for yy in range(gy * ch, (gy + 1) * ch):
                row = yy * W + gx * cw
                total += sum(abs(a[i] - b[i]) for i in range(row, row + cw))
            worst = max(worst, total / (cw * ch))
    return worst


def snapshot(url, path):
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-rtsp_transport", "tcp", "-i", url,
                    "-frames:v", "1", path], check=False)


def main(argv):
    host, port, plan = argv[1], argv[2], argv[3]
    shots = argv[4] if len(argv) > 4 else "."
    url = os.environ["LAB_CAMERA"]
    remote = subprocess.Popen(
        ["ssh", host, "cd ~/faceplate-lab/tools && PAST_GUARD=%s ../.venv/bin/python lab_serve.py %s"
         % (os.environ.get("PAST_GUARD", ""), port)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)

    def send(line):
        remote.stdin.write(line + "\n")
        remote.stdin.flush()
        return json.loads(remote.stdout.readline())

    camera = Camera(url)
    with open(plan) as f:
        lines = [l.split("#")[0].strip() for l in f]
    lines = [l for l in lines if l]
    baseline_cmds = [l[len("baseline "):] for l in lines if l.startswith("baseline ")]
    frames = [l for l in lines if not l.startswith("baseline ")]

    def set_baseline():
        for b in baseline_cmds:
            send(b)
        time.sleep(SETTLE * 2)
        return camera.latest(time.monotonic())

    set_baseline()
    for line in frames:
        # Before/after comparison, each a 1 s average, so drift and the colon blink cancel.
        before = camera.averaged(1.0)
        result = send(line)
        if "refused" in result:
            print("REFUSED", line, flush=True)
            continue
        time.sleep(SETTLE + 1.0)
        d = diff(before, camera.averaged(1.0))
        tag = "CHANGE" if d > THRESHOLD else "same"
        print("%-6s %5.1f %-24s %s" % (tag, d, line, result), flush=True)
        if not result.get("alive", True):
            print("DEAD after", line, flush=True)
            break
        if d > THRESHOLD:
            snapshot(url, os.path.join(shots, "change_" + line.replace(" ", "_") + ".jpg"))
            base = set_baseline()
    remote.stdin.close()
    camera.proc.kill()


if __name__ == "__main__":
    main(sys.argv)
