# Random cat photos for the panel between games.
#
# A new cat comes from a public cat API (TheCatAPI, then CATAAS as a backup)
# and is kept in a small stash in the plugin's folder. With no network, a cat
# from the stash is shown instead, so the panel still gets a different one.
# Each new cat is one flash write, so they change every few minutes, not faster.

import json
import os
import random
import time

from . import render

CATS_DIR = None  # set by main.py; None turns fetching off (the stash still works if given)
THECATAPI = "https://api.thecatapi.com/v1/images/search?mime_types=jpg,png&size=med"
CATAAS = "https://cataas.com/cat?width=640"
# How many cats to keep for offline use; the oldest go first.
STASH_SIZE = 40
# Cats' faces sit a little above the middle of most photos.
CAT_YBIAS = 0.4


def _image_kind(data):
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return None


class CatStash:
    def __init__(self, directory=None, fetch=None):
        self.directory = directory
        self.fetch = fetch or render._fetch
        self.last = None
        self.source = ""

    def _dir(self):
        return self.directory or CATS_DIR

    def stash(self):
        directory = self._dir()
        if not directory:
            return []
        try:
            names = [n for n in os.listdir(directory) if n.startswith("cat-") and n.rsplit(".", 1)[-1] in ("jpg", "png")]
        except OSError:
            return []
        return sorted(os.path.join(directory, n) for n in names)

    def _download(self):
        """Raw image bytes of a random cat from the first API that answers, or None."""
        listing = self.fetch(THECATAPI)
        if listing:
            try:
                url = json.loads(listing.decode("utf-8"))[0]["url"]
            except (ValueError, KeyError, IndexError, TypeError, UnicodeDecodeError):
                url = None
            if isinstance(url, str) and url.startswith("https://"):
                data = self.fetch(url)
                if data and _image_kind(data):
                    self.source = "TheCatAPI"
                    return data
        data = self.fetch(CATAAS)
        if data and _image_kind(data):
            self.source = "CATAAS"
            return data
        return None

    def _save(self, data):
        directory = self._dir()
        if not directory:
            return None
        path = os.path.join(directory, "cat-%d.%s" % (int(time.time() * 1000), _image_kind(data)))
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
        """Path of the next cat to show: a fresh download, or a stashed one other than the last."""
        data = self._download() if self._dir() else None
        path = self._save(data) if data else None
        if not path:
            choices = [p for p in self.stash() if p != self.last] or self.stash()
            path = random.choice(choices) if choices else None
            self.source = "stash" if path else ""
        if path:
            self.last = path
        return path

    def next_frame(self):
        """The next cat as a 64x54 frame, or None if there's no cat to be had."""
        for _ in range(3):  # a broken download shouldn't mean no cat
            path = self.next_path()
            if not path:
                return None
            frame = render.decode_image(path, fill=True, ybias=CAT_YBIAS)
            if frame:
                return render.lift(render.sharpen(frame), render.ART_GAMMA)
            try:
                os.remove(path)
            except OSError:
                pass
        return None
