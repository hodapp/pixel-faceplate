# Draw 64x54 RGB frames: clock, light bar glow, images and Steam artwork via GStreamer.

import glob
import os
import re
import shutil
import subprocess
import ssl
import threading
import time
import urllib.error
import urllib.request

from .protocol import HEIGHT, WIDTH

FRAME_BYTES = WIDTH * HEIGHT * 3


def clean_environment():
    """Environment for system binaries: drop the library paths Decky's bundled Python sets."""
    env = dict(os.environ)
    for name in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"):
        env.pop(name, None)
    env["LD_LIBRARY_PATH"] = ""
    return env

# 3x5 digits for the date line and 5x7 digits drawn at 2x for the time.
SMALL = {
    "0": ["111", "101", "101", "101", "111"], "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"], "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"], "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"], "7": ["111", "001", "010", "010", "010"],
    "8": ["111", "101", "111", "101", "111"], "9": ["111", "101", "111", "001", "111"],
    "/": ["001", "001", "010", "100", "100"], " ": ["000"] * 5, ":": ["0", "1", "0", "1", "0"],
    "A": ["010", "101", "111", "101", "101"], "P": ["110", "101", "110", "100", "100"],
    "M": ["10001", "11011", "10101", "10001", "10001"],
}
BIG = {
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11111", "00010", "00100", "00010", "00001", "10001", "01110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    ":": ["0", "1", "1", "0", "1", "1", "0"],
}


class Canvas:
    def __init__(self, fill=(0, 0, 0)):
        self.px = bytearray(bytes(fill) * (WIDTH * HEIGHT))

    def set(self, x, y, color):
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            i = 3 * (y * WIDTH + x)
            self.px[i:i + 3] = bytes(color)

    def rect(self, x, y, w, h, color):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.set(xx, yy, color)

    def text(self, x, y, string, color, font=SMALL, scale=1, gap=1):
        for ch in string:
            glyph = font.get(ch, font.get(" ", ["0"]))
            for gy, row in enumerate(glyph):
                for gx, bit in enumerate(row):
                    if bit == "1":
                        self.rect(x + gx * scale, y + gy * scale, scale, scale, color)
            x += (len(glyph[0]) + gap) * scale
        return x

    @staticmethod
    def text_width(string, font=SMALL, scale=1, gap=1):
        return sum((len(font.get(ch, font.get(" ", ["0"]))[0]) + gap) * scale for ch in string) - gap * scale

    def bytes(self):
        return bytes(self.px)


def clock(now=None, color=(255, 140, 20), use_24h=False):
    now = time.localtime(now)
    canvas = Canvas()
    hour = now.tm_hour if use_24h else (now.tm_hour % 12 or 12)
    hhmm = "%d:%02d" % (hour, now.tm_min) if not use_24h else "%02d:%02d" % (hour, now.tm_min)
    width = Canvas.text_width(hhmm, BIG, 2)
    canvas.text((WIDTH - width) // 2, 12, hhmm, color, BIG, 2)
    line = "%d/%d" % (now.tm_mon, now.tm_mday)
    if not use_24h:
        line += " " + ("AM" if now.tm_hour < 12 else "PM")
    dim = tuple(c // 3 for c in color)
    canvas.text((WIDTH - Canvas.text_width(line)) // 2, 34, line, dim)
    return canvas.bytes()


def read_lightbar(root="/sys/class/leds", reverse=False):
    """Colors of the Steam Machine light bar in sysfs index order (reversed if asked), scaled by brightness."""
    leds = []
    for path in glob.glob(os.path.join(root, "valve-leds[[]*[]]")):
        try:
            index = int(path.rsplit("[", 1)[1].rstrip("]"))
            with open(os.path.join(path, "multi_intensity")) as handle:
                rgb = [int(v) for v in handle.read().split()[:3]]
            with open(os.path.join(path, "brightness")) as handle:
                level = int(handle.read().strip() or 0)
            with open(os.path.join(path, "max_brightness")) as handle:
                top = int(handle.read().strip() or 255) or 255
        except (OSError, ValueError, IndexError):
            continue
        leds.append((index, tuple(min(255, c * level // top) for c in rgb)))
    colors = [c for _, c in sorted(leds)]
    return colors[::-1] if reverse else colors


def aura(colors):
    """A soft glow: light bar colors spread across the width, fading toward the top."""
    if not colors:
        return bytes(FRAME_BYTES)
    out = bytearray(FRAME_BYTES)
    n = len(colors)
    row = []
    for x in range(WIDTH):
        pos = x * (n - 1) / (WIDTH - 1) if n > 1 else 0
        a = int(pos)
        b = min(n - 1, a + 1)
        t = pos - a
        row.append(tuple(int(colors[a][k] * (1 - t) + colors[b][k] * t) for k in range(3)))
    for y in range(HEIGHT):
        # Brightest along the bottom edge, where the light bar sits below the faceplate.
        fade = ((y + 1) / HEIGHT) ** 1.6
        for x, (r, g, b) in enumerate(row):
            i = 3 * (y * WIDTH + x)
            out[i] = int(r * fade)
            out[i + 1] = int(g * fade)
            out[i + 2] = int(b * fade)
    return bytes(out)


def image_size(path):
    """(width, height) from a PNG or JPEG header, or None."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(64 * 1024)
    except OSError:
        return None
    if head[:8] == b"\x89PNG\r\n\x1a\n" and len(head) >= 24:
        return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    if head[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(head):
            if head[i] != 0xFF:
                i += 1
                continue
            marker = head[i + 1]
            length = int.from_bytes(head[i + 2:i + 4], "big")
            # SOF0-SOF15 carry the size, except DHT (C4), JPG (C8) and DAC (CC).
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                return int.from_bytes(head[i + 7:i + 9], "big"), int.from_bytes(head[i + 5:i + 7], "big")
            i += 2 + length
    return None


def _gst_decode(path, width, height, alpha=False, timeout=5.0):
    """Decode and Lanczos-scale an image with GStreamer; raw RGB or RGBA bytes, or None."""
    gst = shutil.which("gst-launch-1.0")
    if not gst or not os.path.isfile(path):
        return None
    fmt = "RGBA" if alpha else "RGB"
    # The image goes in on stdin, never as text in the pipeline: gst-launch
    # parses its arguments, so a crafted file name could add elements.
    argv = [
        gst, "-q", "fdsrc", "fd=0", "!", "decodebin", "!", "videoconvert",
        # method=3 is Lanczos: much crisper than bilinear at this size (seen).
        "!", "videoscale", "method=3", "add-borders=false",
        "!", "video/x-raw,format=%s,width=%d,height=%d,pixel-aspect-ratio=1/1" % (fmt, width, height),
        "!", "imagefreeze", "num-buffers=1", "!", "fdsink", "fd=1",
    ]
    try:
        with open(path, "rb") as image:
            result = subprocess.run(argv, stdin=image, capture_output=True, timeout=timeout,
                                    check=False, env=clean_environment())
    except (OSError, subprocess.SubprocessError):
        return None
    # GStreamer pads every raw video row to a multiple of 4 bytes. RGB rows of
    # odd widths would shear diagonally if read as packed (seen on hero art).
    row = width * (4 if alpha else 3)
    stride = (row + 3) & ~3
    if result.returncode or len(result.stdout) < stride * height:
        return None
    data = result.stdout
    if stride == row:
        return data[:row * height]
    return b"".join(data[y * stride:y * stride + row] for y in range(height))


def _crop(rgb, width, height, x0, y0):
    out = bytearray()
    for y in range(y0, y0 + HEIGHT):
        start = 3 * (y * width + x0)
        out += rgb[start:start + 3 * WIDTH]
    return bytes(out)


def decode_image(path, fill=True, ybias=0.5):
    """Any image GStreamer can open, as one 64x54 RGB frame (or None).

    fill crops to the panel's shape (ybias picks how far down a tall image
    the crop sits: 0 top, 0.5 middle); otherwise the image is letterboxed.
    """
    size = image_size(path)
    if not size or not all(size):
        size = (WIDTH, HEIGHT)  # unknown format: just squeeze it
    w, h = size
    wide = w * HEIGHT > h * WIDTH
    if fill:
        tw, th = (max(WIDTH, round(w * HEIGHT / h)), HEIGHT) if wide else (WIDTH, max(HEIGHT, round(h * WIDTH / w)))
        # A freak shape (say 1x100000 from a picture off the web) would scale
        # to a strip hundreds of MB big; past this it's squeezed instead.
        tw, th = min(tw, MAX_SCALED), min(th, MAX_SCALED)
    else:
        tw, th = (WIDTH, max(1, round(h * WIDTH / w))) if wide else (max(1, round(w * HEIGHT / h)), HEIGHT)
    rgb = _gst_decode(path, tw, th)
    if rgb is None:
        return None
    if fill:
        return _crop(rgb, tw, th, (tw - WIDTH) // 2, int((th - HEIGHT) * ybias))
    canvas = bytearray(FRAME_BYTES)
    x0, y0 = (WIDTH - tw) // 2, (HEIGHT - th) // 2
    for y in range(th):
        start = 3 * ((y0 + y) * WIDTH + x0)
        canvas[start:start + 3 * tw] = rgb[3 * y * tw:3 * (y + 1) * tw]
    return bytes(canvas)


def sharpen(rgb, amount=0.8):
    """Light unsharp mask (3x3 box blur); downscaled art reads better with it."""
    out = bytearray(rgb)
    for y in range(1, HEIGHT - 1):
        for x in range(1, WIDTH - 1):
            i = 3 * (y * WIDTH + x)
            for k in range(3):
                total = 0
                for dy in (-WIDTH * 3, 0, WIDTH * 3):
                    j = i + dy + k
                    total += rgb[j - 3] + rgb[j] + rgb[j + 3]
                v = rgb[i + k] + amount * (rgb[i + k] - total / 9)
                out[i + k] = 0 if v < 0 else 255 if v > 255 else int(v)
    return bytes(out)


def dim(rgb, factor):
    return bytes(int(v * factor) for v in rgb)


def lift(rgb, gamma):
    """Brighten midtones (gamma < 1) while black stays black and white stays white."""
    table = bytes(int(round(255 * (v / 255.0) ** gamma)) for v in range(256))
    return bytes(rgb).translate(table)


def rotate(rgb):
    """Turn a frame 180 degrees, for a faceplate mounted with its cable on the right."""
    out = bytearray(len(rgb))
    last = len(rgb) - 3
    for i in range(0, len(rgb), 3):
        out[last - i:last - i + 3] = rgb[i:i + 3]
    return bytes(out)


def load_logo(path, max_width=WIDTH - 6, max_height=HEIGHT // 2):
    """A transparent logo PNG trimmed and box-averaged to fit the box.

    Returns (width, height, pixels) with pixels as (x, y, coverage, color),
    or None if it can't be read or is empty.
    """
    size = image_size(path)
    if not size or not all(size):
        return None
    w, h = size
    # Decode at 4x the target width so trimming and box-averaging stay sharp.
    dw = 4 * max_width
    dh = max(1, round(h * dw / w))
    if dh > 4 * HEIGHT:
        dh = 4 * HEIGHT
        dw = max(1, round(w * dh / h))
    rgba = _gst_decode(path, dw, dh, alpha=True)
    if rgba is None:
        return None
    return fit_logo(rgba, dw, dh, max_width, max_height)


def fit_logo(rgba, dw, dh, max_width, max_height):
    # Trim fully transparent margins (logos ship with lots of padding).
    xs = [x for x in range(dw) if any(rgba[4 * (y * dw + x) + 3] > 8 for y in range(dh))]
    ys = [y for y in range(dh) if any(rgba[4 * (y * dw + x) + 3] > 8 for x in range(dw))]
    if not xs or not ys:
        return None
    bx0, bx1, by0, by1 = xs[0], xs[-1] + 1, ys[0], ys[-1] + 1
    bw, bh = bx1 - bx0, by1 - by0
    scale = min(max_width / bw, max_height / bh)
    lw, lh = max(1, int(bw * scale)), max(1, int(bh * scale))
    pixels = []
    for ty in range(lh):
        sy0, sy1 = by0 + int(ty / scale), by0 + max(int(ty / scale) + 1, int((ty + 1) / scale))
        for tx in range(lw):
            sx0, sx1 = bx0 + int(tx / scale), bx0 + max(int(tx / scale) + 1, int((tx + 1) / scale))
            r = g = b = a = 0
            n = 0
            for sy in range(sy0, min(sy1, dh)):
                for sx in range(sx0, min(sx1, dw)):
                    j = 4 * (sy * dw + sx)
                    alpha = rgba[j + 3]
                    r += rgba[j] * alpha
                    g += rgba[j + 1] * alpha
                    b += rgba[j + 2] * alpha
                    a += alpha
                    n += 1
            if a:
                pixels.append((tx, ty, a / (255 * n), (r / a, g / a, b / a)))
    return lw, lh, pixels


def place_logo(rgb, logo, position="bottom", band=True, margin=3):
    """Blend a fitted logo onto a frame at the top, bottom or center.

    With band on, the art fades to half brightness behind the logo so the
    title stands out. It covers the logo plus a short fade, running out to
    the edge the logo sits against (both fades for a centered logo).
    """
    lw, lh, pixels = logo
    out = bytearray(rgb)
    ox = (WIDTH - lw) // 2
    if position == "top":
        oy = margin
    elif position == "center":
        oy = (HEIGHT - lh) // 2
    else:
        oy = HEIGHT - lh - margin
    if band:
        fade = 6
        for y in range(HEIGHT):
            below, above = y - (oy - fade), (oy + lh + fade) - y  # rows inside each fade edge
            if position == "top":
                into = above
            elif position == "center":
                into = min(below, above)
            else:
                into = below
            if into <= 0:
                continue
            keep = 1.0 - 0.5 * min(1.0, into / fade)
            row = 3 * y * WIDTH
            for i in range(row, row + 3 * WIDTH):
                out[i] = int(out[i] * keep)
    # Bright logo on dim art reads brighter than bright art, and the logo is
    # a small area, so it costs little power. Lift the logo until its brightest
    # channel is at full, at most doubling it.
    peak = max((max(c) for _, _, cov, c in pixels if cov > 0.5), default=255)
    gain = min(2.0, 255.0 / peak) if peak else 1.0
    for tx, ty, coverage, color in pixels:
        i = 3 * ((oy + ty) * WIDTH + ox + tx)
        for k in range(3):
            lifted = min(255.0, color[k] * gain)
            out[i + k] = int(out[i + k] * (1 - coverage) + lifted * coverage)
    return bytes(out)


# Artwork lookup follows GabeCubeAura's (BSD-3, (c) 2026 Alyenax) so both
# plugins pick the same picture: the logged-in account's custom grid art
# (SteamGridDB writes there) first, then Steam's library cache in its old
# flat layout and the newer <appid>/<hash>/<name> one (seen on Graveyard
# Keeper 2). The code here is my own.
STEAM_ROOT = os.path.expanduser("~deck/.local/share/Steam")
IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "webp")
ART_STEMS = {
    "hero": ("library_hero", "library_hero_2x", "library_hero@2x"),
    "header": ("library_header", "library_header_2x", "header"),
    "capsule": ("library_capsule", "library_600x900", "library_600x900_2x"),
    "logo": ("logo", "logo_2x"),
}
# Steam's grid folder names custom art <appid><suffix>.<ext>.
GRID_SUFFIX = {"hero": "_hero", "header": "", "capsule": "p", "logo": "_logo"}
MAX_ART_BYTES = 12 * 1024 * 1024
# Largest side an image is scaled to before the crop (see decode_image).
MAX_SCALED = 2048
# Midtone lift for game art. Even at full brightness the panel is much dimmer
# than the Steam Machine's light bar, so midtones get pushed up. The power cap
# in service.py still trims any frame that would draw too much.
ART_GAMMA = 0.7


def _usable(path):
    try:
        return os.path.isfile(path) and 0 < os.path.getsize(path) <= MAX_ART_BYTES
    except OSError:
        return False


def _active_grid_dir(root):
    """config/grid of the logged-in account only, never another account's overrides.

    That's the login marked MostRecent in loginusers.vdf; some installs don't
    write that flag, so then the newest Timestamp, or the only account there is.
    """
    try:
        with open(os.path.join(root, "config", "loginusers.vdf"), encoding="utf-8") as handle:
            content = handle.read()
    except OSError:
        content = ""
    accounts = []
    for match in re.finditer(r'"(\d{16,20})"\s*\{([^{}]*)\}', content):
        recent = re.search(r'"MostRecent"\s*"1"', match.group(2), re.IGNORECASE)
        stamp = re.search(r'"Timestamp"\s*"(\d+)"', match.group(2), re.IGNORECASE)
        accounts.append((1 if recent else 0, int(stamp.group(1)) if stamp else 0, int(match.group(1)) & 0xFFFFFFFF))
    if accounts:
        account = max(accounts)[2]
    else:
        found = glob.glob(os.path.join(root, "userdata", "*", "config", "grid"))
        if len(found) != 1:
            return None
        return found[0]
    grid = os.path.join(root, "userdata", str(account), "config", "grid")
    return grid if os.path.isdir(grid) else None


def grid_dirs(root, appid):
    """Grid folders to look in: the logged-in account's, then (shortcuts only) every other account's.

    A Steam game's custom art belongs to whoever is logged in. A non-Steam
    game's ID is already per account, so if the active account can't be
    told from loginusers.vdf, any account's grid art for it is the right one.
    """
    active = _active_grid_dir(root)
    dirs = [active] if active else []
    if appid & SHORTCUT_BIT:
        others = glob.glob(os.path.join(root, "userdata", "*", "config", "grid"))
        try:
            others.sort(key=os.path.getmtime, reverse=True)
        except OSError:
            pass
        dirs += [d for d in others if d != active]
    return dirs


def find_art(appid, kind, root=STEAM_ROOT):
    """Path of a game's art of one kind (hero, header, capsule, logo), or None.

    Non-Steam games only have art in the grid folder (where SteamGridDB puts
    it); Steam's library cache holds nothing for them.
    """
    appid = normalize_appid(appid)
    if not appid:
        return None
    for grid in grid_dirs(root, appid):
        for ext in IMAGE_EXTENSIONS:
            path = os.path.join(grid, "%d%s.%s" % (appid & 0xFFFFFFFF, GRID_SUFFIX[kind], ext))
            if _usable(path):
                return path
    cache = os.path.join(root, "appcache", "librarycache")
    for ext in IMAGE_EXTENSIONS:
        for stem in ART_STEMS[kind]:
            name = "%s.%s" % (stem, ext)
            for path in ([os.path.join(cache, str(appid), name)]
                         + sorted(glob.glob(os.path.join(cache, str(appid), "*", name)))
                         + sorted(glob.glob(os.path.join(cache, str(appid), "**", name), recursive=True))
                         + [os.path.join(cache, "%d_%s" % (appid, name))]):
                if _usable(path):
                    return path
    return fetch_art_later(appid, kind)


# Steam games whose art isn't in the local library cache (it only holds what
# the library has drawn lately, and some games, like ones with a launcher in
# front, can be missing pieces) get it from Steam's public CDN once, kept in
# the plugin's own folder. Non-Steam games have no CDN art: SteamGridDB only.
ART_DOWNLOAD_DIR = None  # set by main.py; None turns downloading off
CDN_HOSTS = (
    "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/%d/%s",
    "https://cdn.cloudflare.steamstatic.com/steam/apps/%d/%s",
)
CDN_NAMES = {
    "hero": ("library_hero.jpg",),
    "logo": ("logo.png",),
    "capsule": ("library_600x900.jpg",),
    "header": ("header.jpg",),
}
# A miss is remembered this long before asking the CDN again.
CDN_RETRY = 24 * 3600
CDN_TIMEOUT = 4.0
SHORTCUT_BIT = 0x80000000


def _looks_like_image(data):
    return data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"


def downloaded_art(appid, kind, directory=None, fetch=None):
    """Path of art fetched from Steam's CDN (fetching it now if needed), or None.

    A miss is only remembered when the CDN said so. With no network nothing
    is written, so the art turns up once the network is back.
    """
    directory = directory or ART_DOWNLOAD_DIR
    if not directory or not appid or appid & SHORTCUT_BIT or kind not in CDN_NAMES:
        return None
    base = os.path.join(directory, "%d_%s" % (appid, kind))
    for ext in ("jpg", "png"):
        if _usable("%s.%s" % (base, ext)):
            return "%s.%s" % (base, ext)
    missing = base + ".missing"
    try:
        if time.time() - os.path.getmtime(missing) < CDN_RETRY:
            return None
    except OSError:
        pass
    fetch = fetch or _fetch
    answered = True
    for name in CDN_NAMES[kind]:
        for host in CDN_HOSTS:
            data = fetch(host % (appid, name))
            if data is None:
                answered = False  # no answer at all, not a "not found"
            if data and len(data) <= MAX_ART_BYTES and _looks_like_image(data):
                path = "%s.%s" % (base, "png" if data[:4] == b"\x89PNG" else "jpg")
                try:
                    os.makedirs(directory, exist_ok=True)
                    with open(path + ".tmp", "wb") as handle:
                        handle.write(data)
                    os.replace(path + ".tmp", path)
                except OSError:
                    return None
                return path
    if not answered:
        return None
    try:
        os.makedirs(directory, exist_ok=True)
        with open(missing, "w"):
            pass
    except OSError:
        pass
    return None


# The worker holds the panel lock while it draws, and sleep only waits 3 s
# for it, so CDN art is fetched on a thread of its own. find_art returns
# what's already here; when a download lands, ART_FETCHED tells the service
# to draw again.
ART_FETCHED = None  # set by the service
_art_pending = set()
_art_pending_lock = threading.Lock()


def fetch_art_later(appid, kind):
    """Downloaded art if it's here already; otherwise start fetching it and return None."""
    directory = ART_DOWNLOAD_DIR
    if not directory or not appid or appid & SHORTCUT_BIT or kind not in CDN_NAMES:
        return None
    base = os.path.join(directory, "%d_%s" % (appid, kind))
    for ext in ("jpg", "png"):
        if _usable("%s.%s" % (base, ext)):
            return "%s.%s" % (base, ext)
    try:
        if time.time() - os.path.getmtime(base + ".missing") < CDN_RETRY:
            return None
    except OSError:
        pass
    key = (appid, kind)
    with _art_pending_lock:
        if key in _art_pending:
            return None
        _art_pending.add(key)

    def work():
        try:
            path = downloaded_art(appid, kind, directory)
        finally:
            with _art_pending_lock:
                _art_pending.discard(key)
        if path and ART_FETCHED:
            ART_FETCHED()

    threading.Thread(target=work, name="pixel-faceplate-art", daemon=True).start()
    return None


# Decky's bundled Python may not find the system's certificates on its own.
SYSTEM_CA_FILES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/ca-certificates/extracted/tls-ca-bundle.pem")


def _ssl_context():
    for path in SYSTEM_CA_FILES:
        if os.path.isfile(path):
            try:
                return ssl.create_default_context(cafile=path)
            except (OSError, ssl.SSLError):
                continue
    return ssl.create_default_context()


def _fetch(url):
    """The body of an HTTPS GET, b"" if the server said it isn't there, None if no answer."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "pixel-faceplate"})
        with urllib.request.urlopen(request, timeout=CDN_TIMEOUT, context=_ssl_context()) as response:
            if response.status != 200:
                return None
            return response.read(MAX_ART_BYTES + 1)
    except urllib.error.HTTPError as error:
        return b"" if error.code in (403, 404, 410) else None
    except (OSError, ValueError):
        return None


def normalize_appid(value):
    """A Steam app ID as the 32-bit number Steam's grid and cache files use.

    Non-Steam games (shortcuts) have a 32-bit app ID with the top bit set,
    and Steam also refers to them by a 64-bit game ID, (appid << 32) |
    0x02000000. Both come out as the 32-bit app ID; anything unusable is 0.
    """
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 0
    if value <= 0:
        return 0
    if value > 0xFFFFFFFF:
        return (value >> 32) & 0xFFFFFFFF
    return value


def _launch_env_appid(proc_root, pid):
    """App ID from a launch's environment, for launches whose AppId= is 0 or missing."""
    try:
        with open(os.path.join(proc_root, pid, "environ"), "rb") as handle:
            env = handle.read(65536).split(b"\0")
    except OSError:
        return 0
    found = {}
    for item in env:
        key, _, value = item.partition(b"=")
        if key in (b"SteamGameId", b"SteamOverlayGameId", b"SteamAppId"):
            found[key] = normalize_appid(value)
    # SteamGameId carries the shortcut's 64-bit game ID; SteamAppId is 0 for shortcuts.
    return found.get(b"SteamGameId") or found.get(b"SteamOverlayGameId") or found.get(b"SteamAppId") or 0


def running_appid(proc_root="/proc"):
    """App ID of the game Steam is running, from its `reaper SteamLaunch AppId=N` process (0 if none).

    Non-Steam games launch through the same reaper; when their AppId= is 0
    or missing, the launch's SteamGameId environment variable names them.
    """
    best = (0, 0)
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return 0
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc_root, entry, "cmdline"), "rb") as handle:
                args = handle.read(4096).split(b"\0")
        except OSError:
            continue
        if b"SteamLaunch" not in args:
            continue
        appid = 0
        for arg in args:
            if arg.startswith(b"AppId="):
                appid = normalize_appid(arg[6:])
                break
        if not appid:
            appid = _launch_env_appid(proc_root, entry)
        # Newest launch wins if two are up (e.g. a game started from another).
        if appid and int(entry) > best[0]:
            best = (int(entry), appid)
    return best[1]


def artwork(appid, root=STEAM_ROOT, style="logo_dim", position="bottom"):
    """The best 64x54 picture for a game, or None if nothing usable is cached.

    Side by side on five games, wide hero art with the transparent logo over
    the bottom beat the portrait cover: centered subject, readable title. The
    portrait cover cropped near the top is the fallback, then the header.

    style: logo_dim (art, logo, dark band behind it), logo (no band), art
    (no logo) or logo_only (the logo big on black; art if there's no logo).
    """
    if not appid:
        return None
    if style == "logo_only":
        path = find_art(appid, "logo", root)
        logo = load_logo(path, max_height=HEIGHT - 6) if path else None
        if logo:
            return place_logo(bytes(FRAME_BYTES), logo, position, band=False)
        style = "logo_dim"
    hero = find_art(appid, "hero", root)
    if hero:
        frame = decode_image(hero)
        if frame:
            frame = lift(sharpen(frame), ART_GAMMA)
            if style == "art":
                return frame
            path = find_art(appid, "logo", root)
            logo = load_logo(path) if path else None
            return place_logo(frame, logo, position, band=style == "logo_dim") if logo else frame
    for kind, bias in (("capsule", 0.2), ("header", 0.5)):
        path = find_art(appid, kind, root)
        if path:
            frame = decode_image(path, ybias=bias)
            if frame:
                return sharpen(frame)
    return None


# Steam's own icon, drawn from the copy SteamOS installs rather than shipped
# with the plugin (it's Valve's logo).
STEAM_ICONS = (
    "/usr/share/icons/hicolor/256x256/apps/steam.png",
    "/usr/share/icons/hicolor/48x48/apps/steam.png",
)


def steam_logo(size=46, paths=STEAM_ICONS):
    """The Steam logo centered on black, or None if SteamOS's icon isn't there."""
    for path in paths:
        if not os.path.isfile(path):
            continue
        dims = image_size(path) or (size, size)
        w = max(1, round(size * dims[0] / max(dims)))
        h = max(1, round(size * dims[1] / max(dims)))
        rgba = _gst_decode(path, w, h, alpha=True)
        if rgba is None:
            continue
        out = bytearray(FRAME_BYTES)
        ox, oy = (WIDTH - w) // 2, (HEIGHT - h) // 2
        for y in range(h):
            for x in range(w):
                j = 4 * (y * w + x)
                a = rgba[j + 3]
                if a:
                    i = 3 * ((oy + y) * WIDTH + ox + x)
                    for k in range(3):
                        out[i + k] = rgba[j + k] * a // 255
        return bytes(out)
    return None
