# Random pictures for the panel between games: cats, space, Earth, paintings, a night sky.
#
# Photos come from free public APIs that need no key (TheCatAPI and CATAAS,
# NASA's image library, NASA EPIC, the Art Institute of Chicago). Each one
# keeps a small stash in the plugin's folder, so with no network a picture
# already seen comes back instead. The night sky is drawn here and never
# touches the network. Every new picture is one flash write, so they change
# every few minutes, not faster.
#
# The fetching happens on its own thread (PictureFeed). The service holds
# the panel lock while it works, and sleep only waits 3 s for that lock, so a
# slow download there would leave the screen on all night.

import datetime
import json
import math
import os
import random
import re
import threading
import time
import urllib.parse

from . import render
from .protocol import HEIGHT, WIDTH

PICTURES_DIR = None  # set by main.py; None turns fetching off
# How many of each source to keep for offline use; the oldest go first.
STASH_SIZE = 40

THECATAPI = "https://api.thecatapi.com/v1/images/search?mime_types=jpg,png&size=med"
CATAAS = "https://cataas.com/cat?width=640"
NASA_SEARCH = "https://images-api.nasa.gov/search?media_type=image&page_size=50&page=%d&q=%s"
# Searches that come back with pictures that read on 64x54: big shapes, lots of black.
SPACE_QUERIES = ("nebula", "galaxy", "aurora", "jupiter", "saturn", "earth from space",
                 "milky way", "star cluster", "supernova", "moon", "mars surface", "comet")
EPIC_LIST = "https://epic.gsfc.nasa.gov/api/natural"
EPIC_IMAGE = "https://epic.gsfc.nasa.gov/archive/natural/%s/%s/%s/thumbs/%s.jpg"
# Public domain paintings that have an image. The API refuses to page past
# the first 1000 results without a key, so 100 pages of 10.
ARTIC_QUERY = json.dumps({"query": {"bool": {"filter": [
    {"term": {"is_public_domain": True}},
    {"term": {"artwork_type_id": 1}},
    {"exists": {"field": "image_id"}},
]}}}, separators=(",", ":"))
# Built with + rather than %, since the quoted query is full of % signs.
ARTIC_SEARCH = "https://api.artic.edu/api/v1/artworks/search?limit=10&fields=id,title,image_id&params=" + \
    urllib.parse.quote(ARTIC_QUERY) + "&page="
ARTIC_IMAGE = "https://www.artic.edu/iiif/2/%s/full/200,/0/default.jpg"
ARTIC_PAGES = 100


def _image_kind(data):
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return None


def _json(data):
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, AttributeError):
        return None


def _on_host(url, *hosts):
    """Only follow a link an API hands back if it's HTTPS on a host we expect."""
    if not isinstance(url, str):
        return False
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    return parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in hosts)


# ---- where each source gets a picture (raw image bytes, or None) --------

def download_cat(fetch):
    listing = _json(fetch(THECATAPI))
    try:
        url = listing[0]["url"]
    except (KeyError, IndexError, TypeError):
        url = None
    if _on_host(url, "thecatapi.com"):
        data = fetch(url)
        if data and _image_kind(data):
            return data, "TheCatAPI"
    data = fetch(CATAAS)
    if data and _image_kind(data):
        return data, "CATAAS"
    return None, ""


def download_space(fetch):
    query = random.choice(SPACE_QUERIES)
    for page in (random.randint(1, 3), 1):
        listing = _json(fetch(NASA_SEARCH % (page, urllib.parse.quote(query))))
        try:
            items = listing["collection"]["items"]
        except (KeyError, TypeError):
            items = []
        links = [link.get("href") for item in items if isinstance(item, dict)
                 for link in (item.get("links") or [])[:1] if isinstance(link, dict)]
        links = [url for url in links if _on_host(url, "images-assets.nasa.gov")]
        if links:
            data = fetch(random.choice(links))
            if data and _image_kind(data):
                return data, "NASA"
            return None, ""
    return None, ""


def download_earth(fetch):
    listing = _json(fetch(EPIC_LIST))
    shots = []
    for shot in listing if isinstance(listing, list) else []:
        try:
            name, date = shot["image"], shot["date"]
        except (KeyError, TypeError):
            continue
        day = re.match(r"(\d{4})-(\d{2})-(\d{2}) ", str(date))
        if day and re.fullmatch(r"[A-Za-z0-9_]+", str(name)):
            shots.append(EPIC_IMAGE % (day.group(1), day.group(2), day.group(3), name))
    if shots:
        data = fetch(random.choice(shots))
        if data and _image_kind(data):
            return data, "NASA EPIC"
    return None, ""


def download_art(fetch):
    listing = _json(fetch(ARTIC_SEARCH + str(random.randint(1, ARTIC_PAGES))))
    works = listing.get("data") if isinstance(listing, dict) else None
    ids = []
    for work in works if isinstance(works, list) else []:
        image_id = work.get("image_id") if isinstance(work, dict) else None
        if isinstance(image_id, str) and re.fullmatch(r"[0-9a-f-]{36}", image_id):
            ids.append(image_id)
    if ids:
        data = fetch(ARTIC_IMAGE % random.choice(ids))
        if data and _image_kind(data):
            return data, "Art Institute of Chicago"
    return None, ""


# ---- the night sky, drawn here ------------------------------------------

# A new moon to count from (2000-01-06 18:14 UTC) and the average lunar month.
NEW_MOON = datetime.datetime(2000, 1, 6, 18, 14, tzinfo=datetime.timezone.utc)
SYNODIC_DAYS = 29.530588853


def moon_phase(when=None):
    """Where the moon is in its month: 0 new, 0.25 first quarter, 0.5 full, 0.75 last quarter."""
    when = when or datetime.datetime.now(datetime.timezone.utc)
    days = (when - NEW_MOON).total_seconds() / 86400.0
    return (days / SYNODIC_DAYS) % 1.0


def night_sky(phase=None, rng=None):
    """A 64x54 sky: stars, sometimes a faint Milky Way, and the moon as it is tonight."""
    rng = rng or random.Random()
    phase = moon_phase() if phase is None else phase
    frame = bytearray(render.FRAME_BYTES)

    def add(x, y, r, g, b):
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            i = 3 * (y * WIDTH + x)
            frame[i] = min(255, frame[i] + r)
            frame[i + 1] = min(255, frame[i + 1] + g)
            frame[i + 2] = min(255, frame[i + 2] + b)

    if rng.random() < 0.5:
        # A diagonal band of very dim stars.
        slope, offset = rng.uniform(-0.8, 0.8), rng.uniform(10, 44)
        for _ in range(260):
            x = rng.randrange(WIDTH)
            y = int(offset + slope * (x - WIDTH / 2) + rng.gauss(0, 4))
            level = rng.randint(6, 18)
            add(x, y, level, level, level + 6)
    tints = ((255, 255, 255), (200, 215, 255), (255, 235, 200), (255, 210, 180))
    for _ in range(rng.randint(45, 75)):
        # Most stars barely show; a few are bright.
        level = 30 + int(200 * rng.random() ** 3)
        r, g, b = rng.choice(tints)
        add(rng.randrange(WIDTH), rng.randrange(HEIGHT), r * level // 255, g * level // 255, b * level // 255)

    radius = 9
    cx, cy = rng.randint(14, WIDTH - 15), rng.randint(12, HEIGHT - 13)
    turn = math.cos(2 * math.pi * phase)
    for y in range(-radius, radius + 1):
        half = math.sqrt(max(0.0, radius * radius - y * y))
        for x in range(-radius, radius + 1):
            if x * x + y * y > radius * radius:
                continue
            i = 3 * ((cy + y) * WIDTH + cx + x)
            across = x / half if half else 0.0
            # Waxing, the right side is lit; waning, the left (northern sky).
            lit = across > turn if phase < 0.5 else across < -turn
            if lit:
                # A little darker toward the edge, and a few grey "seas".
                level = 150 + int(70 * (1 - (x * x + y * y) / (radius * radius)))
                if (x * 7 + y * 13) % 11 < 2 and abs(x) < radius - 2:
                    level -= 45
                frame[i:i + 3] = bytes((level, level, max(0, level - 15)))
            else:
                frame[i:i + 3] = bytes((10, 10, 14))  # earthshine
    return bytes(frame)


# ---- sources -------------------------------------------------------------

class PhotoSource:
    """One API, with its stash of pictures for when the network is down."""

    def __init__(self, name, download, prefix=None, fill=True, ybias=0.5, directory=None, fetch=None):
        self.name = name
        self.download = download
        self.prefix = prefix or name
        self.fill = fill
        self.ybias = ybias
        self.directory = directory
        self.fetch = fetch or render._fetch
        self.last = None

    def _dir(self):
        if self.directory:
            return self.directory
        return os.path.join(PICTURES_DIR, self.name) if PICTURES_DIR else None

    def stash(self):
        directory = self._dir()
        if not directory:
            return []
        try:
            names = [n for n in os.listdir(directory)
                     if n.startswith(self.prefix + "-") and n.rsplit(".", 1)[-1] in ("jpg", "png")]
        except OSError:
            return []
        return sorted(os.path.join(directory, n) for n in names)

    def _save(self, data):
        directory = self._dir()
        if not directory or len(data) > render.MAX_ART_BYTES:
            return None
        path = os.path.join(directory, "%s-%d.%s" % (self.prefix, int(time.time() * 1000), _image_kind(data)))
        try:
            os.makedirs(directory, exist_ok=True)
            with open(path + ".tmp", "wb") as handle:
                handle.write(data)
            os.replace(path + ".tmp", path)
        except OSError:
            return None
        for old in self.stash()[:-STASH_SIZE]:
            try:
                os.remove(old)
            except OSError:
                pass
        return path

    def next_path(self):
        """A fresh download, or a stashed picture other than the last; (path, where from)."""
        data, origin = self.download(self.fetch) if self._dir() else (None, "")
        path = self._save(data) if data else None
        if not path:
            choices = [p for p in self.stash() if p != self.last] or self.stash()
            path = random.choice(choices) if choices else None
            origin = "stash" if path else ""
        if path:
            self.last = path
        return path, origin

    def next_frame(self):
        """(64x54 frame, where from), or (None, "") if there's nothing to show."""
        for _ in range(3):  # a broken download shouldn't mean no picture
            path, origin = self.next_path()
            if not path:
                return None, ""
            frame = render.decode_image(path, fill=self.fill, ybias=self.ybias)
            if frame:
                return render.lift(render.sharpen(frame), render.ART_GAMMA), origin
            try:
                os.remove(path)
            except OSError:
                pass
        return None, ""


class SkySource:
    name = "sky"

    def next_frame(self):
        return night_sky(), ""


def default_sources():
    return {
        # Cats' faces sit a little above the middle of most photos. The folder
        # and file names are the ones the first cats version used, so its stash carries over.
        "cats": PhotoSource("cats", download_cat, prefix="cat", ybias=0.4),
        "space": PhotoSource("space", download_space),
        # EPIC is the whole Earth on black: letterbox it so none of it is cut off.
        "earth": PhotoSource("earth", download_earth, fill=False),
        "art": PhotoSource("art", download_art, ybias=0.4),
        "sky": SkySource(),
    }


# Mix leaves the cats out; pick Cats on its own to get them.
MIX = ("space", "earth", "art", "sky")


class PictureFeed:
    """Gets the next picture on a background thread; the service picks it up when it's ready.

    inline=True does the work in request() itself, for tests.
    """

    def __init__(self, sources=None, on_ready=None, inline=False):
        self.sources = sources or default_sources()
        self.on_ready = on_ready or (lambda: None)
        self.inline = inline
        self._lock = threading.Lock()
        self._thread = None
        self._ready = None
        self.last_source = ""

    def busy(self):
        thread = self._thread
        return bool(thread and thread.is_alive())

    def request(self, choice):
        """Start getting a picture for a source name, or "mix". Does nothing if one is on its way."""
        if self.busy():
            return
        if self.inline:
            self._work(choice)
            return
        self._thread = threading.Thread(target=self._work, args=(choice,), name="pixel-faceplate-pictures", daemon=True)
        self._thread.start()

    def take(self):
        """(frame or None, label) once a request has finished, else None."""
        with self._lock:
            ready, self._ready = self._ready, None
        return ready

    def _pick(self, choice):
        if choice != "mix":
            return choice
        names = [n for n in MIX if n in self.sources]
        others = [n for n in names if n != self.last_source] or names
        return random.choice(others)

    def _work(self, choice):
        name = self._pick(choice)
        source = self.sources.get(name) or self.sources["sky"]
        try:
            frame, origin = source.next_frame()
        except Exception:  # a bad picture from the web must not kill the thread quietly
            frame, origin = None, ""
        if frame is None and choice == "mix" and name != "sky":
            # Mix always has something: the sky needs no network.
            source = self.sources["sky"]
            frame, origin = source.next_frame()
        self.last_source = source.name
        label = LABELS.get(source.name, source.name) if frame else ""
        if frame and origin:
            label += ", from " + origin
        with self._lock:
            self._ready = (frame, label)
        self.on_ready()


LABELS = {"cats": "a cat", "space": "a space photo", "earth": "the whole Earth", "art": "a painting", "sky": "the night sky"}
