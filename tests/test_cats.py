"""Random cats between games, and art fetched from Steam's CDN."""

import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from pixelface import cats, render, service  # noqa: E402
from pixelface.settings import DEFAULTS, validate  # noqa: E402
from test_service import FakeLink  # noqa: E402

FRAME = 64 * 54 * 3
JPEG = b"\xff\xd8\xff" + b"cat" * 50


class FakeWeb:
    def __init__(self, online=True):
        self.online = online
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if not self.online:
            return None
        if url == cats.THECATAPI:
            return json.dumps([{"url": "https://cdn2.thecatapi.com/images/abc.jpg"}]).encode()
        if url.startswith("https://cdn2.thecatapi.com/"):
            return JPEG + str(len(self.urls)).encode()
        return None


class StashTest(unittest.TestCase):
    def test_downloads_then_falls_back_to_the_stash(self):
        web = FakeWeb()
        with tempfile.TemporaryDirectory() as folder:
            stash = cats.CatStash(folder, web)
            first = stash.next_path()
            self.assertTrue(os.path.basename(first).startswith("cat-"))
            self.assertEqual(stash.source, "TheCatAPI")
            time.sleep(0.002)
            second = stash.next_path()
            web.online = False
            third = stash.next_path()  # offline: an earlier cat, not the one just shown
            self.assertEqual(stash.source, "stash")
            self.assertIn(third, (first,))
            self.assertNotEqual(third, second)

    def test_cataas_is_the_backup(self):
        def web(url):
            return JPEG if url == cats.CATAAS else None
        with tempfile.TemporaryDirectory() as folder:
            stash = cats.CatStash(folder, web)
            self.assertIsNotNone(stash.next_path())
            self.assertEqual(stash.source, "CATAAS")

    def test_not_an_image_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            stash = cats.CatStash(folder, lambda url: b"<html>rate limited</html>")
            self.assertIsNone(stash.next_path())

    def test_stash_is_capped(self):
        web = FakeWeb()
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(cats, "STASH_SIZE", 3):
            stash = cats.CatStash(folder, web)
            for _ in range(5):
                stash.next_path()
                time.sleep(0.002)
            self.assertEqual(len(stash.stash()), 3)

    def test_settings(self):
        self.assertEqual(validate({"artwork_idle": "cats", "cat_interval": 30}),
                         {"artwork_idle": "cats", "cat_interval": 30})
        with self.assertRaises(ValueError):
            validate({"cat_interval": 0})


class FakeCats:
    def __init__(self):
        self.count = 0
        self.source = "TheCatAPI"

    def next_frame(self):
        self.count += 1
        return bytes([self.count * 10]) * FRAME


@mock.patch.object(service, "find_port", lambda: "/dev/ttyUSB0")
@mock.patch.object(service, "MIN_UPLOAD_GAP", 0)
@mock.patch.object(render, "running_appid", lambda: 0)
@mock.patch.object(render, "artwork", lambda appid, **_: bytes([90]) * FRAME)
class ServiceCatsTest(unittest.TestCase):
    def setUp(self):
        FakeLink.instances = []
        self.svc = service.FaceplateService(dict(DEFAULTS, mode="artwork", artwork_idle="cats", cat_interval=10),
                                            link_factory=FakeLink)
        self.svc.cats = FakeCats()

    def gifs(self):
        return len(FakeLink.instances[0].gifs)

    def test_one_cat_until_the_interval_is_up(self):
        self.svc.step()
        self.svc.step()
        self.assertEqual(self.svc.cats.count, 1)
        self.assertEqual(self.gifs(), 1)
        self.svc.cat_due = time.monotonic() - 1  # ten minutes later
        self.svc.step()
        self.assertEqual(self.svc.cats.count, 2)
        self.assertEqual(self.gifs(), 2)

    def test_game_art_wins_and_the_same_cat_comes_back(self):
        self.svc.step()
        self.svc.game_event(570, True)
        self.svc.step()
        self.svc.game_event(570, False)
        self.svc.step()
        self.assertEqual(self.svc.cats.count, 1)  # no new download for the same cat
        self.assertEqual(self.gifs(), 3)  # cat, game, cat

    def test_next_cat_button(self):
        self.svc.step()
        self.svc.next_cat()
        self.svc.step()
        self.assertEqual(self.svc.cats.count, 2)

    def test_no_cat_falls_back_to_the_steam_logo(self):
        self.svc.cats.next_frame = lambda: None
        with mock.patch.object(render, "steam_logo", lambda: bytes([7]) * FRAME):
            self.svc.step()
        self.assertIn("Steam logo", self.svc.detail)


class DownloadTest(unittest.TestCase):
    def test_fetches_once_and_remembers_misses(self):
        jpeg = b"\xff\xd8\xff" + b"x" * 100
        calls = []

        def fetch(url):
            calls.append(url)
            return jpeg if "library_hero" in url else None

        with tempfile.TemporaryDirectory() as folder:
            path = render.downloaded_art(292030, "hero", folder, fetch)
            self.assertTrue(path.endswith("292030_hero.jpg"))
            self.assertEqual(render.downloaded_art(292030, "hero", folder, fetch), path)
            self.assertIsNone(render.downloaded_art(292030, "logo", folder, fetch))
            before = len(calls)
            self.assertIsNone(render.downloaded_art(292030, "logo", folder, fetch))
            self.assertEqual(len(calls), before)  # the miss is remembered
            self.assertIsNone(render.downloaded_art(3045812345, "hero", folder, fetch))  # shortcut



if __name__ == "__main__":
    unittest.main()
